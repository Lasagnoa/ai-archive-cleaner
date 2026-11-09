# AI Archive Cleaner

[日本語](README.md)

A Windows 10/11 GUI for deleting local Codex chats, artifacts in dedicated storage, and logs. Japanese OS locales use Japanese; other locales use English.

## Usage

Download `AIArchiveCleaner.exe` from [Releases](https://github.com/Lasagnoa/ai-archive-cleaner/releases/latest).
Select chats, optionally enable shared cleanup or full cleanup, and review the confirmation. Running Codex applications must be stopped before deletion. Full cleanup applies to Codex regardless of selection or search filters. No backup is created.

## Cleanup scope

- **Selected:** the local task, transcript, index, identifiable goals/memories/summaries/metadata and task-named artifacts. Shared prompt history, unidentifiable attachments, and global browser data require full cleanup.
- **Shared:** known Codex Desktop/CLI logs/caches. Does not erase internal browser cookies.
- **Full:** supported current/legacy history databases, drafts, attachments, generated images, visualizations, suggestions, voice continuity, process history, temporary global-state remnants, Codex project lists, and internal browser website data/cookies/logins.

Supports `.codex` and `.codex/sqlite`, versioned supported DB families, and `CODEX_HOME`. Custom `sqlite_home` / `CODEX_SQLITE_HOME` and `log_dir` locations outside these standard paths are preserved and reported as incomplete when present. Orphan catalog titles and unindexed JSONL files remain selectable.
Full cleanup also removes locally cached titles/summaries for other hosts and ChatGPT; it never calls an API to delete remote or cloud conversations. Selected cleanup is scoped to local tasks.

## Preserved

Codex **application** authentication, MCP configuration/credentials, general settings, `auth.json`, `config.toml`, `AGENTS.md`, keybindings, plugins, skills, pets, sandbox configuration, browser integration settings, and automation definitions remain.
Actual source repositories and the entire `Documents/Codex` folder are preserved because they can contain external files and tools. Claude data and external Chrome/Edge profiles remain.

Internal browser cleanup resets the dedicated `codex-browser-*` partitions/profiles and tab restoration data. Shared app-profile cookies/Local Storage that may contain Codex app authentication are protected. Internal website login and Codex application login are separate.

## Errors and limits

Readonly files are retried after changing only their readonly attribute. No ACL changes or elevation are used. Links and junctions inside dedicated cleanup targets are unlinked without traversing their destinations. Links in ancestor paths, unknown reparse points, and protected directory overlaps are rejected. Links under `Documents/Codex` are preserved.
Independent cleanup steps continue after failures. Unknown nonempty databases/tables are preserved and reported. Nonempty `cleanup_backups`, `memories_extensions`, and `worktrees` require manual review because they can contain configuration or actual working data.
The result dialog shows all errors, including partial completion. Individual deletion failures are not counted as completely successful.

This is not a disk sanitization tool. SQLite cleanup uses secure_delete, VACUUM, and WAL truncation, but deallocated sectors, restore points, previous backups, arbitrary exported copies, and cloud history are outside its scope. Whole-disk backup behavior depends on the backup software. Retaining app login allows account-side information to be downloaded again. Future unknown storage formats or mixed authentication stores are not guaranteed to be fully scrubbed.

## Development and build

Python 3.11+, standard-library runtime only.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest -v test_cleanup
.\build_exe.ps1 -InstallDependencies
```

Use `.\build_exe.ps1` when dependencies are already installed. Tests run before packaging; a failure stops the build. Output: `dist/AIArchiveCleaner.exe`. Build dependencies are installed only in the project `.venv`.
Tests use isolated dummy data and never delete real chat history.

## License

MIT License. See [LICENSE](LICENSE).
