param(
    [string]$ConfigPath = "",
    [string]$OllamaUrl = "",
    [string[]]$Models = @("qwen2.5:1.5b", "llama3.2:3b", "qwen2.5:3b"),
    [int]$ShortRuns = 10,
    [int]$MediumRuns = 10
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common_config.ps1")
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repoRoot "voicepaste.config.json"
}

$resolved = Get-VoicePasteResolvedConfig -ConfigPath $ConfigPath -RepoRoot $repoRoot
if (-not $OllamaUrl) {
    $OllamaUrl = [string]$resolved.OLLAMA_URL
}
$keepAlive = if ($resolved.OLLAMA_KEEP_ALIVE) { [string]$resolved.OLLAMA_KEEP_ALIVE } else { "20m" }

$endpoint = $OllamaUrl.TrimEnd("/") + "/api/generate"
$shortSamples = @(
    "please send the invoice today",
    "book the dentist for next week",
    "i will call you this afternoon",
    "meeting moved to 3 pm",
    "remember to buy batteries",
    "send a quick status update",
    "i am running five minutes late",
    "finish the dashboard review",
    "this note should be cleaner",
    "thanks for your help"
)
$mediumSamples = @(
    "hi team i wanted to share a quick update on the project timeline we have completed the first milestone and will start testing tomorrow please flag any blockers before noon",
    "can you draft a polite email to the supplier asking for delivery confirmation and include that we need the shipment by friday to avoid delays",
    "i am dictating this as a journal note today felt productive but i need to improve focus and reduce context switching during the afternoon",
    "please rewrite this message so it sounds clear and professional while keeping the exact meaning and details unchanged",
    "for the meeting summary include actions owners and deadlines and make the language concise enough for a quick read",
    "i want to explain that the model was fast enough for normal dictation but struggled when i gave very long instructions in one go",
    "this is a longer transcript sample intended to test latency variance and output consistency across multiple inference runs",
    "before we ship this update we should verify startup reliability preflight checks and fallback behavior for temporary network failures",
    "write a friendly follow up message that asks whether the customer still needs help and offer two available times for a call",
    "capture this spoken text and clean it lightly remove filler words fix punctuation and keep the same meaning throughout"
)

function Clamp-Score {
    param(
        [double]$Value,
        [double]$Min = 0,
        [double]$Max = 100
    )

    if ($Value -lt $Min) { return $Min }
    if ($Value -gt $Max) { return $Max }
    return [math]::Round($Value, 1)
}

function Evaluate-ResponseQuality {
    param(
        [string]$InputText,
        [string]$OutputText
    )

    $flags = New-Object System.Collections.Generic.List[string]
    $output = ([string]$OutputText).Trim()
    $input = ([string]$InputText).Trim()

    if ([string]::IsNullOrWhiteSpace($output)) {
        $flags.Add("empty_output")
        return [pscustomobject]@{
            quality_score = 0.0
            compliant = $false
            flags = ($flags -join ";")
        }
    }

    $score = 100.0

    if ($output -match "(?im)^(cleaned transcript|transcript|output)\s*[:\-]") {
        $score -= 35
        $flags.Add("boilerplate_header")
    }
    if ($output -match "(?im)^(```|[-*]\s+)") {
        $score -= 20
        $flags.Add("formatting_noise")
    }
    if ($output -match "(?i)\b(here(?:'s| is)|sure|certainly|absolutely)\b") {
        $score -= 10
        $flags.Add("assistant_preface")
    }

    $inputLen = [math]::Max($input.Length, 1)
    $ratio = $output.Length / $inputLen
    if ($ratio -gt 1.40) {
        $score -= 20
        $flags.Add("too_verbose")
    }
    if ($ratio -lt 0.35) {
        $score -= 20
        $flags.Add("over_compressed")
    }

    $newlineCount = ([regex]::Matches($output, "`n")).Count
    if ($newlineCount -gt 3) {
        $score -= 10
        $flags.Add("too_many_line_breaks")
    }

    $score = Clamp-Score -Value $score
    $compliant = $score -ge 70 -and -not ($flags -contains "boilerplate_header")

    return [pscustomobject]@{
        quality_score = $score
        compliant = $compliant
        flags = ($flags -join ";")
    }
}

