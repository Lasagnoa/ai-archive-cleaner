"""Local Claude Code session stores. Never derive deletion targets from transcript cwd."""
import json
import os
from pathlib import Path

import codex_cleanup as cc


def projects(root):
    base = cc.checked(root / "projects", root)
    if base.is_dir():
        for entry in base.iterdir():
            cc.reject_links(entry)
            if entry.is_dir():
                yield entry


def session_ids(root):
    found = {}
    for project in projects(root):
        for entry in project.iterdir():
            sid = entry.stem if entry.suffix == ".jsonl" else entry.name
            if cc.UUID.fullmatch(sid):
                cc.reject_links(entry)
                if entry.is_dir() or entry.suffix == ".jsonl":
                    found.setdefault(sid, set()).add(project)
    return found


def read_history(root):
    path = cc.checked(root / "history.jsonl", root)
    found = {}
    if path.is_file():
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError(f"Unsupported history: {path}")
                    sid = row.get("sessionId")
                    if isinstance(sid, str) and cc.UUID.fullmatch(sid):
                        found[sid] = row
    return found


def cleanup(root, config, desktop_stores, wanted, *, full=False, common=False, retained_cwds=()):
    if not root.exists() and not config.exists() and not any(p.exists() for p in desktop_stores):
        return []
    cc.reject_links(root)
    result = cc.Result()
    sessions = session_ids(root)
    ids = set(wanted)
    kept_paths = {cc.lexical(Path(p)) for p in retained_cwds if p and Path(p).is_absolute()}
    unknown_location = any(not p or not Path(p).is_absolute() for p in retained_cwds)
    if full:
        ids.update(sessions)
        ids.update(read_history(root))
    if any(not cc.UUID.fullmatch(sid) for sid in ids):
        raise ValueError("Invalid Claude session ID")

    def remove(path, boundary=root):
        cc.remove_path(path, boundary)
        if os.path.lexists(path):
            raise OSError(f"Remaining Claude session data: {path}")

    if common:
        for name in ("debug", "cache/changelog.md"):
            result.step(name, lambda: remove(root / name))
    per_session = ("file-history", "image-cache", "uploads", "dev-mods", "session-env", "tasks")
    if full:
        for name in ("file-history", "image-cache", "uploads", "paste-cache", "usage-data", "stats-cache.json"):
            result.step(name, lambda: remove(root / name))
    for sid in ids:
        for name in per_session:
            result.step(name, lambda: remove(root / name / sid))
        for folder in sessions.get(sid, ()):
            result.step(str(folder / sid), lambda: remove(folder / sid))

    def prune_index(data):
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise ValueError("Unsupported Claude sessions index")
        return {**data, "entries": [row for row in data["entries"] if row.get("sessionId") not in ids and not full]}

    for project in projects(root):
        index = project / "sessions-index.json"
        if index.exists():
            result.step(str(index), lambda: cc.rewrite_json(index, root, prune_index))
    for store in desktop_stores:
        for path in cc.files_under(store):
            if path.suffix != ".json":
                continue
            def desktop_entry():
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict) and isinstance(data.get("cliSessionId"), str):
                    if data["cliSessionId"] in ids or (full and cc.UUID.fullmatch(data["cliSessionId"])):
                        remove(path, store)
            result.step(str(path), desktop_entry)
    def config_state(data):
        if not isinstance(data, dict):
            raise ValueError("Unsupported Claude config")
        result = dict(data)
        if isinstance(data.get("projects"), dict):
            kept = {}
            for folder, settings in data["projects"].items():
                if not isinstance(settings, dict):
                    kept[folder] = settings
                elif full or settings.get("lastSessionId") in ids:
                    other = {k: v for k, v in settings.items() if k not in ("lastSessionId", "lastSessionMetrics")
                             and k not in SESSION_METRICS}
                    if other or unknown_location or cc.lexical(Path(folder)) in kept_paths:
                        kept[folder] = other
                else:
                    kept[folder] = settings
            result["projects"] = kept
        return result
    if config.exists():
        result.step(str(config), lambda: cc.rewrite_json(config, config.parent, config_state))
    if result.errors:
        return result.errors
    history = root / "history.jsonl"
    if history.exists():
        if full:
            remove(history)
        elif ids:
            cc.filter_jsonl(history, root, "sessionId", ids)
    for sid in ids:
        for folder in sessions.get(sid, ()):
            result.step(str(folder), lambda: remove(folder / (sid + ".jsonl")))
    for project in projects(root):
        if (project / "sessions-index.json").exists():
            index = project / "sessions-index.json"
            data = json.loads(index.read_text(encoding="utf-8-sig"))
            if data != prune_index(data):
                result.errors.append(f"Remaining Claude index entries: {index}")
            elif data.get("entries") == [] and all(p == index for p in project.iterdir()):
                remove(index)
        if not any(project.iterdir()):
            project.rmdir()
    if ids.intersection(session_ids(root)) or ids.intersection(read_history(root)):
        result.errors.append("Remaining Claude sessions")
    return result.errors


SESSION_METRICS = {"lastCost", "lastDuration", "lastAPIDuration", "lastAPIDurationWithoutRetries",
                   "lastToolDuration", "lastLinesAdded", "lastLinesRemoved", "lastTotalInputTokens",
                   "lastTotalOutputTokens", "lastTotalCacheCreationInputTokens", "lastTotalCacheReadInputTokens",
                   "lastTotalWebSearchRequests", "lastModelUsage", "lastFpsAverage", "lastFpsLow1Pct"}
