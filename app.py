import json
import locale
import os
import shutil
import sqlite3
import subprocess
import time
import tkinter as tk
import ctypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk


APP_NAME = "AI Archive Cleaner"

COLOR_BG = "#171a1e"
COLOR_PANEL = "#20242a"
COLOR_PANEL_ALT = "#1c2026"
COLOR_BORDER = "#3a4048"
COLOR_TEXT = "#f2f3f5"
COLOR_MUTED = "#b8c0cc"
COLOR_ACCENT = "#23b6a4"
COLOR_BUTTON = "#2a3038"
COLOR_BUTTON_ACTIVE = "#343b45"
COLOR_SCROLL_DISABLED = "#252b33"

STRINGS = {
    "ja": {
        "provider_codex": "Codex",
        "provider_codex_docs": "Codex生成物",
        "provider_claude": "Claude",
        "none": "なし",
        "size_failed": "取得失敗",
        "untitled": "(無題)",
        "archived": "アーカイブ済み",
        "normal": "通常",
        "jsonl_history": "JSONL履歴",
        "artifact": "生成物",
        "delete": "削除",
        "reload": "再読み込み",
        "check_all": "全チェック",
        "uncheck_all": "全解除",
        "delete_common": "共通ログ/キャッシュも一緒に消す",
        "search": "検索",
        "kind": "種類",
        "title": "タイトル",
        "updated": "更新日時",
        "size": "サイズ",
        "status": "状態",
        "cwd": "作業フォルダ",
        "path": "保存場所",
        "load_failed": "読み込みに失敗しました。\n\n{error}",
        "status_line": "{shown} 件を表示中 / チェック {checked} 件 / 共通ログ・キャッシュ {common} 箇所",
        "select_to_delete": "削除するチャット/生成物にチェックを入れてください。",
        "running_apps": "対象アプリが起動中です。\n書き込み競合を避けるため、終了してから削除します。\n\n終了対象: {apps}\n\n終了して続行しますか？",
        "more_items": "...ほか {count} 件",
        "delete_common_confirm": "\n共通ログ/キャッシュも一緒に削除します。",
        "confirm_delete": "選択した {count} 件を完全削除します。{common_text}\nバックアップは作りません。\n\n{titles}\n\n続行しますか？",
        "processed_warning": "チャット/生成物 {records} 件、共通痕跡 {common} 箇所を処理しました。\n一部に失敗があります。\n\n{errors}",
        "processed_info": "チャット/生成物 {records} 件、共通痕跡 {common} 箇所を処理しました。",
        "stop_process_failed": "対象アプリを終了できませんでした。手動で終了してから再実行してください。",
        "empty_delete_path": "削除パスが空です",
        "refuse_root_delete": "保存場所のルート自体は削除しません: {path}",
        "outside_allowed_path": "許可された場所の外です: {path}",
        "protected_common_path": "設定・認証・履歴に関わるため共通削除では扱いません: {path}",
        "unsupported_action": "未対応の処理です: {action}",
        "common_codex_logs_db": "Codex ログDB",
        "common_codex_tui_log": "Codex TUIログ",
        "common_codex_sandbox_log": "Codex sandboxログ",
        "common_codex_internal_sandbox_log": "Codex sandbox内部ログ",
        "common_claude_session_env": "Claude Code セッション環境",
        "common_claude_shell_snapshots": "Claude Code shellスナップショット",
        "common_claude_cli_node_cache": "Claude CLI Node.jsキャッシュ",
        "common_claude_native_host_logs": "Claude Native Hostログ",
        "common_claude_desktop": "Claude Desktop {name}",
        "windows_only": "このツールはWindows専用です。",
    },
    "en": {
        "provider_codex": "Codex",
        "provider_codex_docs": "Codex Artifacts",
        "provider_claude": "Claude",
        "none": "None",
        "size_failed": "Failed",
        "untitled": "(Untitled)",
        "archived": "Archived",
        "normal": "Normal",
        "jsonl_history": "JSONL history",
        "artifact": "Artifact",
        "delete": "Delete",
        "reload": "Reload",
        "check_all": "Check all",
        "uncheck_all": "Clear all",
        "delete_common": "Also delete shared logs/cache",
        "search": "Search",
        "kind": "Type",
        "title": "Title",
        "updated": "Updated",
        "size": "Size",
        "status": "Status",
        "cwd": "Working folder",
        "path": "Path",
        "load_failed": "Failed to load records.\n\n{error}",
        "status_line": "{shown} shown / {checked} checked / {common} shared log/cache targets",
        "select_to_delete": "Check chats/artifacts to delete first.",
        "running_apps": "Target apps are running.\nThey will be closed before deletion to avoid write conflicts.\n\nApps to close: {apps}\n\nClose them and continue?",
        "more_items": "...and {count} more",
        "delete_common_confirm": "\nShared logs/cache will also be deleted.",
        "confirm_delete": "Permanently delete {count} selected item(s).{common_text}\nNo backup will be created.\n\n{titles}\n\nContinue?",
        "processed_warning": "Processed {records} chat/artifact item(s) and {common} shared trace target(s).\nSome operations failed.\n\n{errors}",
        "processed_info": "Processed {records} chat/artifact item(s) and {common} shared trace target(s).",
        "stop_process_failed": "Could not close the target apps. Close them manually and run again.",
        "empty_delete_path": "Delete path is empty",
        "refuse_root_delete": "Refusing to delete the storage root itself: {path}",
        "outside_allowed_path": "Path is outside the allowed locations: {path}",
        "protected_common_path": "Shared cleanup will not touch settings, auth, or history paths: {path}",
        "unsupported_action": "Unsupported action: {action}",
        "common_codex_logs_db": "Codex logs DB",
        "common_codex_tui_log": "Codex TUI logs",
        "common_codex_sandbox_log": "Codex sandbox log",
        "common_codex_internal_sandbox_log": "Codex internal sandbox log",
        "common_claude_session_env": "Claude Code session env",
        "common_claude_shell_snapshots": "Claude Code shell snapshots",
        "common_claude_cli_node_cache": "Claude CLI Node.js cache",
        "common_claude_native_host_logs": "Claude Native Host logs",
        "common_claude_desktop": "Claude Desktop {name}",
        "windows_only": "This tool supports Windows only.",
    },
}