function Invoke-Model {
    param(
        [string]$Model,
        [string]$Text
    )

    $prompt = @"
You are a strict transcript cleaner.
Keep same meaning, fix punctuation, remove filler words.
Output cleaned text only.

Transcript:
$Text
"@

    $body = @{
        model = $Model
        prompt = $prompt
        stream = $false
        keep_alive = $keepAlive
        options = @{
            temperature = 0
            num_predict = 160
        }
    } | ConvertTo-Json -Depth 8

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $resp = Invoke-RestMethod -Uri $endpoint -Method Post -Body $body -ContentType "application/json" -TimeoutSec 45
        $sw.Stop()
        $responseText = [string]$resp.response
        $quality = Evaluate-ResponseQuality -InputText $Text -OutputText $responseText
        return [pscustomobject]@{
            ok = $true
            ms = $sw.ElapsedMilliseconds
            chars = $responseText.Length
            response = $responseText
            quality_score = $quality.quality_score
            compliant = $quality.compliant
            quality_flags = $quality.flags
            error = ""
        }
    }
    catch {
        $sw.Stop()
        return [pscustomobject]@{
            ok = $false
            ms = $sw.ElapsedMilliseconds
            chars = 0
            response = ""
            quality_score = 0.0
            compliant = $false
            quality_flags = "request_failed"
            error = [string]$_
        }
    }
}

function Get-Percentile {
    param(
        [double[]]$Values,
        [double]$P
    )
    if (-not $Values -or $Values.Count -eq 0) {
        return [double]::NaN
    }
    $sorted = $Values | Sort-Object
    $idx = [math]::Ceiling(($P / 100.0) * $sorted.Count) - 1
    if ($idx -lt 0) { $idx = 0 }
    if ($idx -ge $sorted.Count) { $idx = $sorted.Count - 1 }
    return [double]$sorted[$idx]
}

$results = @()
Write-Output "Endpoint: $endpoint"
Write-Output "KeepAlive: $keepAlive"
Write-Output "Models: $($Models -join ', ')"

foreach ($model in $Models) {
    Write-Output "Running benchmark for model: $model"

    for ($i = 0; $i -lt $ShortRuns; $i++) {
        $sample = $shortSamples[$i % $shortSamples.Count]
        $row = Invoke-Model -Model $model -Text $sample
        $results += [pscustomobject]@{
            model = $model
            bucket = "short"
            iteration = $i + 1
            ok = $row.ok
            ms = $row.ms
            chars = $row.chars
            response = $row.response
            quality_score = $row.quality_score
            compliant = $row.compliant
            quality_flags = $row.quality_flags
            error = $row.error
        }
    }

    for ($i = 0; $i -lt $MediumRuns; $i++) {
        $sample = $mediumSamples[$i % $mediumSamples.Count]
        $row = Invoke-Model -Model $model -Text $sample
        $results += [pscustomobject]@{
            model = $model
            bucket = "medium"
            iteration = $i + 1
            ok = $row.ok
            ms = $row.ms
            chars = $row.chars
            response = $row.response
            quality_score = $row.quality_score
            compliant = $row.compliant
            quality_flags = $row.quality_flags
            error = $row.error
        }
    }
}

$summary = @()
$groups = $results | Group-Object model, bucket
foreach ($group in $groups) {
    $parts = $group.Name -split ","
    $model = $parts[0].Trim()
    $bucket = $parts[1].Trim()
    $okRows = $group.Group | Where-Object { $_.ok -eq $true }
    $msValues = @($okRows | ForEach-Object { [double]$_.ms })
    $qualityValues = @($okRows | ForEach-Object { [double]$_.quality_score })
    $compliantRows = @($okRows | Where-Object { $_.compliant -eq $true })

    $summary += [pscustomobject]@{
        model = $model
        bucket = $bucket
        runs = $group.Count
        success = $okRows.Count
        success_rate = if ($group.Count -gt 0) { [math]::Round((100.0 * $okRows.Count / $group.Count), 1) } else { [double]::NaN }
        compliance_rate = if ($okRows.Count -gt 0) { [math]::Round((100.0 * $compliantRows.Count / $okRows.Count), 1) } else { [double]::NaN }
        avg_quality = if ($qualityValues.Count -gt 0) { [math]::Round(($qualityValues | Measure-Object -Average).Average, 1) } else { [double]::NaN }
        avg_ms = if ($msValues.Count -gt 0) { [math]::Round(($msValues | Measure-Object -Average).Average, 1) } else { [double]::NaN }
        p50_ms = if ($msValues.Count -gt 0) { [math]::Round((Get-Percentile -Values $msValues -P 50), 1) } else { [double]::NaN }
        p95_ms = if ($msValues.Count -gt 0) { [math]::Round((Get-Percentile -Values $msValues -P 95), 1) } else { [double]::NaN }
    }
}

