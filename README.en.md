# AI Archive Cleaner

[日本語](README.md)

A Windows 10/11 GUI for deleting local Codex and Claude Code chats, artifacts in dedicated storage, and logs. Japanese OS locales use Japanese; other locales use English.

## Usage

Download `AIArchiveCleaner.exe` from [Releases](https://github.com/Lasagnoa/ai-archive-cleaner/releases/latest).
Click a title or its checkbox, then choose Delete. Shared logs/caches and unused project registrations are included each time. Selecting every local chat, or confirming cleanup with an empty inventory, also removes supported residual history and saved project selections. Hidden chats and chats created during confirmation are retained. No backup is created.

## Cleanup scope

- Codex transcripts, indexes, SQLite records, JSON state and known chat-owned artifacts are matched by ID. The cleaner supports legacy JSON, account-specific state and version 1 of the desktop global SQLite database.
- Explicitly mapped chat folders in `Documents/Codex` include any Git repositories and uncommitted files inside them. Registered workspaces, directories shared with retained chats, and external working directories are protected.
- Project registration cleanup checks retained chat IDs, project assignments and working directories. When a retained chat cannot be located, registrations are preserved.
- Claude Code cleanup covers local transcripts, session-specific subagents and tool outputs, prompt history, file checkpoints, attachments and known desktop Code metadata. The default directory and `CLAUDE_CONFIG_DIR` are supported. Project memory, authentication, trust and MCP configuration are preserved. [Anthropic's storage reference](https://code.claude.com/docs/en/claude-directory)
- General settings, plugins, skills, automations and browser login stores are preserved. Cloud conversations and external copies are outside the local cleanup.

## Errors and limits

Readonly files are retried after changing only their readonly attribute. No ACL changes or elevation are used. Links and junctions inside cleanup targets are unlinked without traversing their destinations. Links in ancestor paths, unknown reparse points, and protected directory overlaps are rejected.
Independent cleanup steps continue after failures. Unknown nonempty databases/tables are preserved and reported. Nonempty `cleanup_backups`, `memories_extensions`, and `worktrees` require manual review because they can contain configuration or actual working data.
The result dialog shows all errors, including partial completion. Individual deletion failures are not counted as completely successful.

This is not a disk sanitization tool. SQLite cleanup uses secure_delete, VACUUM, and WAL truncation, but deallocated sectors, restore points, previous backups, arbitrary exported copies, and cloud history are outside its scope. Whole-disk backup behavior depends on the backup software. Retaining app login allows account-side information to be downloaded again. Future unknown storage formats or mixed authentication stores are not guaranteed to be fully scrubbed.

## Development and build

Run these commands in the source directory (`Development` in the project layout). Use Python 3.13 for development and exe builds. Running from source requires Python 3.11 or later and uses only the standard library.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest -v test_cleanup
.\build_exe.ps1 -InstallDependencies
```

Use `.\build_exe.ps1` when dependencies are already installed. Tests run before packaging; a failure stops the build. Building from `Development` writes `Release/AIArchiveCleaner.exe` in the project root. A standalone checkout builds to `dist/AIArchiveCleaner.exe`. Build dependencies are installed in the `.venv` next to the source.
Tests use isolated dummy data and never delete real chat history.

## License

MIT License. See [LICENSE](LICENSE).