def language_code() -> str:
    try:
        lang = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
    except Exception:
        lang = ""
    return "ja" if lang.lower().startswith("ja") else "en"


LANGUAGE = language_code()


def tr(key: str, **kwargs) -> str:
    text = STRINGS.get(LANGUAGE, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text


PROVIDER_CODEX = tr("provider_codex")
PROVIDER_CODEX_DOCS = tr("provider_codex_docs")
PROVIDER_CLAUDE = tr("provider_claude")


def app_dir() -> Path:
    return Path(__file__).resolve().parent


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass
class CleanRecord:
    provider: str
    record_id: str
    title: str
    path: str
    updated_at: float
    cwd: str = ""
    status: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}|{self.record_id}|{self.path}"

    @property
    def updated_label(self) -> str:
        if not self.updated_at:
            return ""
        return datetime.fromtimestamp(self.updated_at).strftime("%Y-%m-%d %H:%M")

    @property
    def size_label(self) -> str:
        path = Path(self.path)
        if not path.exists():
            return tr("none")
        try:
            size = folder_size(path) if path.is_dir() else path.stat().st_size
        except OSError:
            return tr("size_failed")
        return format_size(size)


@dataclass
class CommonTarget:
    name: str
    path: Path
    action: str


def folder_size(path: Path) -> int:
    total = 0
    try:
        items = path.rglob("*")
    except OSError:
        return 0
    for item in items:
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def format_size(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def run_hidden(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def process_running(image_name: str) -> bool:
    try:
        result = run_hidden(["tasklist", "/FI", f"IMAGENAME eq {image_name}"])
    except Exception:
        return False
    return image_name.lower() in result.stdout.lower()


def stop_processes(image_names: list[str]) -> None:
    for image_name in image_names:
        run_hidden(["taskkill", "/IM", image_name, "/T", "/F"])
    for _ in range(25):
        if not any(process_running(name) for name in image_names):
            return
        time.sleep(0.2)
    raise RuntimeError(tr("stop_process_failed"))


def home() -> Path:
    return Path.home()


def appdata_roaming() -> Path:
    return Path(os.environ.get("APPDATA", str(home() / "AppData" / "Roaming")))


def appdata_local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(home() / "AppData" / "Local")))


def codex_home() -> Path:
    return home() / ".codex"


def claude_home() -> Path:
    return home() / ".claude"


def codex_db_path() -> Path:
    return codex_home() / "state_5.sqlite"


def codex_logs_db_path() -> Path:
    return codex_home() / "logs_2.sqlite"


def codex_index_path() -> Path:
    return codex_home() / "session_index.jsonl"


def codex_history_path() -> Path:
    return codex_home() / "history.jsonl"


def codex_global_state_path() -> Path:
    return codex_home() / ".codex-global-state.json"


def codex_sessions_path() -> Path:
    return codex_home() / "sessions"


def codex_archived_sessions_path() -> Path:
    return codex_home() / "archived_sessions"


def codex_documents_path() -> Path:
    return home() / "Documents" / "Codex"


def claude_projects_path() -> Path:
    return claude_home() / "projects"


def claude_history_path() -> Path:
    return claude_home() / "history.jsonl"


def claude_json_path() -> Path:
    return home() / ".claude.json"


def claude_desktop_code_sessions_path() -> Path:
    return appdata_roaming() / "Claude" / "claude-code-sessions"


def safe_resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_record_path(record: CleanRecord) -> Path:
    if not record.path.strip():
        raise ValueError(tr("empty_delete_path"))

    target = safe_resolve(Path(record.path))
    if record.provider == PROVIDER_CODEX:
        roots = [codex_sessions_path(), codex_archived_sessions_path()]
    elif record.provider == PROVIDER_CODEX_DOCS:
        roots = [codex_documents_path()]
    elif record.provider == PROVIDER_CLAUDE:
        roots = [claude_projects_path()]
    else:
        roots = []

    resolved_roots = [safe_resolve(root) for root in roots]
    if target in resolved_roots:
        raise ValueError(tr("refuse_root_delete", path=target))
    if not any(is_relative_to(target, root) for root in resolved_roots):
        raise ValueError(tr("outside_allowed_path", path=target))
    return target


