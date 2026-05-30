# AI Archive Cleaner

[日本語](README.md)

AI Archive Cleaner is a Windows GUI tool for deleting local Codex and Claude chat histories, artifacts, and temporary logs.

The UI starts in Japanese on Japanese OS locales. Other locales use English.

## Supported Environment

- Windows 10 / 11
- Python 3.11 or newer when running from source
- Codex App / Codex CLI local files
- Claude Desktop / Claude Code / Claude CLI local files

The current release is Windows-only. macOS and Linux are not supported because app data paths, process control, and folder-opening behavior differ by OS.

## What It Can Delete

Selectable items:

- Codex chat sessions
- Claude Code / Claude CLI JSONL sessions
- Artifacts under `Documents\Codex`

When selected chat/session items are deleted, related local indexes, history rows, and metadata are also cleaned where supported.

Optional shared cleanup:

- Codex logs DB, TUI logs, and sandbox logs
- Claude Code `session-env` and `shell-snapshots`
- `AppData\Local\claude-cli-nodejs\Cache`
- Claude Desktop logs and temporary Electron caches
  - `Cache`
  - `Code Cache`
  - `Crashpad`
  - `GPUCache`
  - `Shared Dictionary`

## What It Does Not Delete

- Codex / Claude authentication data
- Primary settings files
- Codex `state_5.sqlite`
- Codex `session_index.jsonl`
- Codex `history.jsonl`
- Plugin directories
- Skill directories
- Claude Desktop `IndexedDB`
- Claude Desktop `Local Storage`
- Claude Desktop `Session Storage`
- Claude Desktop `WebStorage`
- Claude Web cloud chat history
- Claude Memory

No backup is created. Run deletion operations at your own risk.

## Usage

Download `AIArchiveCleaner.exe` from Releases and run it.

Run from source:

```powershell
python app.py
```

You can also run `run.bat`.

## Build EXE

```powershell
.\build_exe.ps1
```

Output:

```text
dist\AIArchiveCleaner.exe
```

The build script creates `.venv` and installs PyInstaller inside it. It does not install build dependencies globally.

## Development Notes

- Runtime dependencies are Python standard library only.
- PyInstaller is used only for packaging.
- `favicon.ico` is used for both the window icon and executable icon.
- The UI language is selected automatically from the OS locale.

## License

MIT License. See [LICENSE](LICENSE).
