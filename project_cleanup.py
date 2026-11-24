"""Remove unused local Codex project registrations without touching project directories."""
import json
from contextlib import closing
from pathlib import Path

import codex_cleanup as cc


class UnusedProjects:
    def __init__(self, ids, roots):
        self.ids = ids
        self.roots = roots

    def clean(self, data):
        result = dict(data)
        for key, value in data.items():
            name = cc.setting_name(key)
            if cc.atom_container(key):
                result[key] = self.clean(value)
            elif name in {"local-projects", "project-appearances"} and isinstance(value, dict):
                result[key] = {k: v for k, v in value.items() if k not in self.ids}
            elif name in {"project-order", "pinned-project-ids"} and isinstance(value, list):
                result[key] = [v for v in value if v not in self.ids]
            elif name == "selected-project" and (value if isinstance(value, str) else
                    value.get("projectId") if isinstance(value, dict) else None) in self.ids:
                del result[key]
            elif name == "new-task-project-by-computer" and isinstance(value, dict):
                result[key] = {k: v for k, v in value.items() if not isinstance(v, str) or v not in self.ids}
            elif name in {"electron-saved-workspace-roots", "active-workspace-roots"} and isinstance(value, list):
                result[key] = [v for v in value if not self.removed_root(v)]
            elif name == "electron-workspace-root-labels" and isinstance(value, dict):
                result[key] = {k: v for k, v in value.items() if not self.removed_root(k)}
            elif name in cc.SIDEBAR_ORDERS or name in cc.SIDEBAR_GROUPS:
                result[key] = cc.cleaned_sidebar(name, value, None, self.ids)
            elif name.startswith("sidebar-project-expanded-v1-") and name.removeprefix("sidebar-project-expanded-v1-").removeprefix("codex:") in self.ids:
                del result[key]
            elif name in cc.PROJECT_EXECUTION_KEYS and isinstance(value, dict):
                result[key] = dict(value)
                for entry in value:
                    try:
                        parts = json.loads(entry)
                    except ValueError:
                        continue
                    if isinstance(parts, list) and len(parts) == 3 and isinstance(parts[2], str) and parts[2] in self.ids:
                        del result[key][entry]
            elif name == "app-server-project-id-by-legacy-project-id-by-host" and isinstance(value, dict):
                result[key] = {host: {k: v for k, v in entries.items() if k not in self.ids
                                      and not (isinstance(v, str) and v in self.ids)}
                               if (host == "local" or host.startswith("local:")) and isinstance(entries, dict) else entries
                               for host, entries in value.items()}
        return result

    def removed_root(self, value):
        return isinstance(value, str) and Path(value).is_absolute() and cc.lexical(Path(value)) in self.roots


def unused_projects(storage, retained, external_paths=()):
    roots = {}
    keep = set()
    located = set()
    workdirs = set(external_paths)
    known_roots = set()
    aliases = []
    thread_ids = {record.record_id for record in retained}

    def remember(pid, path=None):
        if isinstance(pid, str):
            paths = roots.setdefault(pid, set())
            if isinstance(path, str) and Path(path).is_absolute():
                paths.add(cc.lexical(Path(path)))

    def thread(tid, pid, cwd):
        if tid not in thread_ids:
            return
        if isinstance(pid, str) and pid:
            keep.add(pid)
            located.add(tid)
        if isinstance(cwd, str) and Path(cwd).is_absolute():
            workdirs.add(cc.lexical(Path(cwd)))
            located.add(tid)

    for record in retained:
        thread(record.record_id, None, record.cwd)
    for path in cc.databases(storage):
        kind = cc.family(path)
        if kind not in ("state", "catalog"):
            continue
        with closing(cc.connect(path)) as con:
            tables = cc.schema(con)
            if kind == "state":
                if "id" in tables.get("projects", set()):
                    for (pid,) in con.execute("select id from projects"):
                        remember(pid)
                if {"project_id", "path"} <= tables.get("project_roots", set()):
                    for pid, root in con.execute("select project_id,path from project_roots"):
                        remember(pid, root)
            table, id_col = ("threads", "id") if kind == "state" else ("local_thread_catalog", "thread_id")
            cols = tables.get(table, set())
            if id_col in cols:
                fields = [cc.quote(col) if col in cols else "NULL" for col in (id_col, "project_id", "cwd")]
                where = " where host_id='local'" if kind == "catalog" else ""
                for row in con.execute(f"select {','.join(fields)} from {cc.quote(table)}{where}"):
                    thread(*row)
    for name, val in cc.stored_settings(storage):
        if name == "local-projects" and isinstance(val, dict):
            for pid, project in val.items():
                remember(pid)
                for root in project.get("rootPaths", []):
                    remember(pid, root)
        elif name == "thread-project-assignments" and isinstance(val, dict):
            for tid, project in val.items():
                pid = project.get("projectId") if isinstance(project, dict) else project
                thread(tid, pid, None)
        elif name in ("thread-workspace-root-hints", "thread-projectless-output-directories") and isinstance(val, dict):
            for tid, cwd in val.items():
                thread(tid, None, cwd)
        elif name in ("active-workspace-roots", "electron-saved-workspace-roots") and isinstance(val, list):
            known_roots.update(cc.lexical(Path(v)) for v in val if isinstance(v, str) and Path(v).is_absolute())
        elif name == "app-server-project-id-by-legacy-project-id-by-host" and isinstance(val, dict):
            for host, entries in val.items():
                if (host == "local" or host.startswith("local:")) and isinstance(entries, dict):
                    aliases.extend((a, b) for a, b in entries.items() if isinstance(b, str))
    # An unindexed transcript with no usable location could belong to any project.
    if thread_ids - located:
        return UnusedProjects(set(), set())
    def overlaps(paths):
        return any(cc.beneath(w, p) or cc.beneath(p, w) for w in workdirs for p in paths)
    keep.update(pid for pid, paths in roots.items() if overlaps(paths))
    while True:
        linked = {p for pair in aliases if keep.intersection(pair) for p in pair}
        if linked <= keep:
            break
        keep.update(linked)
    remove = (roots.keys() | {p for pair in aliases for p in pair}) - keep
    kept_roots = {path for pid in keep for path in roots.get(pid, ())}
    unused = known_roots | {path for pid in remove for path in roots.get(pid, ())}
    return UnusedProjects(remove, {p for p in unused if p not in kept_roots and not overlaps([p])})


def prune(storage, retained, external_paths=()):
    plan = unused_projects(storage, retained, external_paths)
    if not plan.ids and not plan.roots:
        return []
    errors = cc.Result()
    for path in cc.global_files(storage):
        errors.step(str(path), lambda: cc.rewrite_json(path, storage.home, plan.clean))
        cc.reject_links(path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data != plan.clean(data):
            errors.errors.append(f"Remaining project metadata: {path}")
    for path in cc.databases(storage):
        if cc.family(path) in ("state", "global"):
            for clean in (True, False):
                pending = errors.step(str(path), lambda: cc.database_rows(path, clean=clean, projects=plan))
                errors.errors.extend(pending or [])
    return errors.errors