def delete_record_file(record: CleanRecord) -> None:
    target = validate_record_path(record)
    if not target.exists():
        return
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def load_codex_records() -> list[CleanRecord]:
    if not codex_db_path().exists():
        return []
    con = sqlite3.connect(f"file:{codex_db_path()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """
            select id, title, rollout_path, archived, updated_at, cwd
            from threads
            order by updated_at desc
            """
        ).fetchall()
    finally:
        con.close()

    records = []
    for thread_id, title, rollout_path, archived, updated_at, cwd in rows:
        records.append(
            CleanRecord(
                provider=PROVIDER_CODEX,
                record_id=thread_id,
                title=title or tr("untitled"),
                path=rollout_path or "",
                updated_at=float(updated_at or 0),
                cwd=cwd or "",
                status=tr("archived") if archived else tr("normal"),
            )
        )
    return records


def extract_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def normalize_title(title: str, fallback: str) -> str:
    normalized = " ".join((title or fallback).split())
    if len(normalized) > 100:
        normalized = normalized[:97] + "..."
    return normalized


def summarize_claude_jsonl(path: Path) -> tuple[str, str, str]:
    explicit_title = ""
    first_user_text = ""
    cwd = ""
    session_id = path.stem
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = item.get("sessionId") or session_id
                cwd = item.get("cwd") or cwd
                candidate = item.get("summary") or item.get("title") or item.get("name")
                if isinstance(candidate, str) and candidate.strip():
                    explicit_title = candidate.strip()
                if not first_user_text and item.get("type") == "user":
                    message = item.get("message") or {}
                    first_user_text = extract_text(message.get("content")).strip()
                if item.get("type") == "queue-operation" and item.get("content"):
                    explicit_title = str(item.get("content")).strip()
    except OSError:
        pass

    return session_id, normalize_title(explicit_title or first_user_text, path.stem), cwd


def decode_claude_project_name(name: str) -> str:
    if "--" in name:
        return name.replace("--", ":\\").replace("-", "\\")
    return name


def load_claude_desktop_titles() -> dict[str, str]:
    root = claude_desktop_code_sessions_path()
    if not root.exists():
        return {}

    titles = {}
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        cli_session_id = data.get("cliSessionId")
        title = data.get("title")
        if isinstance(cli_session_id, str) and isinstance(title, str) and title.strip():
            titles[cli_session_id] = title.strip()
    return titles


def load_claude_records() -> list[CleanRecord]:
    root = claude_projects_path()
    if not root.exists():
        return []
    desktop_titles = load_claude_desktop_titles()
    records = []
    for path in root.rglob("*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        session_id, title, cwd = summarize_claude_jsonl(path)
        title = normalize_title(desktop_titles.get(session_id, title), path.stem)
        records.append(
            CleanRecord(
                provider=PROVIDER_CLAUDE,
                record_id=session_id,
                title=title,
                path=str(path),
                updated_at=stat.st_mtime,
                cwd=cwd or decode_claude_project_name(path.parent.name),
                status=tr("jsonl_history"),
            )
        )
    records.sort(key=lambda item: item.updated_at, reverse=True)
    return records


def load_codex_document_records() -> list[CleanRecord]:
    root = codex_documents_path()
    if not root.exists():
        return []
    records = []
    for path in root.iterdir():
        try:
            stat = path.stat()
        except OSError:
            continue
        records.append(
            CleanRecord(
                provider=PROVIDER_CODEX_DOCS,
                record_id=path.name,
                title=f"Documents\\Codex\\{path.name}",
                path=str(path),
                updated_at=stat.st_mtime,
                cwd=str(root),
                status=tr("artifact"),
            )
        )
    records.sort(key=lambda item: item.updated_at, reverse=True)
    return records


def load_records() -> list[CleanRecord]:
    records = load_codex_records()
    records.extend(load_claude_records())
    records.extend(load_codex_document_records())
    records.sort(key=lambda item: item.updated_at, reverse=True)
    return records


def remove_jsonl_lines_by_field(path: Path, field: str, ids: set[str]) -> None:
    if not ids or not path.exists():
        return
    kept_lines = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                kept_lines.append(line)
                continue
            if item.get(field) not in ids:
                kept_lines.append(line)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text("".join(kept_lines), encoding="utf-8")
    temp_path.replace(path)


def delete_sql_rows(db_path: Path, statements: list[tuple[str, list[str]]]) -> None:
    if not db_path.exists() or not statements:
        return
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        existing_tables = {
            row[0] for row in cur.execute("select name from sqlite_master where type='table'")
        }
        cur.execute("begin")
        for sql, params in statements:
            table_name = sql.split()[2]
            if table_name in existing_tables:
                cur.execute(sql, params)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def delete_codex_db_rows(ids: set[str]) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    params = list(ids)
    statements = [
        (f"delete from stage1_outputs where thread_id in ({placeholders})", params),
        (f"delete from thread_dynamic_tools where thread_id in ({placeholders})", params),
        (f"delete from thread_goals where thread_id in ({placeholders})", params),
        (f"delete from agent_job_items where assigned_thread_id in ({placeholders})", params),
        (
            f"""
            delete from thread_spawn_edges
            where parent_thread_id in ({placeholders})
               or child_thread_id in ({placeholders})
            """,
            params + params,
        ),
        (f"delete from threads where id in ({placeholders})", params),
    ]
    delete_sql_rows(codex_db_path(), statements)


def delete_codex_log_rows(ids: set[str]) -> None:
    if not ids or not codex_logs_db_path().exists():
        return
    placeholders = ",".join("?" for _ in ids)
    con = sqlite3.connect(codex_logs_db_path())
    try:
        cur = con.cursor()
        existing_tables = {
            row[0] for row in cur.execute("select name from sqlite_master where type='table'")
        }
        cur.execute("begin")
        if "logs" in existing_tables:
            cur.execute(f"delete from logs where thread_id in ({placeholders})", list(ids))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def normalize_codex_workspace_path(value: str) -> str:
    if not value:
        return ""
    text = value.strip()
    if text.startswith("\\\\?\\"):
        text = text[4:]
    try:
        text = str(safe_resolve(Path(text)))
    except Exception:
        pass
    return os.path.normcase(os.path.normpath(text))


def display_path_text(value: str) -> str:
    if not value:
        return ""
    text = value.strip()
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def remaining_codex_workspace_paths() -> set[str]:
    if not codex_db_path().exists():
        return set()
    con = sqlite3.connect(f"file:{codex_db_path()}?mode=ro", uri=True)
    try:
        rows = con.execute("select distinct cwd from threads").fetchall()
    finally:
        con.close()
    return {normalized for (cwd,) in rows if (normalized := normalize_codex_workspace_path(cwd or ""))}


def prune_codex_global_project_state(deleted_cwds: set[str]) -> None:
    path = codex_global_state_path()
    if not deleted_cwds or not path.exists():
        return

    remaining_cwds = remaining_codex_workspace_paths()
    stale_cwds = {
        normalized
        for cwd in deleted_cwds
        if (normalized := normalize_codex_workspace_path(cwd)) and normalized not in remaining_cwds
    }
    if not stale_cwds:
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return

    changed = False
    for key in ["electron-saved-workspace-roots", "project-order", "active-workspace-roots"]:
        values = data.get(key)
        if not isinstance(values, list):
            continue
        filtered = [
            value
            for value in values
            if not (isinstance(value, str) and normalize_codex_workspace_path(value) in stale_cwds)
        ]
        if len(filtered) != len(values):
            data[key] = filtered
            changed = True

    if not changed:
        return

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp_path.replace(path)


def update_claude_json_last_sessions(session_ids: set[str]) -> None:
    path = claude_json_path()
    if not session_ids or not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = False
    for project in data.get("projects", {}).values():
        if isinstance(project, dict) and project.get("lastSessionId") in session_ids:
            project.pop("lastSessionId", None)
            project.pop("lastSessionMetrics", None)
            changed = True
    if changed:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)


def delete_claude_desktop_code_session_files(session_ids: set[str]) -> list[str]:
    if not session_ids:
        return []

    root = claude_desktop_code_sessions_path()
    if not root.exists():
        return []

    root = safe_resolve(root)
    errors = []
    for path in root.rglob("*.json"):
        try:
            resolved = safe_resolve(path)
            if not is_relative_to(resolved, root):
                raise ValueError(tr("outside_allowed_path", path=resolved))
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, dict):
                continue
            if data.get("cliSessionId") in session_ids:
                path.unlink()
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    cleanup_empty_dirs(root)
    return errors


def cleanup_empty_dirs(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        return
    root = safe_resolve(root)
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            resolved = safe_resolve(path)
            if resolved != root and is_relative_to(resolved, root) and path.is_dir():
                path.rmdir()
        except OSError:
            pass


def delete_selected_records(records: list[CleanRecord]) -> tuple[int, list[str]]:
    errors = []
    deleted = []
    for record in records:
        try:
            delete_record_file(record)
            deleted.append(record)
        except Exception as exc:
            errors.append(f"{record.title}: {exc}")

    codex_ids = {record.record_id for record in deleted if record.provider == PROVIDER_CODEX}
    codex_cwds = {record.cwd for record in deleted if record.provider == PROVIDER_CODEX and record.cwd}
    claude_ids = {record.record_id for record in deleted if record.provider == PROVIDER_CLAUDE}
    delete_codex_db_rows(codex_ids)
    delete_codex_log_rows(codex_ids)
    remove_jsonl_lines_by_field(codex_index_path(), "id", codex_ids)
    remove_jsonl_lines_by_field(codex_history_path(), "session_id", codex_ids)
    prune_codex_global_project_state(codex_cwds)
    remove_jsonl_lines_by_field(claude_history_path(), "sessionId", claude_ids)
    update_claude_json_last_sessions(claude_ids)
    errors.extend(delete_claude_desktop_code_session_files(claude_ids))

    for root in [
        codex_sessions_path(),
        codex_archived_sessions_path(),
        codex_documents_path(),
        claude_projects_path(),
    ]:
        cleanup_empty_dirs(root)
    return len(deleted), errors


def delete_dir_contents(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def truncate_file(path: Path) -> None:
    if path.exists() and path.is_file():
        path.write_text("", encoding="utf-8")


def clean_codex_logs_db_all() -> None:
    path = codex_logs_db_path()
    if not path.exists():
        return
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        tables = {row[0] for row in cur.execute("select name from sqlite_master where type='table'")}
        cur.execute("begin")
        if "logs" in tables:
            cur.execute("delete from logs")
        con.commit()
        cur.execute("pragma wal_checkpoint(TRUNCATE)")
        cur.execute("vacuum")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def clean_claude_json_trace() -> None:
    path = claude_json_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = False
    for key in ["skillUsage", "seenNotifications", "tipsHistory"]:
        if key in data:
            data[key] = {} if isinstance(data[key], dict) else []
            changed = True
    if changed:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)


def protected_common_paths() -> list[Path]:
    codex = codex_home()
    claude = claude_home()
    roaming_claude = appdata_roaming() / "Claude"
    return [
        codex / "auth.json",
        codex / "config.toml",
        codex / "state_5.sqlite",
        codex / "state_5.sqlite-wal",
        codex / "state_5.sqlite-shm",
        codex / "session_index.jsonl",
        codex / "history.jsonl",
        codex / ".codex-global-state.json",
        codex / ".codex-global-state.json.bak",
        codex / "sessions",
        codex / "archived_sessions",
        codex / "plugins",
        codex / "skills",
        codex / "memories",
        claude / "projects",
        claude / "history.jsonl",
        claude_json_path(),
        home() / ".claude.json.backup",
        roaming_claude / "config.json",
        roaming_claude / "Preferences",
        roaming_claude / "Local State",
        roaming_claude / "IndexedDB",
        roaming_claude / "Local Storage",
        roaming_claude / "Network",
        roaming_claude / "Partitions",
        roaming_claude / "Session Storage",
        roaming_claude / "WebStorage",
        roaming_claude / "blob_storage",
        roaming_claude / "local-agent-mode-sessions",
        claude_desktop_code_sessions_path(),
        roaming_claude / "claude-code-vm",
        roaming_claude / "vm_bundles",
        roaming_claude / "Claude Extensions",
        roaming_claude / "Claude Extensions Settings",
    ]


def is_protected_common_path(path: Path) -> bool:
    resolved = safe_resolve(path)
    for protected in protected_common_paths():
        protected_resolved = safe_resolve(protected)
        if resolved == protected_resolved or is_relative_to(resolved, protected_resolved):
            return True
    return False


def common_targets() -> list[CommonTarget]:
    codex = codex_home()
    claude = claude_home()
    roaming_claude = appdata_roaming() / "Claude"
    local = appdata_local()
    targets = [
        CommonTarget(tr("common_codex_logs_db"), codex / "logs_2.sqlite", "codex_logs_db"),
        CommonTarget(tr("common_codex_tui_log"), codex / "log", "contents"),
        CommonTarget(tr("common_codex_sandbox_log"), codex / "sandbox.log", "delete_file"),
        CommonTarget(tr("common_codex_internal_sandbox_log"), codex / ".sandbox" / "sandbox.log", "delete_file"),
        CommonTarget(tr("common_claude_session_env"), claude / "session-env", "contents"),
        CommonTarget(tr("common_claude_shell_snapshots"), claude / "shell-snapshots", "contents"),
        CommonTarget(tr("common_claude_cli_node_cache"), local / "claude-cli-nodejs" / "Cache", "contents"),
        CommonTarget(tr("common_claude_native_host_logs"), local / "Claude" / "Logs", "contents"),
    ]
    for name in [
        "Cache",
        "Code Cache",
        "Crashpad",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "GPUCache",
        "sentry",
        "Shared Dictionary",
        "logs",
    ]:
        targets.append(CommonTarget(tr("common_claude_desktop", name=name), roaming_claude / name, "contents"))
    return [target for target in targets if target.path.exists()]


def clean_common_traces() -> tuple[int, list[str]]:
    errors = []
    cleaned = 0
    allowed_roots = [
        safe_resolve(codex_home()),
        safe_resolve(claude_home()),
        safe_resolve(appdata_roaming() / "Claude"),
        safe_resolve(appdata_local() / "Claude"),
        safe_resolve(appdata_local() / "claude-cli-nodejs"),
    ]
    allowed_files = {
        safe_resolve(home() / ".claude.json"),
        safe_resolve(home() / ".claude.json.backup"),
    }
    for target in common_targets():
        try:
            resolved = safe_resolve(target.path)
            if resolved not in allowed_files and not any(
                resolved == root or is_relative_to(resolved, root) for root in allowed_roots
            ):
                raise ValueError(tr("outside_allowed_path", path=resolved))
            if is_protected_common_path(resolved):
                raise ValueError(tr("protected_common_path", path=resolved))

            if target.action == "contents":
                delete_dir_contents(resolved)
            elif target.action == "truncate":
                truncate_file(resolved)
            elif target.action == "delete_file":
                if resolved.exists() and resolved.is_file():
                    resolved.unlink()
            elif target.action == "codex_logs_db":
                clean_codex_logs_db_all()
            elif target.action == "claude_json_trace":
                clean_claude_json_trace()
            else:
                raise ValueError(tr("unsupported_action", action=target.action))
            cleaned += 1
        except Exception as exc:
            errors.append(f"{target.name}: {exc}")
    return cleaned, errors


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        icon_path = app_dir() / "favicon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        self.geometry("1148x716")
        self.minsize(720, 420)

        self.records: dict[str, CleanRecord] = {}
        self.checked_keys: set[str] = set()
        self.search_var = tk.StringVar(value="")
        self.common_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="")
        self.sort_column = "updated"
        self.sort_reverse = True
        self.columns = ("checked", "provider", "title", "updated", "size", "status", "cwd", "path")
        self.default_display_columns = ("checked", "provider", "title", "status", "updated", "size", "cwd", "path")
        self.fixed_width_columns = {"checked", "provider", "updated"}
        self.heading_press_column = ""
        self.heading_dragging = False
        self.heading_press_x = 0
        self.heading_reorder_ready = False
        self.heading_long_press_job = ""
        self.heading_drop_index = 0
        self.drop_indicator: tk.Frame | None = None

        self._setup_theme()
        self._build_ui()
        self.refresh()

    def _setup_theme(self) -> None:
        self.configure(background=COLOR_BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, fieldbackground=COLOR_PANEL)
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure(
            "TButton",
            background=COLOR_BUTTON,
            foreground=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            focusthickness=1,
            focuscolor=COLOR_ACCENT,
            padding=(10, 5),
        )
        style.map(
            "TButton",
            background=[("active", COLOR_BUTTON_ACTIVE), ("pressed", COLOR_PANEL)],
            foreground=[("disabled", COLOR_MUTED)],
        )
        style.configure(
            "TCheckbutton",
            background=COLOR_BG,
            foreground=COLOR_TEXT,
            indicatorcolor=COLOR_PANEL,
            focuscolor=COLOR_ACCENT,
        )
        style.map(
            "TCheckbutton",
            background=[("active", COLOR_BG)],
            foreground=[("disabled", COLOR_MUTED)],
            indicatorcolor=[("selected", COLOR_ACCENT), ("!selected", COLOR_PANEL)],
        )
        style.configure(
            "TEntry",
            fieldbackground=COLOR_PANEL,
            foreground=COLOR_TEXT,
            insertcolor=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
        )
        style.configure(
            "Treeview",
            background=COLOR_PANEL,
            fieldbackground=COLOR_PANEL,
            foreground=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            rowheight=24,
        )
        style.map(
            "Treeview",
            background=[("selected", COLOR_ACCENT)],
            foreground=[("selected", "#111315")],
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_BUTTON,
            foreground=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
            relief="solid",
            borderwidth=1,
            padding=(6, 4),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", COLOR_BUTTON_ACTIVE), ("pressed", COLOR_PANEL)],
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=COLOR_BUTTON,
            troughcolor=COLOR_BG,
            bordercolor=COLOR_BORDER,
            arrowcolor=COLOR_TEXT,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
        )
        style.configure(
            "Vertical.TScrollbar",
            background=COLOR_BUTTON,
            troughcolor=COLOR_BG,
            bordercolor=COLOR_BORDER,
            arrowcolor=COLOR_TEXT,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[("disabled", COLOR_SCROLL_DISABLED), ("active", COLOR_BUTTON_ACTIVE)],
            troughcolor=[("disabled", COLOR_BG)],
            arrowcolor=[("disabled", COLOR_MUTED)],
            bordercolor=[("disabled", COLOR_BORDER)],
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("disabled", COLOR_SCROLL_DISABLED), ("active", COLOR_BUTTON_ACTIVE)],
            troughcolor=[("disabled", COLOR_BG)],
            arrowcolor=[("disabled", COLOR_MUTED)],
            bordercolor=[("disabled", COLOR_BORDER)],
        )

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(12, 10, 12, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(5, weight=1)

        ttk.Button(top, text=tr("delete"), command=self.delete_checked).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(top, text=tr("reload"), command=self.refresh).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(top, text=tr("check_all"), command=self.check_all).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(top, text=tr("uncheck_all"), command=self.uncheck_all).grid(row=0, column=3, padx=(0, 12))
        ttk.Checkbutton(top, text=tr("delete_common"), variable=self.common_var, command=self.update_status).grid(
            row=0, column=4, padx=(0, 12)
        )
        ttk.Label(top, text=tr("search")).grid(row=0, column=6, padx=(0, 6), sticky="e")
        search = ttk.Entry(top, textvariable=self.search_var, width=28)
        search.grid(row=0, column=7, sticky="e")
        search.bind("<KeyRelease>", lambda _event: self.refresh())

        self.tree = ttk.Treeview(self, columns=self.columns, show="headings", selectmode="none")
        self.tree["displaycolumns"] = self.default_display_columns
        self.tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        self.tree.bind("<ButtonPress-1>", self.on_tree_button_press)
        self.tree.bind("<B1-Motion>", self.on_tree_mouse_drag)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_button_release)
        self.tree.tag_configure("odd", background=COLOR_PANEL)
        self.tree.tag_configure("even", background=COLOR_PANEL_ALT)

        headings = {
            "checked": tr("delete"),
            "provider": tr("kind"),
            "title": tr("title"),
            "updated": tr("updated"),
            "size": tr("size"),
            "status": tr("status"),
            "cwd": tr("cwd"),
            "path": tr("path"),
        }
        for column, label in headings.items():
            self.tree.heading(column, text=label)

        self.tree.column("checked", width=50, minwidth=50, anchor="center", stretch=False)
        self.tree.column("provider", width=84, minwidth=84, stretch=False)
        self.tree.column("title", width=328, minwidth=220, stretch=False)
        self.tree.column("updated", width=154, minwidth=154, stretch=False)
        self.tree.column("size", width=90, minwidth=70, anchor="e", stretch=False)
        self.tree.column("status", width=100, minwidth=90, stretch=False)
        self.tree.column("cwd", width=160, minwidth=160, stretch=False)
        self.tree.column("path", width=160, minwidth=160, stretch=False)
        self.drop_indicator = tk.Frame(self.tree, background=COLOR_ACCENT, width=2)

        y_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        y_scrollbar.grid(row=1, column=1, sticky="ns")
        x_scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        x_scrollbar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.tree.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set)

        bottom = ttk.Frame(self, padding=(12, 0, 12, 10))
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def checkbox_text(self, key: str) -> str:
        return "[x]" if key in self.checked_keys else "[ ]"

    def row_matches(self, record: CleanRecord, query: str) -> bool:
        if not query:
            return True
        text = " ".join([record.provider, record.title, record.cwd, record.path]).lower()
        return query.lower() in text

    def sort_value(self, record: CleanRecord, column: str):
        if column == "checked":
            return record.key in self.checked_keys
        if column == "provider":
            return record.provider.lower()
        if column == "title":
            return record.title.lower()
        if column == "updated":
            return record.updated_at
        if column == "size":
            path = Path(record.path)
            try:
                return folder_size(path) if path.is_dir() else path.stat().st_size
            except OSError:
                return -1
        if column == "status":
            return record.status.lower()
        if column == "cwd":
            return record.cwd.lower()
        if column == "path":
            return record.path.lower()
        return ""

    def sort_records(self, records: list[CleanRecord]) -> list[CleanRecord]:
        return sorted(
            records,
            key=lambda record: (self.sort_value(record, self.sort_column), record.updated_at),
            reverse=self.sort_reverse,
        )

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = column in {"updated", "size", "checked"}
        self.refresh()

    def current_display_columns(self) -> tuple[str, ...]:
        display_columns = self.tree["displaycolumns"]
        if display_columns in ("", "#all", ("#all",)):
            return self.columns
        return tuple(display_columns)

    def display_column_name(self, tree_column: str) -> str:
        if not tree_column.startswith("#"):
            return ""
        try:
            index = int(tree_column[1:]) - 1
        except ValueError:
            return ""
        columns = self.current_display_columns()
        if 0 <= index < len(columns):
            return columns[index]
        return ""

    def heading_boundary_positions(self) -> list[int]:
        columns = self.current_display_columns()
        widths = [int(self.tree.column(column, "width")) for column in columns]
        total_width = sum(widths)
        scroll_offset = int(total_width * self.tree.xview()[0]) if total_width else 0
        positions = [-scroll_offset]
        current = -scroll_offset
        for width in widths:
            current += width
            positions.append(current)
        return positions

    def heading_drop_index_at(self, x: int) -> int:
        positions = self.heading_boundary_positions()
        if not positions:
            return 0
        index = min(range(len(positions)), key=lambda item: abs(positions[item] - x))
        return max(0, min(index, len(self.current_display_columns())))

    def show_drop_indicator(self, index: int) -> None:
        if not self.drop_indicator:
            return
        positions = self.heading_boundary_positions()
        if not positions:
            return
        index = max(0, min(index, len(positions) - 1))
        x = positions[index]
        self.heading_drop_index = index
        self.drop_indicator.place(x=x - 1, y=0, width=2, height=self.tree.winfo_height())
        self.drop_indicator.lift()

    def hide_drop_indicator(self) -> None:
        if self.drop_indicator:
            self.drop_indicator.place_forget()

    def on_tree_button_press(self, event: tk.Event):
        region = self.tree.identify_region(event.x, event.y)
        column = self.display_column_name(self.tree.identify_column(event.x))
        self.heading_press_column = ""
        self.heading_dragging = False
        self.heading_press_x = event.x
        self.heading_reorder_ready = False
        self.heading_drop_index = 0
        self.hide_drop_indicator()
        if self.heading_long_press_job:
            self.after_cancel(self.heading_long_press_job)
            self.heading_long_press_job = ""

        if region == "separator" and column in self.fixed_width_columns:
            return "break"
        if region == "heading":
            self.heading_press_column = column
            self.heading_long_press_job = self.after(450, self.enable_heading_reorder)
            return "break"
        return None

    def enable_heading_reorder(self) -> None:
        self.heading_reorder_ready = bool(self.heading_press_column)
        self.heading_long_press_job = ""
        if self.heading_reorder_ready:
            self.show_drop_indicator(self.heading_drop_index_at(self.heading_press_x))

    def on_tree_mouse_drag(self, event: tk.Event):
        if (
            self.heading_press_column
            and self.heading_reorder_ready
            and abs(event.x - self.heading_press_x) > 8
        ):
            self.heading_dragging = True
            self.show_drop_indicator(self.heading_drop_index_at(event.x))
            return "break"
        if self.heading_press_column:
            return "break"
        region = self.tree.identify_region(event.x, event.y)
        column = self.display_column_name(self.tree.identify_column(event.x))
        if region == "separator" and column in self.fixed_width_columns:
            return "break"
        return None

    def on_tree_button_release(self, event: tk.Event):
        region = self.tree.identify_region(event.x, event.y)
        if self.heading_press_column:
            if self.heading_long_press_job:
                self.after_cancel(self.heading_long_press_job)
                self.heading_long_press_job = ""
            if self.heading_reorder_ready and self.heading_dragging:
                self.move_display_column_to_index(self.heading_press_column, self.heading_drop_index_at(event.x))
            else:
                self.sort_by(self.heading_press_column)
            self.heading_press_column = ""
            self.heading_dragging = False
            self.heading_reorder_ready = False
            self.hide_drop_indicator()
            return "break"

        if region != "cell":
            return None
        row_id = self.tree.identify_row(event.y)
        column = self.display_column_name(self.tree.identify_column(event.x))
        if not row_id:
            return None
        if column == "checked":
            self.toggle_checked(row_id)
            return "break"
        if column in {"cwd", "path"}:
            record = self.records.get(row_id)
            if not record:
                return "break"
            raw_path = record.cwd if column == "cwd" else record.path
            path = Path(raw_path) if raw_path else None
            if path and path.exists():
                os.startfile(path if path.is_dir() else path.parent)
            return "break"
        return None

    def move_display_column(self, source_column: str, target_column: str) -> None:
        if not source_column or not target_column or source_column == target_column:
            return
        columns = list(self.current_display_columns())
        if source_column not in columns or target_column not in columns:
            return
        columns.remove(source_column)
        columns.insert(columns.index(target_column), source_column)
        self.tree["displaycolumns"] = columns

    def move_display_column_to_index(self, source_column: str, boundary_index: int) -> None:
        if not source_column:
            return
        columns = list(self.current_display_columns())
        if source_column not in columns:
            return
        source_index = columns.index(source_column)
        boundary_index = max(0, min(boundary_index, len(columns)))
        columns.remove(source_column)
        if source_index < boundary_index:
            boundary_index -= 1
        boundary_index = max(0, min(boundary_index, len(columns)))
        columns.insert(boundary_index, source_column)
        self.tree["displaycolumns"] = columns

    def refresh(self) -> None:
        try:
            all_records = load_records()
        except Exception as exc:
            messagebox.showerror(APP_NAME, tr("load_failed", error=exc))
            return

        query = self.search_var.get().strip()
        visible = self.sort_records([record for record in all_records if self.row_matches(record, query)])
        visible_keys = {record.key for record in visible}
        self.checked_keys &= visible_keys
        self.tree.delete(*self.tree.get_children())
        self.records.clear()
        for record in visible:
            display_cwd = display_path_text(record.cwd)
            display_path = display_path_text(record.path)
            self.records[record.key] = record
            row_index = len(self.records)
            self.tree.insert(
                "",
                "end",
                iid=record.key,
                values=(
                    self.checkbox_text(record.key),
                    record.provider,
                    record.title,
                    record.updated_label,
                    record.size_label,
                    record.status,
                    display_cwd,
                    display_path,
                ),
                tags=("even" if row_index % 2 == 0 else "odd",),
            )
        self.update_status()

    def update_status(self) -> None:
        common_count = len(common_targets()) if self.common_var.get() else 0
        self.status_var.set(tr("status_line", shown=len(self.records), checked=len(self.checked_keys), common=common_count))

    def toggle_checked(self, key: str) -> None:
        if key in self.checked_keys:
            self.checked_keys.remove(key)
        else:
            self.checked_keys.add(key)
        self.refresh()

    def check_all(self) -> None:
        self.checked_keys = set(self.records)
        self.refresh()

    def uncheck_all(self) -> None:
        self.checked_keys.clear()
        self.refresh()

    def checked_records(self) -> list[CleanRecord]:
        return [self.records[key] for key in self.checked_keys if key in self.records]

    def delete_checked(self) -> None:
        records = self.checked_records()
        if not records and not self.common_var.get():
            messagebox.showinfo(APP_NAME, tr("select_to_delete"))
            return

        running_images = [
            name for name in ["Codex.exe", "codex.exe", "Claude.exe", "claude.exe"] if process_running(name)
        ]
        if running_images:
            if not messagebox.askyesno(
                APP_NAME,
                tr("running_apps", apps=", ".join(sorted(set(running_images)))),
            ):
                return
            try:
                stop_processes(sorted(set(running_images)))
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))
                self.refresh()
                return

        titles = "\n".join(f"- [{record.provider}] {record.title}" for record in records[:10])
        if len(records) > 10:
            titles += "\n" + tr("more_items", count=len(records) - 10)
        common_text = tr("delete_common_confirm") if self.common_var.get() else ""
        if not messagebox.askyesno(
            APP_NAME,
            tr("confirm_delete", count=len(records), common_text=common_text, titles=titles),
        ):
            return

        record_deleted, record_errors = delete_selected_records(records)
        common_deleted = 0
        common_errors = []
        if self.common_var.get():
            common_deleted, common_errors = clean_common_traces()

        self.checked_keys.clear()
        self.refresh()

        errors = record_errors + common_errors
        if errors:
            messagebox.showwarning(
                APP_NAME,
                tr("processed_warning", records=record_deleted, common=common_deleted, errors="\n".join(errors[:10])),
            )
        else:
            messagebox.showinfo(
                APP_NAME,
                tr("processed_info", records=record_deleted, common=common_deleted),
            )


def main() -> int:
    try:
        enable_windows_dpi_awareness()
        app = App()
        app.mainloop()
        return 0
    except Exception as exc:
        messagebox.showerror(APP_NAME, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
