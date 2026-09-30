# 🎙️ VoicePaste

**System-wide push-to-talk voice dictation for Linux (Wayland / Omarchy) and Windows: local, private, and fast.**

VoicePaste lets you tap or hold a shortcut, speak, and have your speech transcribed and cleaned up by a local AI model, then pasted directly wherever your cursor is. No cloud required. Your audio never leaves your network.

> Inspired by [Wispr Flow](https://www.wispr.ai/), built entirely on open-source local AI.

---

## ✨ Features

* **Cross-platform**: native client script for Linux (Wayland, Hyprland, Omarchy) and full system-tray app for Windows
* **Flexible dictation**: hold to talk on Windows (`Ctrl + Alt`) or tap-to-toggle on Linux (`Super + Ctrl + X`)
* **Instant text polish**: lightning-fast (<0.1ms) regex cleanup to strip filler words (`um`, `uh`, `er`, `ah`) and stutter repeats
* **Live preview**: text appears on screen as you speak (partial transcript mode)
* **Quick-add vocabulary (`Ctrl + Alt + W`)**: capture highlighted or clipboard terms straight into your exact dictionary and sync across devices
* **Active-window context injection**: reads the focused window title to seed Whisper with relevant project keywords and terminology
* **Buffer guardrail**: automatic 120-second recording cutoff prevents runaway memory use if hotkeys stick
* **Voice commands**: say _"new paragraph"_, _"scratch that"_, _"question mark"_, etc.
* **Privacy-first**: all processing happens on your LAN; nothing touches the internet by default

---

## 🧱 Requirements

| Component | Linux (Wayland / Omarchy) | Windows |
| :--- | :--- | :--- |
| **Operating System** | Arch Linux, Omarchy, or any Wayland compositor (Hyprland, Sway) | Windows 10 or 11 (admin rights for global hotkeys) |
| **Audio Capture** | PipeWire (`pw-record`) | Python `sounddevice` |
| **Text Delivery** | `wtype` (with `wl-copy` fallback) | Windows virtual keystrokes / clipboard |
| **Utilities** | `curl`, `jq`, `ffmpeg` (optional for silence trim) | Python 3.11+ |
| **STT Backend** | Whisper HTTP server on your LAN (e.g. `faster-whisper` on port 8770) | Whisper HTTP server on your LAN |

---

## 🚀 Quick Start

### Option A: Linux (Wayland / Hyprland / Omarchy)

**1. Install dependencies**

On Arch Linux / Omarchy:

```bash
sudo pacman -S pipewire-utils wtype wl-clipboard curl jq ffmpeg
```

**2. Install the client script**

```bash
mkdir -p ~/.local/bin ~/.config/voicepaste
cp scripts/linux/voicepaste ~/.local/bin/voicepaste
chmod +x ~/.local/bin/voicepaste
cp scripts/linux/voicepaste.env.example ~/.config/voicepaste/env
```

Edit `~/.config/voicepaste/env` to point to your Whisper server URL (e.g. `http://YOUR-SERVER-IP:8770`).

**3. Bind the hotkey**

In Hyprland (`~/.config/hypr/hyprland.conf` or `bindings.lua`):

```lua
-- In bindings.lua:
o.bind("SUPER + CTRL + X", "Dictate", "/home/USERNAME/.local/bin/voicepaste")
```

Or in standard Hyprland config:

```ini
bind = SUPER CTRL, X, exec, ~/.local/bin/voicepaste
```

**4. Speak!**
Press `Super + Ctrl + X` to start recording, speak naturally, then press `Super + Ctrl + X` again to transcribe and paste directly at your cursor.

---

### Option B: Windows

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

Edit `voicepaste.config.json` with your server addresses:

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
Hold `Ctrl + Alt`, say something, release: your words appear where your cursor is.

---

## ⌨️ Hotkeys Reference

### Linux (Wayland)

| Hotkey | Action |
| :--- | :--- |
| `Super + Ctrl + X` | Toggle dictation (first press starts recording, second press transcribes and types at cursor) |

### Windows

| Hotkey | Action |
| :--- | :--- |
| Hold `Ctrl + Alt` | Record (Push-To-Talk) |
| Release | Transcribe and paste at cursor |
| `Ctrl+Alt+W` | Quick-add term (save clipboard to vocabulary) |
| `Ctrl+Alt+1` | Dictation mode |
| `Ctrl+Alt+2` | Assistant mode |
| `Ctrl+Alt+3` | Journal mode |
| `Ctrl+Alt+9` | Meeting mode |
| `Ctrl+Alt+7` | Fast model profile |
| `Ctrl+Alt+8` | Quality model profile |
| `Ctrl+Alt+4` | Assistant profile: Email |
| `Ctrl+Alt+5` | Assistant profile: Chat |
| `Ctrl+Alt+6` | Assistant profile: Neutral |

---

## 🗣️ Voice Commands

Say these while dictating: they are processed before pasting:

| Say | Result |
| :--- | :--- |
| `"new paragraph"` | Inserts a blank line |
| `"new line"` | Inserts a line break |
| `"scratch that"` | Deletes the last sentence |
| `"question mark"` | Inserts `?` |
| `"period"` | Inserts `.` |
| `"comma"` | Inserts `,` |
| `"literal [voice command]"` | Types the phrase without applying it |

---

## 🖥️ Windows Tray Status Line

The second line in the tray menu shows:

```
dictation  |  fast (qwen2.5:3b) [warm]
```

* **Mode**: current input mode
* **Profile (model)**: active model profile and model name
* **Warm state**: `[warm]` / `[warming...]` / `[cold]` / `[warm error]`
* **Meeting indicator**: `meeting: 14s` (elapsed seconds in current chunk)

---

## ⚙️ Configuration (Windows)

Copy `voicepaste.config.example.json` to `voicepaste.config.json` and edit as needed.
The Settings window (tray -> Open -> Settings) lets you change most settings with a UI.

Key settings:

| Key | Default | Description |
| :--- | :--- | :--- |
| `STT_URL` | `None` | Your Whisper STT server URL |
| `OLLAMA_URL` | `None` | Your Ollama server URL |
| `MODEL_PROFILE` | `fast` | `fast` or `quality` |
| `FAST_MODEL` | `qwen2.5:3b` | Model used for fast cleanup |
| `QUALITY_MODEL` | `phi4:latest` | Model used for quality cleanup |
| `OLLAMA_KEEP_ALIVE` | `20m` | How long Ollama keeps model in VRAM |
| `PARTIAL_TRANSCRIPT_ENABLED` | `true` | Show live text preview while speaking |
| `VOICE_COMMANDS_ENABLED` | `true` | Enable spoken commands |
| `WARMUP_ENABLED` | `true` | Auto-warm model on profile selection |
| `CLOUD_FALLBACK_ENABLED` | `false` | Allow fallback to cloud model on timeout |
| `MAX_RECORDING_SECONDS` | `120` | Guardrail cutoff for stuck hotkeys |

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

## 📁 Transcript Storage & Lifecycle

All transcripts are saved automatically:

* **Linux**: Saved to daily logs in `~/.local/state/voicepaste/voicepaste-YYYY-MM-DD.log`.
* **Windows**: Saved to Markdown files in `<VOICE_PASTE_ROOT>\inbox\YYYY-MM-DD.md` (Dictation/Assistant), `<VOICE_PASTE_ROOT>\journal\YYYY-MM-DD.md` (Journal), or `<VOICE_PASTE_ROOT>\meetings\YYYY-MM-DD.md` (Meeting).
* **Safe 14-Day Archival**: Files older than 14 days are automatically relocated to `~/ZZDelete/voicepaste/` rather than hard-deleted, keeping your recent dictation history accessible as a safety net.

---

## 🌾 Transcript Auditing & Checkpoints

To audit spoken mishearings and tune your vocabulary without re-checking already-reviewed text, use `voicepaste-harvest`:

```bash
# Preview fresh utterances recorded since your last review:
voicepaste-harvest --dry-run

# Review fresh utterances and advance your checkpoint bookmark:
voicepaste-harvest --advance
```

VoicePaste maintains a `.last_tuned_checkpoint` timestamp file so you always know where your last audit ended.

---

## 🛠️ Troubleshooting

### Linux

* **Typing does not appear at cursor?** Ensure `wtype` is installed and your compositor supports virtual keyboard protocols. If typing fails, VoicePaste automatically falls back to your clipboard (`wl-copy`) so you can paste with `Super + V` or `Ctrl + V`.
* **Microphone not capturing?** Check `pw-record --list-targets` or ensure PipeWire is running.
* **Notification says STT failed?** Check that your Whisper server IP and port are reachable from your Linux machine.

### Windows

* **Hotkeys not working?** Run VoicePaste as Administrator, verify Num Lock is active, or restart via `.\scripts\voice_stop.ps1` then `.\scripts\run_tray.ps1`.
* **Model shows `[cold]` immediately after warmup?** Check Ollama is running and the model name matches your pulled model.
* **Text pasted without cleanup?** The local model timed out; VoicePaste pastes raw text immediately and refines in the background.

---

## 🧪 Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## 🏛️ Architecture & Reliability Standards

VoicePaste is designed for rock-solid daily-driver input with zero tolerance for regressions. Contributors and maintenance agents should observe these operational guidelines:

* **Zero-Downtime Verification:** Test model experiments, speech-to-text daemons, or inference parameters on an isolated staging port before applying to production.
* **Regression Test Gate:** Ensure the full test suite (`pytest tests/`) passes cleanly before creating pull requests or releases.
* **Rollback Protection:** Maintain backup environment configs and rollback scripts before modifying server-side inference or vocabulary daemon settings.

---

## 📄 Licence

MIT: do whatever you like with it.
