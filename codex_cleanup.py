"""Schema-aware local Codex cleanup. Never delete authentication or whole app profiles.

All filesystem mutation goes through a bounded, reparse-point rejecting helper.
Database/JSON operations preserve unrelated settings, and share their target
selection with verification. Unknown database tables are reported, not erased.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote


UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
HISTORY_KEYS = {
    "heartbeat-thread-permissions-by-id", "prompt-history", "projectless-thread-ids",
    "queued-follow-ups", "thread-descriptions-v1", "thread-project-assignments",
    "thread-projectless-output-directories", "thread-workspace-root-hints",
    "unread-thread-ids-by-host-v1", "electron-thread-read-state-v1",
    "composer-prompt-drafts-v1", "composer-prompt-drafts-v2", "client-thread-bindings-v1",
    "composer-retained-documents-v1", "realtime-voice-most-recent-thread",
    "sidebar-project-thread-orders", "update-resume-state-v1",
    "chatgpt-sidebar-state-v1", "electron-browser-extension-recently-used",
}
HISTORY_PREFIXES = (
    "thread-client-id-v1:", "thread-reference-capability:",
    "codex-writing-block-deleted-thread-v1:", "thread-browser-tabs-v1:", "thread-tab-routes-v1:",
)
PROJECT_KEYS = {
    "local-projects", "project-order", "electron-saved-workspace-roots",
    "active-workspace-roots", "selected-project", "project-appearances",
    "app-server-project-id-by-legacy-project-id-by-host", "app-server-projects-migration-by-host",
}
CACHE_DIRS = (
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "Crashpad", "sentry", "Shared Dictionary", "logs",
)
HISTORY_DIRS = (
    "sessions", "archived_sessions", "attachments", "generated_images", "visualizations",
    "ambient-suggestions", "computer-use-turn-ended", "dictation-history",
    "memories", "shell_snapshots", "shell-snapshots",
)
HISTORY_FILES = ("history.jsonl", "session_index.jsonl", "transcription-history.jsonl",
                 "realtime-voice-continuity.json", "process_manager/chat_processes.json")


def lexical(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def beneath(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def reject_links(path: Path) -> None:
    """Check the entire path, including roots: junctions must not change scope."""
    for part in [path, *path.parents]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError(f"Link/reparse point is not a cleanup target: {part}")


def checked(path: Path, root: Path, *, allow_root: bool = False) -> Path:
    path, root = lexical(path), lexical(root)
    if not beneath(path, root) or (path == root and not allow_root):
        raise ValueError(f"Outside cleanup boundary: {path}")
    if root == Path(root.anchor):
        raise ValueError(f"Drive roots cannot be cleanup boundaries: {root}")
    reject_links(path)
    return path


def remove_path(path: Path, root: Path) -> None:
    path = checked(path, root)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode):
        errors = []
        for child in list(path.iterdir()):
            try:
                remove_path(child, root)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        if errors:
            raise OSError("\n".join(errors))
        path.rmdir()
    else:
        try:
            path.unlink()
        except PermissionError:
            # Only retry the specific Windows readonly case; never change ACLs.
            if not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_READONLY:
                raise
            reject_links(path)
            path.chmod(info.st_mode | stat.S_IWRITE)
            path.unlink()


def remove_contents(path: Path, root: Path) -> None:
    path = checked(path, root, allow_root=True)
    if not path.exists():
        return
    errors = []
    for child in list(path.iterdir()):
        try:
            remove_path(child, root)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        raise OSError("\n".join(errors))


def files_under(path: Path):
    reject_links(lexical(path))
    if not path.exists():
        return
    if path.is_file():
        yield path
        return
    for base, dirs, files in os.walk(path, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
        for name in dirs + files:
            reject_links(Path(base) / name)
        for name in files:
            yield Path(base) / name


def has_files(path: Path) -> bool:
    return next(files_under(path), None) is not None


def documents_folder(user: Path) -> Path:
    if os.name == "nt" and user == Path.home():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                value, _ = winreg.QueryValueEx(key, "Personal")
            return Path(os.path.expandvars(value))
        except OSError:
            pass
    return user / "Documents"


@dataclass
class Storage:
    home: Path
    user: Path
    roaming: Path
    local: Path
    documents: Path
    extra_db: Path | None = None
    extra_log: Path | None = None

    @classmethod
    def discover(cls) -> "Storage":
        user = Path.home()
        home = lexical(Path(os.environ.get("CODEX_HOME", str(user / ".codex"))))
        if home in {lexical(user), Path(home.anchor)}:
            raise ValueError("CODEX_HOME must be a dedicated application directory")
        conf = home / "config.toml"
        data = tomllib.loads(conf.read_text(encoding="utf-8-sig")) if conf.exists() else {}
        def configured(value):
            if not value:
                return None
            path = Path(os.path.expandvars(str(value))).expanduser()
            return lexical(path if path.is_absolute() else home / path)
        return cls(home, user, Path(os.environ.get("APPDATA", str(user / "AppData/Roaming"))),
                   Path(os.environ.get("LOCALAPPDATA", str(user / "AppData/Local"))),
                   documents_folder(user) / "Codex",
                   configured(os.environ.get("CODEX_SQLITE_HOME") or data.get("sqlite_home")),
                   configured(data.get("log_dir")))

    def db_roots(self) -> list[Path]:
        return list(dict.fromkeys(lexical(p) for p in [self.extra_db, self.home, self.home / "sqlite"] if p))

    def desktops(self) -> list[Path]:
        roots = [self.roaming / "Codex"]
        packages = self.local / "Packages"
        if packages.exists():
            roots += [p / "LocalCache/Roaming/Codex" for p in packages.glob("OpenAI.Codex_*")]
        return unique_paths(roots)

    def logs(self) -> list[Path]:
        roots = [self.home / "log", self.local / "Codex/Logs"]
        if self.extra_log:
            roots.append(self.extra_log)
        packages = self.local / "Packages"
        if packages.exists():
            roots += [p / "LocalCache/Local/Codex/Logs" for p in packages.glob("OpenAI.Codex_*")]
        return unique_paths(roots)


def unique_paths(paths: list[Path]) -> list[Path]:
    result = []
    for p in paths:
        p = lexical(p)
        if any(p == q or (p.exists() and q.exists() and os.path.samefile(p, q)) for q in result):
            continue
        result.append(p)
    return result


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)

    def step(self, label, action):
        try:
            return action()
        except (OSError, ValueError, sqlite3.Error, TypeError) as exc:
            self.errors.append(f"{label}: {exc}")
            return None


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# Each family names only history-bearing tables. Everything else is preserved.
RULES = {
    "state": {
        "threads": ("id",), "thread_dynamic_tools": ("thread_id",),
        "thread_goals": ("thread_id",), "stage1_outputs": ("thread_id",),
        "thread_spawn_edges": ("parent_thread_id", "child_thread_id"),
        "agent_job_items": ("assigned_thread_id",), "agent_jobs": (),
        "thread_artifacts": ("thread_id",), "projects": (), "project_roots": (),
        "project_idempotency_keys": (), "rollout_migration_skipped_rollouts": (),
    },
    "thread_history": {"thread_turns": ("thread_id",), "thread_items": ("thread_id",),
                       "thread_history_projection_state": ("thread_id",), "thread_realtime_items": ("thread_id",)},
    "logs": {"logs": ("thread_id",)},
    "goals": {"thread_goals": ("thread_id",), "thread_goal_continuation_deferrals": ("thread_id",)},
    "memories": {"jobs": ("job_key",), "stage1_outputs": ("thread_id",)},
    "queue": {"queued_items": ("thread_id",), "queued_thread_revisions": ("thread_id",)},
    "catalog": {
        "local_thread_catalog": ("thread_id",), "thread_timeline_ledger": ("thread_id",),
        "local_thread_catalog_scan_entries": ("thread_id",),
        "local_thread_catalog_sync_state": (), "local_thread_catalog_scan_checkpoints": (),
        "inbox_items": ("thread_id",), "automation_runs": ("thread_id",),
    },
    "summaries": {"thread_turn_summaries": ("thread_id",)},
}
SAFE_TABLES = {
    "_sqlx_migrations", "sqlite_sequence", "backfill_state", "rollout_migration_state",
    "remote_control_enrollments", "external_agent_config_imports", "thread_sections",
    "codex_schema_migrations", "automations", "local_app_server_feature_enablement",
    "local_thread_catalog_metadata", "local_thread_catalog_hosts",
}


def family(path: Path) -> str | None:
    m = re.fullmatch(r"(state|thread_history|logs|goals|memories|queue)_\d+\.sqlite", path.name)
    if m:
        return m[1]
    if re.fullmatch(r"codex-thread-summaries(?:-[\w-]+)?\.db", path.name):
        return "summaries"
    if re.fullmatch(r"codex(?:-[\w-]+)?\.db", path.name):
        return "catalog"
    return None


def databases(storage: Storage):
    found = []
    for root in storage.db_roots():
        reject_links(root)
        if root.exists():
            found += [p for p in root.iterdir() if p.suffix in {".sqlite", ".db"}]
    return unique_paths(found)


def connect(path: Path, readonly: bool = True):
    reject_links(lexical(path))
    for suffix in ("-wal", "-shm", "-journal"):
        reject_links(lexical(Path(str(path) + suffix)))
    con = sqlite3.connect(path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True, timeout=2)
    if readonly:
        con.execute("pragma query_only=ON")
    return con


def schema(con):
    return {name: {r[1] for r in con.execute(f"pragma table_info({quote(name)})")}
            for (name,) in con.execute("select name from sqlite_master where type='table'").fetchall()}


def predicates(kind, table, columns, ids):
    parts, params = [], []
    id_columns = RULES[kind][table]
    if ids is not None:
        if not id_columns:
            return None
        actual = [c for c in id_columns if c in columns]
        if not actual:
            raise ValueError(f"Unsupported columns: {table}")
        parts.append("(" + " OR ".join(f"{quote(c)} IN ({','.join('?' for _ in ids)})" for c in actual) + ")")
        params += list(ids) * len(actual)
    if ids is not None and kind == "catalog" and (table.startswith("local_thread_catalog") or table == "thread_timeline_ledger"):
        if "host_id" not in columns:
            raise ValueError(f"Missing host scope: {table}")
        parts.append("host_id = 'local'")
    if ids is not None and kind == "summaries":
        if "host_key" not in columns:
            raise ValueError(f"Missing host scope: {table}")
        parts.append("(host_key = 'local' OR host_key LIKE 'local:%')")
    return " AND ".join(parts) or "1", params


def database_rows(path: Path, ids=None, *, clean=False, logs_only=False):
    kind = family(path)
    if logs_only and kind != "logs":
        return []
    if kind is None:
        if path.stat().st_size:
            return [f"Unsupported database (preserved): {path.name}"]
        return []
    con = connect(path, readonly=not clean)
    pending = []
    try:
        tables = schema(con)
        if clean:
            con.execute("pragma secure_delete=ON")
            con.execute("begin immediate")
        for table, columns in tables.items():
            if table in SAFE_TABLES:
                continue
            if table not in RULES[kind]:
                if con.execute(f"select 1 from {quote(table)} limit 1").fetchone():
                    pending.append(f"Unsupported table (preserved): {path.name}/{table}")
                continue
            pred = predicates(kind, table, columns, ids)
            if pred is None:
                continue
            where, params = pred
            if clean:
                con.execute(f"delete from {quote(table)} where {where}", params)
            elif con.execute(f"select 1 from {quote(table)} where {where} limit 1", params).fetchone():
                pending.append(f"Remaining: {path.name}/{table}")
        if clean:
            if kind == "catalog" and "local_thread_catalog_metadata" in tables and "catalog_revision" in tables["local_thread_catalog_metadata"]:
                con.execute("update local_thread_catalog_metadata set catalog_revision=catalog_revision+1")
            con.commit()
            con.execute("vacuum")
            row = con.execute("pragma wal_checkpoint(TRUNCATE)").fetchone()
            if row and row[0]:
                raise sqlite3.OperationalError(f"WAL checkpoint busy: {path}")
    except Exception:
        if clean:
            con.rollback()
        raise
    finally:
        con.close()
    return pending


def contains_id(value, ids):
    if not isinstance(value, str):
        return False
    value = unquote(value)
    return value in ids or bool(set(UUID.findall(value)) & ids)


def filter_ids(value, ids):
    if isinstance(value, dict):
        return {k: filter_ids(v, ids) for k, v in value.items()
                if not contains_id(k, ids) and not contains_id(v, ids)}
    if isinstance(value, list):
        return [filter_ids(v, ids) for v in value
                if not contains_id(v, ids) and not (isinstance(v, dict) and
                    any(contains_id(v.get(k), ids) for k in ("threadId", "thread_id", "conversationId", "id")))]
    return value


def cleaned_global(data, ids=None):
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    data = dict(data)
    for key in list(data):
        if key == "electron-persisted-atom-state":
            data[key] = cleaned_global(data[key], ids)
        elif key in HISTORY_KEYS or key.startswith(HISTORY_PREFIXES):
            if ids is None or contains_id(key, ids):
                data.pop(key)
            else:
                data[key] = filter_ids(data[key], ids)
        elif ids is None and (key in PROJECT_KEYS or key.startswith("sidebar-project-expanded-v1-")):
            data.pop(key)
    return data


def rewrite_json(path, root, transform):
    path = checked(path, root)
    before = json.loads(path.read_text(encoding="utf-8-sig"))
    after = transform(before)
    if before == after:
        return
    temp = checked(path.with_name(path.name + ".cleaner.tmp"), root)
    # Do not overwrite an existing temporary file from a different operation.
    with temp.open("x", encoding="utf-8") as f:
        json.dump(after, f, ensure_ascii=False, separators=(",", ":"))
    try:
        reject_links(path)
        temp.replace(path)
    finally:
        if temp.exists():
            remove_path(temp, root)


def global_files(storage):
    return [storage.home / n for n in (".codex-global-state.json", ".codex-global-state.json.bak")
            if (storage.home / n).exists()]


def full_targets(storage):
    targets = [(storage.home / n, storage.home) for n in HISTORY_DIRS + HISTORY_FILES]
    targets += [(storage.documents, storage.documents.parent)]
    if storage.home.exists():
        targets += [(p, storage.home) for pattern in ("..codex-global-state.json*tmp-*", ".codex-global-state.json*.tmp", ".codex-global-state.json*.cleaner.tmp")
                    for p in storage.home.glob(pattern)]
    targets += common_file_targets(storage)
    for desktop in storage.desktops():
        # The app's Default profile / Cookies / Local Storage may own app auth.
        # Only Codex browser partitions are reset, not the app's whole userData.
        for parent in [desktop / "Partitions", desktop / "web/Codex"]:
            reject_links(parent)
            if parent.exists():
                targets += [(p, desktop) for p in parent.iterdir()
                            if p.name.startswith("codex-browser-")]
        for name in ("browser-sidebar-page-states.json", "web/Codex/browser-sidebar-page-states.json"):
            targets.append((desktop / name, desktop))
        # Cache/history in the host profile can be discarded without deleting its cookies/settings.
        web = desktop / "web/Codex"
        for name in CACHE_DIRS + ("History", "History-journal", "Top Sites", "Top Sites-journal", "Sessions", "Session Storage"):
            targets.append((web / "Default" / name, desktop))
        for name in CACHE_DIRS:
            targets.append((web / name, desktop))
    return targets


def common_file_targets(storage):
    targets = []
    for p in storage.logs():
        # A configured log_dir could also contain unrelated user files.
        if storage.extra_log and lexical(p) == lexical(storage.extra_log):
            targets += [(f, p) for f in files_under(p) if f.suffix == ".log"]
        else:
            targets.append((p, p.parent))
    targets += [(storage.home / name, storage.home) for name in ("sandbox.log", ".sandbox/sandbox.log")]
    for desktop in storage.desktops():
        targets += [(desktop / name, desktop) for name in CACHE_DIRS]
    return targets


def protected(storage):
    # Both ancestor and descendant overlap is rejected for recursive operations.
    paths = [storage.home / n for n in ("auth.json", "config.toml", "AGENTS.md", "keybindings.json",
              "plugins", "skills", "pets", "browser", ".sandbox-secrets", ".sandbox-bin", "automations")]
    for desktop in storage.desktops():
        paths += [desktop / n for n in ("Local State", "Preferences", "Network", "Local Storage")]
        paths += [desktop / "web/Codex/Default" / n for n in ("Network", "Local Storage", "Preferences", "Login Data")]
        paths.append(desktop / "web/Codex/Local State")
    return [lexical(p) for p in paths]


def delete_target(path, root, storage):
    target = checked(path, root)
    if any(beneath(target, p) or beneath(p, target) for p in protected(storage)):
        raise ValueError(f"Protected settings overlap: {target}")
    remove_path(target, root)


def inspect_remaining(storage, ids=None, *, logs_only=False):
    result = Result()
    paths = result.step("Database discovery", lambda: databases(storage)) or []
    for path in paths:
        pending = result.step(str(path), lambda p=path: database_rows(p, ids, logs_only=logs_only))
        result.errors.extend(pending or [])
    if ids is None:
        for path, _ in (common_file_targets(storage) if logs_only else full_targets(storage)):
            remaining = result.step(str(path), lambda p=path: has_files(p))
            if remaining:
                result.errors.append(f"Remaining files: {path}")
    if not logs_only:
        for path in global_files(storage):
            def inspect(p=path):
                reject_links(p)
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                return data != cleaned_global(data, ids)
            if result.step(str(path), inspect):
                result.errors.append(f"Remaining metadata: {path}")
        # These may contain user-managed configuration: detect, never guess-delete.
        if ids is None:
            for name in ("cleanup_backups", "memories_extensions", "worktrees"):
                p = storage.home / name
                if result.step(str(p), lambda p=p: has_files(p)):
                    result.errors.append(f"Manual review required (preserved): {p}")
    return result.errors


def cleanup_all(storage, *, logs_only=False):
    result = Result()
    paths = result.step("Database discovery", lambda: databases(storage)) or []
    for path in paths:
        pending = result.step(str(path), lambda p=path: database_rows(p, clean=True, logs_only=logs_only))
        result.errors.extend(pending or [])
    targets = result.step("File discovery", lambda: common_file_targets(storage) if logs_only else full_targets(storage)) or []
    for path, root in targets:
        result.step(str(path), lambda p=path, r=root: delete_target(p, r, storage))
    if not logs_only:
        for path in global_files(storage):
            result.step(str(path), lambda p=path: rewrite_json(p, storage.home, cleaned_global))
    remaining = result.step("Verification", lambda: inspect_remaining(storage, logs_only=logs_only))
    result.errors.extend(remaining or [])
    return list(dict.fromkeys(result.errors))


def list_threads(storage):
    records = {}
    for path in databases(storage):
        if family(path) != "state":
            continue
        con = connect(path)
        try:
            tables = schema(con)
            if "threads" not in tables:
                continue
            cols = tables["threads"]
            for row in con.execute("select " + ",".join(quote(c) if c in cols else "NULL"
                                   for c in ("id", "title", "rollout_path", "archived", "updated_at", "cwd", "name")) + " from threads"):
                tid, title, rollout, archived, updated, cwd, name = row
                key = (tid, rollout)
                if key not in records or (updated or 0) > records[key][4]:
                    records[key] = (tid, name or title or tid, rollout or "", archived or 0, updated or 0, cwd or "")
        finally:
            con.close()
    # A deleted transcript may leave only a Desktop catalog or history projection.
    # Keep these selectable so a retry does not require wiping every other task.
    known_ids = {r[0] for r in records.values()}
    for path in databases(storage):
        kind = family(path)
        if kind not in {"catalog", "thread_history", "summaries"}:
            continue
        con = connect(path)
        try:
            tables = schema(con)
            if kind == "catalog" and "local_thread_catalog" in tables:
                cols = tables["local_thread_catalog"]
                if not {"thread_id", "host_id"} <= cols:
                    raise ValueError(f"Unsupported catalog schema: {path}")
                fields = ("thread_id", "display_title", "source_updated_at", "cwd")
                rows = con.execute("select " + ",".join(quote(c) if c in cols else "NULL" for c in fields)
                                   + " from local_thread_catalog where host_id='local'").fetchall()
            else:
                table = "thread_items" if kind == "thread_history" else "thread_turn_summaries"
                if table not in tables or "thread_id" not in tables[table]:
                    continue
                where = ""
                if kind == "summaries":
                    if "host_key" not in tables[table]:
                        continue
                    where = " where host_key='local' OR host_key LIKE 'local:%'"
                rows = [(t, None, 0, "") for (t,) in con.execute(f"select distinct thread_id from {quote(table)}{where}")]
            for tid, title, updated, cwd in rows:
                if kind == "catalog" and (tid, "") in records:
                    records[(tid, "")] = (tid, title or records[(tid, "")][1], "", 0, updated or 0, cwd or "")
                if tid and tid not in known_ids:
                    records[(tid, "")] = (tid, title or f"History: {tid}", "", 0, updated or 0, cwd or "")
                    known_ids.add(tid)
        finally:
            con.close()
    indexed_paths = {lexical(Path(r[2])) for r in records.values() if r[2]}
    for root in (storage.home / "sessions", storage.home / "archived_sessions"):
        for p in files_under(root):
            if p.suffix == ".jsonl" and lexical(p) not in indexed_paths:
                match = UUID.search(p.name)
                tid = match[0] if match else str(p.relative_to(root))
                orphan = records.pop((tid, ""), None)
                records[(tid, str(p))] = (tid, orphan[1] if orphan else p.stem, str(p),
                                        root.name == "archived_sessions", p.stat().st_mtime, orphan[5] if orphan else "")
    return list(records.values())


def delete_selected(storage, ids: set[str], rollout_paths: list[str]):
    if not ids:
        return []
    result = Result()
    # Resolve allowed transcript paths before making any database changes.
    paths = []
    for value in rollout_paths:
        if not value:
            continue  # DB-only orphan row can still be removed.
        p = lexical(Path(value))
        root = next((r for r in [storage.home / "sessions", storage.home / "archived_sessions"]
                     if beneath(p, lexical(r)) and p != lexical(r)), None)
        if root is None:
            result.errors.append(f"Outside transcript boundary: {p}")
        else:
            result.step(str(p), lambda p=p, root=root: checked(p, root))
            paths.append((p, root))
    if result.errors:
        return result.errors
    for path in databases(storage):
        pending = result.step(str(path), lambda p=path: database_rows(p, ids, clean=True))
        result.errors.extend(pending or [])
    # Keep transcript files available for retry if database cleanup failed.
    if result.errors:
        return result.errors
    for name, field in [("history.jsonl", "session_id"), ("session_index.jsonl", "id")]:
        path = storage.home / name
        if path.exists():
            result.step(str(path), lambda p=path, f=field: filter_jsonl(p, storage.home, f, ids))
    for path in global_files(storage):
        result.step(str(path), lambda p=path: rewrite_json(p, storage.home, lambda d: cleaned_global(d, ids)))
    # Only explicit task-named directories/files: never infer ownership from cwd.
    for name in ("attachments", "generated_images", "visualizations", "computer-use-turn-ended"):
        root = storage.home / name
        if root.exists():
            def prune_owned(root=root):
                reject_links(root)
                for base, dirs, files in os.walk(root, followlinks=False):
                    for child in dirs + files:
                        p = Path(base) / child
                        reject_links(p)
                        if contains_id(p.name, ids):
                            result.step(str(p), lambda p=p: delete_target(p, storage.home, storage))
                            if child in dirs:
                                dirs.remove(child)
            result.step(str(root), prune_owned)
    if not result.errors:
        for path, root in paths:
            result.step(str(path), lambda p=path, r=root: remove_path(p, r))
    for path, _ in paths:
        if path.exists():
            result.errors.append(f"Remaining transcript: {path}")
    pending = result.step("Verification", lambda: inspect_remaining(storage, ids))
    result.errors.extend(pending or [])
    return list(dict.fromkeys(result.errors))


def filter_jsonl(path, root, field, ids):
    path = checked(path, root)
    lines = []
    for line in path.read_text(encoding="utf-8-sig").splitlines(keepends=True):
        if not line.strip():
            lines.append(line)
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"Invalid JSONL object: {path}")
        if item.get(field) not in ids:
            lines.append(line)
    temp = checked(path.with_name(path.name + ".cleaner.tmp"), root)
    with temp.open("x", encoding="utf-8") as f:
        f.write("".join(lines))
    try:
        reject_links(path)
        temp.replace(path)
    finally:
        if temp.exists():
            remove_path(temp, root)
