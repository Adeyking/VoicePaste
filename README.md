# 🎙️ VoicePaste (Desktop)

**System-wide push-to-talk dictation for Windows — local, private, and fast.**

VoicePaste lets you hold a hotkey, speak, and have your words transcribed and cleaned up by a local AI model, then pasted wherever your cursor is. No cloud required. Your audio never leaves your network.

> Inspired by [Wispr Flow](https://www.wispr.ai/) — built entirely on open-source local AI.

---

## ✨ Features

- **Push-to-talk** — hold `Ctrl + Numpad 0` to record, release to transcribe and paste
- **Live preview** — text appears on screen as you speak (partial transcript mode)
- **Local AI cleanup** — a local LLM (via [Ollama](https://ollama.com/)) fixes grammar and removes filler words before pasting
- **Fast and Quality profiles** — swap between a quick small model and a higher-quality model on the fly
- **Voice commands** — say _"new paragraph"_, _"scratch that"_, _"question mark"_ etc.
- **Multiple modes** — Dictation, Assistant, Journal, and Meeting transcription
- **Meeting mode** — continuous transcription saved to a Markdown file automatically
- **System tray** — warm state badge, live stats, settings window, all from the taskbar
- **Warm state tracking** — know at a glance if your model is `[warm]`, `[warming...]`, or `[cold]`
- **Privacy-first** — all processing happens on your LAN; nothing touches the internet by default

---

## 🧱 Requirements

| Component      | What you need                                                                                                                                                     |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows**    | Windows 10 or 11 (admin rights required for global hotkeys)                                                                                                       |
| **Python**     | 3.11+                                                                                                                                                             |
| **STT server** | A [Whisper](https://github.com/openai/whisper)-compatible HTTP server on your LAN (e.g. [faster-whisper-server](https://github.com/fedirz/faster-whisper-server)) |
| **Ollama**     | [Ollama](https://ollama.com/) running on your LAN with at least one model pulled                                                                                  |
| **Models**     | e.g. `ollama pull qwen2.5:3b` (fast) and `ollama pull phi4:latest` (quality)                                                                                      |

> **LAN setup:** Both the STT server and Ollama can run on the same machine as VoicePaste, or on a separate machine on your local network (e.g. a NUC or home server).

---

## 🚀 Quick Start

**1. Clone the repo and install dependencies**

```bash
git clone https://github.com/Adeyking/VoicePaste.git
cd VoicePaste
pip install -r requirements.txt
```

**2. Create your config file**

```bash
copy voicepaste.config.example.json voicepaste.config.json
```

Then edit `voicepaste.config.json` and set your server addresses:

```json
"STT_URL": "http://YOUR-SERVER-IP:8770/transcribe",
"OLLAMA_URL": "http://YOUR-SERVER-IP:11434"
```

**3. Run as Administrator** (required for global hotkeys)

```powershell
.\scripts\run_tray.ps1
```

A microphone icon will appear in your system tray.

**4. Speak!**
Hold `Ctrl + Alt`, say something, release — your words appear where your cursor is.

---

## ⌨️ Hotkeys

| Hotkey                 | Action                     |
| ---------------------- | -------------------------- |
| Hold `Ctrl + Alt`      | Record (Push-To-Talk)      |
| Release                | Transcribe + paste         |
| `Ctrl+Alt+1`           | Dictation mode             |
| `Ctrl+Alt+2`           | Assistant mode             |
| `Ctrl+Alt+3`           | Journal mode               |
| `Ctrl+Alt+9`           | Meeting mode               |
| `Ctrl+Alt+7`           | Fast model profile         |
| `Ctrl+Alt+8`           | Quality model profile      |
| `Ctrl+Alt+4`           | Assistant profile: Email   |
| `Ctrl+Alt+5`           | Assistant profile: Chat    |
| `Ctrl+Alt+6`           | Assistant profile: Neutral |

---

## 🗣️ Voice Commands

Say these while dictating — they are processed before pasting:

| Say                         | Result                                  |
| --------------------------- | --------------------------------------- |
| `"new paragraph"`           | Inserts a blank line                    |
| `"new line"`                | Inserts a line break                    |
| `"scratch that"`            | Deletes the last sentence               |
| `"actually"`                | Deletes the last sentence and continues |
| `"question mark"`           | Inserts `?`                             |
| `"period"`                  | Inserts `.`                             |
| `"comma"`                   | Inserts `,`                             |
| `"literal [voice command]"` | Types the phrase without applying it    |

---

## 🖥️ Tray Status Line

The second line in the tray menu shows:

```
dictation  |  fast (qwen2.5:3b) [warm]
```

- **Mode** — current input mode
- **Profile (model)** — active model profile and model name
- **Warm state** — `[warm]` / `[warming...]` / `[cold]` / `[warm error]`
- **Meeting indicator** — `meeting: 14s` (elapsed seconds in current chunk)

---

## ⚙️ Configuration

Copy `voicepaste.config.example.json` → `voicepaste.config.json` and edit as needed.
The Settings window (tray → Open → Settings) lets you change most settings with a UI.

Key settings:

| Key                          | Default       | Description                              |
| ---------------------------- | ------------- | ---------------------------------------- |
| `STT_URL`                    | —             | Your Whisper STT server URL              |
| `OLLAMA_URL`                 | —             | Your Ollama server URL                   |
| `MODEL_PROFILE`              | `fast`        | `fast` or `quality`                      |
| `FAST_MODEL`                 | `qwen2.5:3b`  | Model used for fast cleanup              |
| `QUALITY_MODEL`              | `phi4:latest` | Model used for quality cleanup           |
| `OLLAMA_KEEP_ALIVE`          | `20m`         | How long Ollama keeps model in VRAM      |
| `PARTIAL_TRANSCRIPT_ENABLED` | `true`        | Show live text preview while speaking    |
| `VOICE_COMMANDS_ENABLED`     | `true`        | Enable spoken commands                   |
| `WARMUP_ENABLED`             | `true`        | Auto-warm model on profile selection     |
| `CLOUD_FALLBACK_ENABLED`     | `false`       | Allow fallback to cloud model on timeout |

### Phrase corrections

Create a JSON file at `PHRASE_CORRECTIONS_PATH`:

```json
{
  "exact": {
    "gonna": "going to",
    "NucBox": "NucBox"
  },
  "regex": []
}
```

### Snippets

Create a JSON file at `SNIPPETS_PATH`:

```json
{
  "exact": {
    "my email": "your.email@example.com"
  }
}
```

---

## 📁 Transcript Storage

All transcripts are saved automatically to Markdown files:

| Mode                  | Saved to                                    |
| --------------------- | ------------------------------------------- |
| Dictation / Assistant | `<VOICE_PASTE_ROOT>\inbox\YYYY-MM-DD.md`    |
| Journal               | `<VOICE_PASTE_ROOT>\journal\YYYY-MM-DD.md`  |
| Meeting               | `<VOICE_PASTE_ROOT>\meetings\YYYY-MM-DD.md` |

---

## 🛠️ Troubleshooting

**Hotkeys not working?**

- Run VoicePaste as Administrator
- Make sure Num Lock is on for numpad hotkeys
- Restart via `.\scripts\voice_stop.ps1` then `.\scripts\run_tray.ps1`

**Model shows `[cold]` immediately after warmup?**

- Check Ollama is running and the model name in config exactly matches the pulled model name (e.g. `qwen2.5:3b`)

**Text pasted without cleanup?**

- The local model timed out; VoicePaste pastes raw text immediately and continues refining in the background
- The improved version is copied to your clipboard automatically when ready (tray notification will appear)

**Diagnostics:**

```powershell
.\scripts\voice_diagnose.ps1
.\scripts\voice_health_report.ps1
```

---

## 🧪 Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## 📄 Licence

MIT — do whatever you like with it.
