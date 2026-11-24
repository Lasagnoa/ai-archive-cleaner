"""Schema-aware local Codex cleanup. Never delete authentication or whole app profiles.

All filesystem mutation goes through a bounded helper that never follows links.
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
from contextlib import contextmanager
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
    "chatgpt-sidebar-state-v1", "chatgpt-sidebar-state-v2", "electron-browser-extension-recently-used",
    "thread-project-membership-host-ids", "pinned-thread-ids", "draft-thread-identities-v1",
    "thread-user-activity-times-v1", "recent-workspace-files-v3", "electron-remote-hosted-pip-task-visibility-state",
}
HISTORY_PREFIXES = (
    "thread-client-id-v1:", "thread-reference-capability:", "search-mcp-context:",
    "codex-writing-block-deleted-thread-v1:", "thread-browser-tabs-v1:", "thread-tab-routes-v1:",
)
PROJECT_KEYS = {
    "local-projects", "project-order", "electron-saved-workspace-roots",
    "active-workspace-roots", "selected-project", "project-appearances",
    "app-server-project-id-by-legacy-project-id-by-host", "app-server-projects-migration-by-host",
    "app-server-pending-project-deletions-by-host", "electron-workspace-root-labels",
    "pinned-project-ids", "new-task-project-by-computer", "new-task-target-history",
}
SIDEBAR_ORDERS = {"unified-sidebar-project-order-v1", "unified-sidebar-pinned-order-v1"}
SIDEBAR_GROUPS = {"sidebar-custom-sections-v3", "sidebar-customization-snapshots-v2"}
PROJECT_EXECUTION_KEYS = {"new-task-execution-by-account-project", "new-task-remote-host-by-account-project"}
GLOBAL_KEYS = HISTORY_KEYS | PROJECT_KEYS | PROJECT_EXECUTION_KEYS | SIDEBAR_ORDERS | SIDEBAR_GROUPS
GLOBAL_PREFIXES = HISTORY_PREFIXES + ("sidebar-project-expanded-v1-",)
GLOBAL_DB = ".codex-global-state.sqlite"
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
OWNED_DIRS = ("attachments", "generated_images", "visualizations", "computer-use-turn-ended",
              "shell_snapshots", "shell-snapshots")


def lexical(path: Path) -> Path:
    value = str(path.expanduser())
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif (value.startswith("\\\\?\\") and len(value) >= 7
              and value[4].isalpha() and value[5:7] == ":\\"):
            value = value[4:]
    return Path(os.path.abspath(value))


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


def checked(path: Path, root: Path, *, allow_root: bool = False, allow_leaf_link: bool = False) -> Path:
    path, root = lexical(path), lexical(root)
    if not beneath(path, root) or (path == root and not allow_root):
        raise ValueError(f"Outside cleanup boundary: {path}")
    if root == Path(root.anchor):
        raise ValueError(f"Drive roots cannot be cleanup boundaries: {root}")
    reject_links(path.parent if allow_leaf_link else path)
    return path


def remove_path(path: Path, root: Path) -> None:
    path = checked(path, root, allow_leaf_link=True)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
        # Unlink only known symbolic links and junctions; never traverse their targets.
        tag = getattr(info, "st_reparse_tag", None)
        if os.name == "nt" and tag not in (0xA000000C, 0xA0000003):
            raise ValueError(f"Unsupported reparse point (preserved): {path}")
        if os.name == "nt" and getattr(info, "st_file_attributes", 0) & 16:
            path.rmdir()
        else:
            path.unlink()
    elif stat.S_ISDIR(info.st_mode):
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
        return list(dict.fromkeys(lexical(p) for p in [self.home, self.home / "sqlite"]))

    def desktops(self) -> list[Path]:
        roots = [self.roaming / "Codex"]
        packages = self.local / "Packages"
        if packages.exists():
            roots += [p / "LocalCache/Roaming/Codex" for p in packages.glob("OpenAI.Codex_*")]
        return unique_paths(roots)

    def logs(self) -> list[Path]:
        roots = [self.home / "log", self.local / "Codex/Logs"]
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
        "thread_artifacts": ("thread_id",), "thread_attachments": ("thread_id",),
        "thread_read_receipts": ("thread_id",), "projects": (), "project_roots": (),
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
        "local_thread_catalog_history_coverage": (),
        "inbox_items": ("thread_id",), "automation_runs": ("thread_id",),
        "active_chat_turns": ("thread_id",),
    },
    "summaries": {"thread_turn_summaries": ("thread_id",)},
}
SAFE_TABLES = {
    "_sqlx_migrations", "sqlite_sequence", "backfill_state", "rollout_migration_state",
    "remote_control_enrollments", "external_agent_config_imports", "thread_sections",
    "codex_schema_migrations", "automations", "local_app_server_feature_enablement",
    "local_thread_catalog_metadata", "local_thread_catalog_hosts",
}

# Column name, declared type, NOT NULL, default and position in the primary key.
HISTORY_TABLE_COLUMNS = {
    ("catalog", "active_chat_turns"): {
        ("profile", "TEXT", 1, None, 1), ("account_id", "TEXT", 1, None, 2),
        ("user_id", "TEXT", 1, None, 3), ("thread_id", "TEXT", 1, None, 4),
        ("launch_id", "TEXT", 1, None, 0), ("observed_at_ms", "INTEGER", 1, None, 0),
    },
    ("state", "thread_attachments"): {
        ("id", "TEXT", 0, None, 1), ("thread_id", "TEXT", 1, None, 0),
        ("attachment_type", "TEXT", 1, None, 0), ("identity_key", "TEXT", 1, None, 0),
        ("payload", "TEXT", 1, None, 0), ("created_at", "INTEGER", 1, None, 0),
    },
    ("catalog", "local_thread_catalog_history_coverage"): {
        ("host_id", "TEXT", 1, None, 1), ("scope", "TEXT", 1, None, 2),
        ("cursor", "TEXT", 0, None, 0), ("complete", "INTEGER", 1, "0", 0),
    },
}


def family(path: Path) -> str | None:
    if path.name == GLOBAL_DB:
        return "global"
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


def supported_table_schema(con, kind, table, columns):
    if kind == "state" and table == "thread_read_receipts":
        return columns == {"thread_id", "first_unread_turn", "revision", "last_published_turn"}
    expected = HISTORY_TABLE_COLUMNS.get((kind, table))
    if expected is None:
        return True
    actual = set()
    for _, name, sql_type, required, default, pk, hidden in con.execute(f"pragma table_xinfo({quote(table)})"):
        if hidden:
            return False
        actual.add((name, sql_type, required, default, pk))
    if actual != expected:
        return False
    foreign_keys = con.execute('select "table", "from", "to", on_update, on_delete '
                               'from pragma_foreign_key_list(?)', (table,)).fetchall()
    if table == "thread_attachments":
        return foreign_keys == [("threads", "thread_id", "id", "NO ACTION", "CASCADE")]
    return not foreign_keys


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


def database_rows(path: Path, ids=None, *, clean=False, logs_only=False, projects=None):
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
        if clean:
            con.execute("pragma secure_delete=ON")
            con.execute("begin immediate")
        else:
            con.execute("begin")
        tables = {}
        if kind == "global":
            pending = global_setting_rows(con, path, ids, clean, projects.clean if projects is not None else None)
        else:
            tables = schema(con)
        for table, columns in tables.items():
            if projects is not None:
                column = {"projects": "id", "project_roots": "project_id",
                          "project_idempotency_keys": "project_id"}.get(table)
                if column and column in columns:
                    for pid in projects.ids:
                        where = f"from {quote(table)} where {quote(column)}=?"
                        if clean:
                            con.execute("delete " + where, (pid,))
                        elif con.execute("select 1 " + where + " limit 1", (pid,)).fetchone():
                            pending.append(f"Remaining project: {path.name}/{table}")
                continue
            if table in SAFE_TABLES:
                continue
            if not supported_table_schema(con, kind, table, columns):
                if con.execute(f"select 1 from {quote(table)} limit 1").fetchone():
                    pending.append(f"Unsupported table schema (preserved): {path.name}/{table}")
                continue
            if (kind == "memories" and table == "consolidation_progress"
                    and columns == {"singleton", "max_thread_count"}):
                # Keep Codex's singleton row; full cleanup resets its history-derived count.
                if ids is None:
                    if clean:
                        con.execute("update consolidation_progress set max_thread_count=0")
                    elif con.execute("select 1 from consolidation_progress "
                                     "where max_thread_count != 0 limit 1").fetchone():
                        pending.append(f"Remaining: {path.name}/{table}")
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
    return (value in ids or bool(set(UUID.findall(value)) & ids)
            or any(alias in ids for alias in re.findall("client-new-thread:" + UUID.pattern, value)))


def filter_ids(value, ids):
    if isinstance(value, dict):
        return {k: filter_ids(v, ids) for k, v in value.items()
                if not contains_id(k, ids) and not contains_id(v, ids)}
    if isinstance(value, list):
        return [filter_ids(v, ids) for v in value
                if not contains_id(v, ids) and not (isinstance(v, dict) and
                    any(contains_id(v.get(k), ids) for k in ("threadId", "thread_id", "conversationId", "id")))]
    return value


def setting_name(key):
    if key.startswith("electron-owner-value:"):
        name, _, owner = key.removeprefix("electron-owner-value:").partition(":")
        if owner:
            return name
    return key


def owner_atoms(key):
    return key.startswith("electron-owner-atoms:") and key != "electron-owner-atoms:"


def atom_container(key):
    return key == "electron-persisted-atom-state" or owner_atoms(key)


def cleaned_sidebar(name, value, ids, project_ids=None):
    prefixes = (("codex:project:", "executor-folder:", "chatgpt:project:", "codex:thread:",
                 "chatgpt:conversation:") if ids is None else ("codex:thread:",))

    def keep(item):
        if project_ids is not None:
            return not (isinstance(item, str) and item.startswith("codex:project:")
                        and item.removeprefix("codex:project:") in project_ids)
        return not (isinstance(item, str) and item.startswith(prefixes)
                    and (ids is None or item.startswith("codex:thread:local:"))
                    and (ids is None or contains_id(item, ids)))

    def items(values):
        if not isinstance(values, list):
            raise ValueError(f"Unsupported sidebar order: {name}")
        return [v for v in values if keep(v)]

    def fields(obj, order, flags):
        result = dict(obj)
        if order in obj:
            result[order] = items(obj[order])
        if isinstance(obj.get(flags), dict):
            result[flags] = {k: v for k, v in obj[flags].items() if keep(k)}
        return result

    if name in SIDEBAR_ORDERS:
        return items(value)
    if not isinstance(value, dict) or not all(isinstance(v, dict) for v in value.values()):
        raise ValueError(f"Unsupported sidebar groups: {name}")
    if name == "sidebar-customization-snapshots-v2":
        return {k: fields(v, "order", "pinOverrides") for k, v in value.items()}
    result = dict(value)
    for account, group in value.items():
        if "sections" in group:
            sections = group["sections"]
            if not isinstance(sections, list) or not all(isinstance(s, dict) for s in sections):
                raise ValueError(f"Unsupported sidebar sections: {name}")
            result[account] = {**group, "sections": [fields(s, "itemKeys", "pendingDeletionHostIdsByItemKey")
                                                      for s in sections]}
    return result


def cleaned_global(data, ids=None):
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    data = dict(data)
    for key in list(data):
        name = setting_name(key)
        if atom_container(key):
            data[key] = cleaned_global(data[key], ids)
        elif ids is not None and name == "recent-workspace-files-v3" and isinstance(data[key], dict):
            data[key] = {k: v for k, v in data[key].items() if not (isinstance(v, dict)
                         and v.get("hostId") == "local" and contains_id(v.get("threadId"), ids))}
        elif ids is not None and name == "app-server-projects-migration-by-host" and isinstance(data[key], dict):
            data[key] = {k: {**v, "pendingThreadAssignmentIds": filter_ids(v["pendingThreadAssignmentIds"], ids)}
                         if k.startswith("local:") and isinstance(v, dict) and "pendingThreadAssignmentIds" in v else v
                         for k, v in data[key].items()}
        elif ids is not None and name in ("prompt-history", "thread-user-activity-times-v1") and isinstance(data[key], dict):
            data[key] = {k: v for k, v in data[key].items() if not contains_id(k, ids)
                         or (name == "thread-user-activity-times-v1" and not k.startswith('["local",'))}
        elif ids is not None and name.startswith("search-mcp-context:"):
            parts = json.loads(name.removeprefix("search-mcp-context:"))
            if isinstance(parts, list) and len(parts) == 2 and parts[0] == "local" and parts[1] in ids:
                data.pop(key)
        elif name in HISTORY_KEYS or name.startswith(HISTORY_PREFIXES):
            if ids is None or contains_id(name, ids) or contains_id(data[key], ids):
                data.pop(key)
            else:
                data[key] = filter_ids(data[key], ids)
        elif ids is None and (name in PROJECT_KEYS or name.startswith("sidebar-project-expanded-v1-")):
            data.pop(key)
        elif ids is None and name in PROJECT_EXECUTION_KEYS:
            # The [account, user, null] entry is the preference for projectless chats.
            if not isinstance(data[key], dict):
                raise ValueError(f"Unsupported project preference: {name}")
            retained = dict(data[key])
            for entry in data[key]:
                try:
                    parts = json.loads(entry)
                except ValueError:
                    continue
                if isinstance(parts, list) and len(parts) == 3 and isinstance(parts[2], str):
                    del retained[entry]
            data[key] = retained
        elif name in SIDEBAR_ORDERS or name in SIDEBAR_GROUPS:
            data[key] = cleaned_sidebar(name, data[key], ids)
    return data


def global_settings(con, path):
    # Desktop schema v1 flattens atom containers into (scope, key) rows.
    version = con.execute("pragma user_version").fetchone()[0]
    columns = [tuple(row[1:]) for row in con.execute("pragma table_xinfo(settings)")]
    expected = [(name, "TEXT", 1, None, pk, 0) for name, pk in (("scope", 1), ("key", 2), ("value", 0))]
    objects = con.execute("select type,name from sqlite_schema where name not glob 'sqlite_*'").fetchall()
    if (version != 1 or columns != expected or objects != [("table", "settings")]
            or con.execute("pragma foreign_key_list(settings)").fetchone()):
        raise ValueError(f"Unsupported global state schema (preserved): {path.name} (version {version})")
    for scope, key, raw in con.execute("select scope,key,value from settings"):
        if not isinstance(scope, str) or not isinstance(key, str) or not isinstance(raw, str):
            raise ValueError(f"Unsupported global state row (preserved): {path.name}")
        if scope in ("global", "atom") or owner_atoms(scope):
            yield scope, key, raw


def global_setting_rows(con, path, ids, clean, transform=None):
    changes = []
    for scope, key, raw in global_settings(con, path):
        name = setting_name(key)
        if not (atom_container(key) or name in GLOBAL_KEYS or name.startswith(GLOBAL_PREFIXES)):
            continue
        before = {key: json.loads(raw)}
        after = transform(before) if transform is not None else cleaned_global(before, ids)
        if before == after:
            continue
        if not clean:
            return [f"Remaining metadata: {path.name}/settings"]
        changes.append((scope, key, after))
    for scope, key, after in changes:
        if key in after:
            value = json.dumps(after[key], ensure_ascii=False, separators=(",", ":"))
            con.execute("update settings set value=? where scope=? and key=?", (value, scope, key))
        else:
            con.execute("delete from settings where scope=? and key=?", (scope, key))
    return []


@contextmanager
def replacement_file(path, root):
    temp = checked(path.with_name(path.name + ".cleaner.tmp"), root)
    stream = temp.open("x", encoding="utf-8", newline="")
    try:
        with stream:
            yield stream
        reject_links(path)
        temp.replace(path)
    finally:
        if temp.exists():
            remove_path(temp, root)


def rewrite_json(path, root, transform):
    path = checked(path, root)
    before = json.loads(path.read_text(encoding="utf-8-sig"))
    after = transform(before)
    if before != after:
        with replacement_file(path, root) as stream:
            json.dump(after, stream, ensure_ascii=False, separators=(",", ":"))


def global_files(storage):
    return [storage.home / n for n in (".codex-global-state.json", ".codex-global-state.json.bak")
            if (storage.home / n).exists()]


def stored_settings(storage):
    def entries(data):
        if not isinstance(data, dict):
            raise ValueError("Global state must be an object")
        for key, value in data.items():
            if atom_container(key):
                yield from entries(value)
            else:
                yield setting_name(key), value
    for path in global_files(storage):
        reject_links(path)
        yield from entries(json.loads(path.read_text(encoding="utf-8-sig")))
    for db in databases(storage):
        if family(db) == "global":
            con = connect(db)
            try:
                for _, key, raw in global_settings(con, db):
                    if atom_container(key) or setting_name(key) in GLOBAL_KEYS or setting_name(key).startswith(GLOBAL_PREFIXES):
                        yield from entries({key: json.loads(raw)})
            finally:
                con.close()


def metadata_ids(storage, ids):
    bindings = {}
    for key, value in stored_settings(storage):
        if key == "client-thread-bindings-v1" and isinstance(value, dict):
            pairs = value.items()
        elif unquote(key).startswith("thread-client-id-v1:local:"):
            pairs = [(value, unquote(key).removeprefix("thread-client-id-v1:local:"))]
        else:
            continue
        for client, server in pairs:
            if isinstance(client, str) and client.startswith("client-new-thread:") and isinstance(server, str):
                bindings.setdefault(client, set()).add(server)
    return ids | {client for client, servers in bindings.items() if servers <= ids}


def projectless_outputs(storage, ids, keep_paths=()):
    """Find explicitly mapped projectless outputs, rejecting ambiguous ownership."""
    mappings = {}
    project_paths = list(keep_paths)
    hints = []
    root = lexical(storage.documents)
    def collect_paths(value):
        if isinstance(value, str) and Path(value).is_absolute():
            project_paths.append(lexical(Path(value)))
        elif isinstance(value, dict):
            for key, item in value.items():
                collect_paths(key)
                collect_paths(item)
        elif isinstance(value, list):
            for item in value:
                collect_paths(item)
    for name, value in stored_settings(storage):
        if name in PROJECT_KEYS:
            collect_paths(value)
        elif name == "thread-workspace-root-hints" and isinstance(value, dict):
            hints.extend((tid, cwd) for tid, cwd in value.items() if isinstance(cwd, str) and Path(cwd).is_absolute())
        elif name == "thread-projectless-output-directories":
            if not isinstance(value, dict):
                raise ValueError("Unsupported projectless output mapping")
            for tid, output in value.items():
                if not isinstance(output, str) or not Path(output).is_absolute():
                    raise ValueError("Unsupported projectless output path (preserved)")
                folder = lexical(Path(output))
                if folder.is_relative_to(root) and len(folder.relative_to(root).parts) == 3 and folder.name == "outputs":
                    folder = folder.parent
                mappings.setdefault(tid, set()).add(folder)

    paths = databases(storage)
    selected_ids = mappings if ids is None else ids
    other_chat_paths = [lexical(Path(cwd)) for tid, cwd in hints if tid not in selected_ids]
    for db in (p for p in paths if family(p) == "state"):
        con = connect(db)
        try:
            tables = schema(con)
            if "path" in tables.get("project_roots", set()):
                for (path,) in con.execute("select path from project_roots"):
                    collect_paths(path)
            cols = tables.get("threads", set())
            if {"id", "cwd"} <= cols:
                for tid, cwd in con.execute("select id,cwd from threads where cwd is not null"):
                    if tid not in selected_ids and isinstance(cwd, str) and Path(cwd).is_absolute():
                        other_chat_paths.append(lexical(Path(cwd)))
        finally:
            con.close()
    targets = []
    for tid in (mappings if ids is None else ids):
        values = mappings.get(tid, set())
        if len(values) > 1:
            raise ValueError(f"Conflicting projectless output paths for {tid}")
        for output in values:
            if not beneath(output, root) or output == root:
                raise ValueError(f"Projectless output outside Documents/Codex (preserved): {output}")
            rel = output.relative_to(root)
            if len(rel.parts) != 2 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rel.parts[0]):
                raise ValueError(f"Unsupported projectless output path (preserved): {output}")
            target = root / rel.parts[0] / rel.parts[1]
            if any(other not in selected_ids and any(beneath(p, target) or beneath(target, p) for p in paths)
                   for other, paths in mappings.items()):
                continue
            checked(target, root)
            if any(beneath(p, target) or beneath(target, p) for p in other_chat_paths):
                continue
            # Git inside this chat belongs to its explicitly mapped output. A containing
            # checkout or a separately registered/shared working directory stays protected.
            project = any(beneath(p, target) or beneath(target, p) for p in project_paths)
            if not project:
                project = any(os.path.lexists(p / ".git") for p in target.parents)
            if project:
                continue
            targets.append((target, root))
    return list(dict.fromkeys(targets))


def writer_locks(storage, ids=None):
    root = storage.home / "thread-writer-locks"
    reject_links(root)
    if root.exists():
        for path in root.iterdir():
            if path.suffix == ".lock" and UUID.fullmatch(path.stem) and (ids is None or path.stem in ids):
                yield path, storage.home


def full_targets(storage):
    targets = [(storage.home / n, storage.home) for n in HISTORY_DIRS + HISTORY_FILES]
    targets.extend(writer_locks(storage))
    if storage.home.exists():
        targets += [(p, storage.home) for pattern in ("..codex-global-state.json*tmp-*", ".codex-global-state.json*.tmp", ".codex-global-state.json*.cleaner.tmp")
                    for p in storage.home.glob(pattern)]
    targets += common_file_targets(storage)
    for desktop in storage.desktops():
        # Browser partitions may contain website logins. Remove only known history
        # and caches, never whole partitions or their authentication stores.
        for parent in [desktop / "Partitions", desktop / "web/Codex"]:
            reject_links(parent)
            if parent.exists():
                for partition in parent.iterdir():
                    if partition.name.startswith("codex-browser-"):
                        reject_links(partition)
                        for name in CACHE_DIRS + ("History", "History-journal", "Top Sites", "Top Sites-journal", "Sessions"):
                            targets.append((partition / name, desktop))
        for name in ("browser-sidebar-page-states.json", "web/Codex/browser-sidebar-page-states.json"):
            targets.append((desktop / name, desktop))
        # Cache/history in the host profile can be discarded without deleting its cookies/settings.
        web = desktop / "web/Codex"
        for name in CACHE_DIRS + ("History", "History-journal", "Top Sites", "Top Sites-journal", "Sessions"):
            targets.append((web / "Default" / name, desktop))
        for name in CACHE_DIRS:
            targets.append((web / name, desktop))
    return targets


def common_file_targets(storage):
    targets = []
    for p in storage.logs():
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
        paths += [desktop / "web/Codex/Default" / n for n in ("Network", "Local Storage", "Session Storage", "IndexedDB", "Preferences", "Login Data")]
        paths.append(desktop / "web/Codex/Local State")
        for parent in (desktop / "Partitions", desktop / "web/Codex"):
            reject_links(parent)
            if parent.exists():
                for partition in parent.iterdir():
                    if partition.name.startswith("codex-browser-"):
                        paths += [partition / n for n in ("Network", "Cookies", "Local Storage", "Session Storage", "IndexedDB", "Preferences", "Login Data", "Local State")]
    return [lexical(p) for p in paths]


def delete_target(path, root, storage):
    target = checked(path, root, allow_leaf_link=True)
    if any(beneath(target, p) or beneath(p, target) for p in protected(storage)):
        raise ValueError(f"Protected settings overlap: {target}")
    remove_path(target, root)


def preserved_configured_paths(storage, *, logs_only=False):
    warnings = []
    if not logs_only and storage.extra_db and lexical(storage.extra_db) not in storage.db_roots() and storage.extra_db.exists():
        warnings.append(f"Custom database location preserved (outside supported scope): {storage.extra_db}")
    if storage.extra_log and lexical(storage.extra_log) not in storage.logs() and storage.extra_log.exists():
        warnings.append(f"Custom log location preserved (outside supported scope): {storage.extra_log}")
    return warnings


def inspect_remaining(storage, ids=None, *, logs_only=False, metadata_refs=None):
    result = Result()
    result.errors.extend(preserved_configured_paths(storage, logs_only=logs_only))
    paths = result.step("Database discovery", lambda: databases(storage)) or []
    refs = ids if metadata_refs is None else metadata_refs
    for path in paths:
        pending = result.step(str(path), lambda p=path: database_rows(p, refs if family(p) == "global" else ids, logs_only=logs_only))
        result.errors.extend(pending or [])
    if ids is None:
        for path, _ in (common_file_targets(storage) if logs_only else full_targets(storage)):
            remaining = result.step(str(path), lambda p=path: has_files(p))
            if remaining:
                result.errors.append(f"Remaining files: {path}")
    if not logs_only:
        if ids is not None:
            result.errors.extend(f"Remaining writer lock: {p}" for p, _ in writer_locks(storage, ids))
        for path in global_files(storage):
            def inspect(p=path):
                reject_links(p)
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                return data != cleaned_global(data, refs)
            if result.step(str(path), inspect):
                result.errors.append(f"Remaining metadata: {path}")
        # These may contain user-managed configuration: detect, never guess-delete.
        if ids is None:
            for name in ("cleanup_backups", "memories_extensions", "worktrees"):
                p = storage.home / name
                if result.step(str(p), lambda p=p: has_files(p)):
                    result.errors.append(f"Manual review required (preserved): {p}")
    return result.errors


def cleanup_all(storage, *, logs_only=False, keep_paths=()):
    result = Result()
    result.errors.extend(preserved_configured_paths(storage, logs_only=logs_only))
    outputs_ok = True
    if not logs_only:
        outputs = result.step("Projectless output discovery", lambda: projectless_outputs(storage, None, keep_paths))
        outputs_ok = outputs is not None
        for target, root in outputs or []:
            before = len(result.errors)
            result.step(str(target), lambda p=target, r=root: delete_target(p, r, storage))
            if os.path.lexists(target):
                result.errors.append(f"Remaining projectless output: {target}")
            outputs_ok = outputs_ok and len(result.errors) == before
    paths = result.step("Database discovery", lambda: databases(storage)) or []
    for path in paths:
        # Retain mappings and registered roots for a safe retry after an output failure.
        if not outputs_ok and family(path) in ("global", "state"):
            continue
        pending = result.step(str(path), lambda p=path: database_rows(p, clean=True, logs_only=logs_only))
        result.errors.extend(pending or [])
    targets = result.step("File discovery", lambda: common_file_targets(storage) if logs_only else full_targets(storage)) or []
    for path, root in targets:
        result.step(str(path), lambda p=path, r=root: delete_target(p, r, storage))
    if not logs_only and outputs_ok:
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
                cwd = ""
                with p.open(encoding="utf-8-sig", errors="replace") as stream:
                    try:
                        header = json.loads(stream.readline(1024 * 1024))
                    except ValueError:
                        header = None
                if isinstance(header, dict) and header.get("type") == "session_meta":
                    payload = header.get("payload")
                    if isinstance(payload, dict):
                        if not match and isinstance(payload.get("id"), str) and UUID.fullmatch(payload["id"]):
                            tid = payload["id"]
                        if isinstance(payload.get("cwd"), str):
                            cwd = payload["cwd"]
                orphan = records.pop((tid, ""), None)
                records[(tid, str(p))] = (tid, orphan[1] if orphan else p.stem, str(p),
                                        root.name == "archived_sessions", p.stat().st_mtime, cwd or (orphan[5] if orphan else ""))
    return list(records.values())


def delete_selected(storage, ids: set[str], rollout_paths: list[str], *, keep_paths=()):
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
        elif p.suffix != ".jsonl" or (UUID.search(p.name) and not contains_id(p.name, ids)):
            result.errors.append(f"Transcript ownership mismatch (preserved): {p}")
        else:
            result.step(str(p), lambda p=p, root=root: checked(p, root))
            paths.append((p, root))
    if result.errors:
        return result.errors
    owned_outputs = result.step("Projectless output discovery", lambda: projectless_outputs(storage, ids, keep_paths)) or []
    refs = result.step("Client thread bindings", lambda: metadata_ids(storage, ids))
    if result.errors:
        return result.errors
    # A thread may have multiple transcript copies across the two directories.
    for root in (storage.home / "sessions", storage.home / "archived_sessions"):
        def find_transcripts(root=root):
            for p in files_under(root):
                if p.suffix == ".jsonl" and contains_id(p.name, ids):
                    if not any(lexical(p) == lexical(existing) for existing, _ in paths):
                        paths.append((p, root))
        result.step(str(root), find_transcripts)
    if result.errors:
        return result.errors
    db_paths = databases(storage)
    for path in db_paths:
        if family(path) == "global":
            continue
        pending = result.step(str(path), lambda p=path: database_rows(p, ids, clean=True))
        result.errors.extend(pending or [])
    # Keep transcript files available for retry if database cleanup failed.
    if result.errors:
        return result.errors
    for target, root in owned_outputs:
        result.step(str(target), lambda p=target, r=root: delete_target(p, r, storage))
        if os.path.lexists(target):
            result.errors.append(f"Remaining projectless output: {target}")
    if result.errors:
        return result.errors
    for name, field in [("history.jsonl", "session_id"), ("session_index.jsonl", "id")]:
        path = storage.home / name
        if path.exists():
            result.step(str(path), lambda p=path, f=field: filter_jsonl(p, storage.home, f, ids))
    for path, root in writer_locks(storage, ids):
        result.step(str(path), lambda p=path, r=root: delete_target(p, r, storage))
    for path in global_files(storage):
        result.step(str(path), lambda p=path: rewrite_json(p, storage.home, lambda d: cleaned_global(d, refs)))
    for path in db_paths:
        if family(path) == "global":
            pending = result.step(str(path), lambda p=path: database_rows(p, refs, clean=True))
            result.errors.extend(pending or [])
    # Only explicit task-named directories/files: never infer ownership from cwd.
    for name in OWNED_DIRS:
        root = storage.home / name
        if root.exists():
            def prune_owned(root=root):
                reject_links(root)
                for base, dirs, files in os.walk(root, followlinks=False):
                    for child in dirs + files:
                        p = Path(base) / child
                        if contains_id(p.name, ids):
                            result.step(str(p), lambda p=p: delete_target(p, storage.home, storage))
                            if child in dirs:
                                dirs.remove(child)
            result.step(str(root), prune_owned)
    # Verification must inspect the same owned paths, including empty directories.
    for name in OWNED_DIRS:
        root = storage.home / name
        if root.exists():
            def verify_owned(root=root):
                reject_links(root)
                for base, dirs, files in os.walk(root, followlinks=False):
                    for child in dirs + files:
                        if contains_id(child, ids):
                            result.errors.append(f"Remaining owned item: {Path(base) / child}")
            result.step(str(root), verify_owned)
    if not result.errors:
        for path, root in paths:
            result.step(str(path), lambda p=path, r=root: remove_path(p, r))
    for path, _ in paths:
        if path.exists():
            result.errors.append(f"Remaining transcript: {path}")
    pending = result.step("Verification", lambda: inspect_remaining(storage, ids, metadata_refs=refs))
    result.errors.extend(pending or [])
    return list(dict.fromkeys(result.errors))


def filter_jsonl(path, root, field, ids):
    path = checked(path, root)
    with replacement_file(path, root) as dest, path.open(encoding="utf-8-sig", newline="") as source:
        for line in source:
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError(f"Invalid JSONL object: {path}")
                if item.get(field) in ids:
                    continue
            dest.write(line)