function Get-ModelRollup {
    param(
        [object[]]$Rows
    )

    $okRows = @($Rows | Where-Object { $_.ok -eq $true })
    $msValues = @($okRows | ForEach-Object { [double]$_.ms })
    $qualityValues = @($okRows | ForEach-Object { [double]$_.quality_score })
    $complianceRate = if ($okRows.Count -gt 0) {
        [math]::Round((100.0 * (@($okRows | Where-Object { $_.compliant -eq $true }).Count) / $okRows.Count), 1)
    } else {
        [double]::NaN
    }
    [pscustomobject]@{
        runs = $Rows.Count
        success = $okRows.Count
        success_rate = if ($Rows.Count -gt 0) { [math]::Round((100.0 * $okRows.Count / $Rows.Count), 1) } else { [double]::NaN }
        p50_all_ms = if ($msValues.Count -gt 0) { [math]::Round((Get-Percentile -Values $msValues -P 50), 1) } else { [double]::NaN }
        p95_all_ms = if ($msValues.Count -gt 0) { [math]::Round((Get-Percentile -Values $msValues -P 95), 1) } else { [double]::NaN }
        avg_quality = if ($qualityValues.Count -gt 0) { [math]::Round(($qualityValues | Measure-Object -Average).Average, 1) } else { [double]::NaN }
        compliance_rate = $complianceRate
    }
}

$modelRollups = @()
foreach ($modelGroup in ($results | Group-Object model)) {
    $rollup = Get-ModelRollup -Rows $modelGroup.Group
    $modelRollups += [pscustomobject]@{
        model = $modelGroup.Name
        runs = $rollup.runs
        success = $rollup.success
        success_rate = $rollup.success_rate
        p50_all_ms = $rollup.p50_all_ms
        p95_all_ms = $rollup.p95_all_ms
        avg_quality = $rollup.avg_quality
        compliance_rate = $rollup.compliance_rate
    }
}

$validP50 = @($modelRollups | Where-Object { -not [double]::IsNaN([double]$_.p50_all_ms) -and $_.p50_all_ms -gt 0 })
$bestP50 = if ($validP50.Count -gt 0) { ($validP50 | Measure-Object -Property p50_all_ms -Minimum).Minimum } else { [double]::NaN }

$ranking = @()
foreach ($row in $modelRollups) {
    $latencyScore = if (-not [double]::IsNaN([double]$bestP50) -and -not [double]::IsNaN([double]$row.p50_all_ms) -and $row.p50_all_ms -gt 0) {
        Clamp-Score -Value ((100.0 * $bestP50) / $row.p50_all_ms)
    } else {
        0.0
    }
    $qualityComplianceScore = if (-not [double]::IsNaN([double]$row.avg_quality) -and -not [double]::IsNaN([double]$row.compliance_rate)) {
        Clamp-Score -Value ((0.7 * [double]$row.avg_quality) + (0.3 * [double]$row.compliance_rate))
    } else {
        0.0
    }
    $weightedScore = [math]::Round((0.6 * $latencyScore) + (0.4 * $qualityComplianceScore), 1)
    $ranking += [pscustomobject]@{
        model = $row.model
        weighted_score = $weightedScore
        latency_score = $latencyScore
        quality_compliance_score = $qualityComplianceScore
        success_rate = $row.success_rate
        compliance_rate = $row.compliance_rate
        p50_all_ms = $row.p50_all_ms
        p95_all_ms = $row.p95_all_ms
        avg_quality = $row.avg_quality
    }
}

Write-Output ""
Write-Output "Benchmark summary:"
$summary | Sort-Object model, bucket | Format-Table -AutoSize

Write-Output ""
Write-Output "Model rollup:"
$modelRollups | Sort-Object p50_all_ms | Format-Table -AutoSize

Write-Output ""
Write-Output "Weighted ranking (60% latency, 40% quality/compliance):"
$ranking = $ranking | Sort-Object weighted_score -Descending
$ranking | Format-Table -AutoSize

$recommended = $ranking | Select-Object -First 1
if ($recommended) {
    Write-Output ""
    Write-Output ("Recommended quick model: {0} (score={1}, p50={2}ms, quality={3})" -f $recommended.model, $recommended.weighted_score, $recommended.p50_all_ms, $recommended.avg_quality)
}

$artifactDir = Join-Path $repoRoot "artifacts"
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$rawPath = Join-Path $artifactDir "cleanup_benchmark_raw_$stamp.json"
$summaryPath = Join-Path $artifactDir "cleanup_benchmark_summary_$stamp.json"
$rankingPath = Join-Path $artifactDir "cleanup_benchmark_ranking_$stamp.json"
$results | ConvertTo-Json -Depth 6 | Set-Content -Path $rawPath -Encoding UTF8
$summaryPayload = [pscustomobject]@{
    by_bucket = $summary
    model_rollup = $modelRollups
}
$summaryPayload | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryPath -Encoding UTF8
$ranking | ConvertTo-Json -Depth 8 | Set-Content -Path $rankingPath -Encoding UTF8

Write-Output ""
Write-Output "Saved raw results: $rawPath"
Write-Output "Saved summary:     $summaryPath"
Write-Output "Saved ranking:     $rankingPath"
