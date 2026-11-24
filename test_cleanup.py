"""Destructive tests run exclusively against a freshly created fixture directory."""
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import codex_cleanup as cc
import app


T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"


class CleanupFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cleaner-test-")
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.home = self.user / ".codex"
        self.home.mkdir(parents=True)
        self.storage = cc.Storage(self.home, self.user, self.user / "Roaming", self.user / "Local",
                                  self.user / "Documents/Codex")
        self.desktop = self.storage.roaming / "Codex"
        self.enterContext(patch.object(app, "home", return_value=self.user))
        self.enterContext(patch.object(app, "appdata_local", return_value=self.storage.local))
        self.enterContext(patch.object(app, "appdata_roaming", return_value=self.storage.roaming))
        self.enterContext(patch.object(app, "codex_storage", return_value=self.storage))
        self.enterContext(patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}))
        self.enterContext(patch.object(app, "claude_node_process_ids", return_value=[]))
        self.enterContext(patch.object(app, "stop_processes", side_effect=AssertionError("unexpected live process operation")))

    def tearDown(self):
        assert self.root.resolve().parent == Path(tempfile.gettempdir()).resolve()
        assert self.root.name.startswith("cleaner-test-")
        self.tmp.cleanup()

    def file(self, path, content="fixture"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def db(self, name, sql):
        p = self.home / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(p)) as con:
            con.executescript(sql)
        return p

    def rows(self, path, table):
        with closing(sqlite3.connect(path)) as con:
            return con.execute(f"select * from {cc.quote(table)}").fetchall()


class CleanupTests(CleanupFixture):
    def global_state(self):
        d = {"local-projects": {"p": {"rootPaths": [str(self.root / "actual-repo")]}},
             "selected-project": {"projectId": "p"}, "project-order": ["p"],
             "electron-main-window-bounds": {"width": 1200},
             "electron-persisted-atom-state": {
                 "prompt-history": {"workspace": ["private prompt"]},
                 "composer-prompt-drafts-v2": {T1: "private draft", T2: "keep other draft"},
                 "thread-descriptions-v1": {T1: "private summary", T2: "other summary"},
                 "thread-tab-routes-v1:" + T1: ["private/path"],
                 "composer-model-picker-selection-mode-v1": "keep mode"}}
        self.file(self.home / ".codex-global-state.json", json.dumps(d))
        self.file(self.home / ".codex-global-state.json.bak", json.dumps(d))
        return d

    def state(self, name="state_5.sqlite"):
        return self.db(name, f"""
            CREATE TABLE threads(id TEXT, title TEXT, rollout_path TEXT, cwd TEXT, archived INT, updated_at INT);
            INSERT INTO threads VALUES('{T1}', 'old task', '', 'X:/project', 0, 1);
            INSERT INTO threads VALUES('{T2}', 'other task', '', 'X:/project', 0, 2);
            CREATE TABLE projects(id TEXT); INSERT INTO projects VALUES('project');
            CREATE TABLE project_roots(project_id TEXT); INSERT INTO project_roots VALUES('project');
            CREATE TABLE remote_control_enrollments(secret TEXT); INSERT INTO remote_control_enrollments VALUES('KEEP');
        """)

    def test_full_cleanup_removes_all_known_history_preserves_auth_settings_repositories(self):
        self.global_state()
        protected = [self.file(self.home / name, "KEEP:" + name) for name in
                     ("auth.json", "config.toml", "keybindings.json", "AGENTS.md",
                      "plugins/plugin/settings.json", "skills/personal/SKILL.md", "browser/config.toml",
                      ".sandbox-secrets/token", "automations/scheduled/automation.toml")]
        protected += [self.file(self.desktop / p, "KEEP:" + p) for p in
                      ("Network/Cookies", "Local Storage/leveldb/data", "Local State", "Preferences",
                       "web/Codex/Default/Network/Cookies", "web/Codex/Default/Local Storage/data", "web/Codex/Local State")]
        repo = self.file(self.root / "actual-repo/source.py", "KEEP REPOSITORY")
        protected.append(repo)
        hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        state = self.state()
        old = self.state("sqlite/state_5.sqlite")
        hist = self.db("thread_history_1.sqlite", f"CREATE TABLE thread_items(thread_id TEXT,item_json TEXT); INSERT INTO thread_items VALUES('{T1}','private body');")
        for name in cc.HISTORY_DIRS:
            self.file(self.home / name / "data.json", "private")
        for name in cc.HISTORY_FILES:
            self.file(self.home / name, "private")
        artifact = self.file(self.storage.documents / "2026/task/output.json", "KEEP")
        temp = self.file(self.home / "..codex-global-state.json.tmp-old", "partial private JSON")
        browser_logins = [self.file(self.desktop / p, "KEEP LOGIN") for p in (
            "Partitions/codex-browser-app/Network/Cookies", "web/Codex/codex-browser-app/Login Data",
            "web/Codex/codex-browser-app/Local Storage/data", "Partitions/codex-browser-app/Session Storage/token",
            "web/Codex/Default/IndexedDB/token")]
        browser_files = [self.file(self.desktop / p, "browser history") for p in (
            "Partitions/codex-browser-app/History", "web/Codex/codex-browser-app/Cache/data",
            "web/Codex/browser-sidebar-page-states.json", "Cache/cache", "web/Codex/Default/History")]
        errors = cc.cleanup_all(self.storage)
        self.assertEqual(errors, [])
        self.assertEqual(cc.inspect_remaining(self.storage), [])
        for p in [state, old]:
            self.assertEqual(self.rows(p, "threads"), [])
            self.assertEqual(self.rows(p, "projects"), [])
            self.assertEqual(self.rows(p, "project_roots"), [])
            self.assertEqual(self.rows(p, "remote_control_enrollments"), [("KEEP",)])
        self.assertEqual(self.rows(hist, "thread_items"), [])
        self.assertFalse(temp.exists())
        self.assertEqual(artifact.read_text(), "KEEP")
        self.assertTrue(all(p.read_text() == "KEEP LOGIN" for p in browser_logins))
        self.assertTrue(all(not p.exists() for p in browser_files))
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}, hashes)
        after = json.loads((self.home / ".codex-global-state.json").read_text())
        self.assertNotIn("local-projects", after)
        self.assertEqual(after["electron-main-window-bounds"], {"width": 1200})
        self.assertEqual(after["electron-persisted-atom-state"], {"composer-model-picker-selection-mode-v1": "keep mode"})

    def test_independent_file_failure_does_not_skip_global_metadata(self):
        self.global_state()
        bad = self.file(self.home / "sessions/locked.data")
        original = cc.delete_target
        def fail(path, root, storage):
            if path == self.home / "sessions":
                raise PermissionError("fixture locked")
            return original(path, root, storage)
        with patch.object(cc, "delete_target", side_effect=fail):
            errors = cc.cleanup_all(self.storage)
        self.assertTrue(errors)
        self.assertTrue(bad.exists())
        self.assertNotIn("local-projects", json.loads((self.home / ".codex-global-state.json").read_text()))

    @unittest.skipUnless(os.name == "nt", "Windows readonly semantics")
    def test_readonly_git_files_removed_without_acl_changes(self):
        p = self.file(self.home / "sessions/task/.git/objects/pack/test.idx")
        p.chmod(stat.S_IREAD)
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertFalse(p.exists())

    def test_unknown_nonempty_database_is_reported_and_preserved(self):
        p = self.db("future_history_9.sqlite", "CREATE TABLE secrets(value TEXT); INSERT INTO secrets VALUES('private');")
        errors = cc.cleanup_all(self.storage)
        self.assertTrue(any("Unsupported database" in e for e in errors))
        self.assertEqual(self.rows(p, "secrets"), [("private",)])

    def test_unknown_table_is_reported_while_known_tables_cleaned(self):
        p = self.state()
        with closing(sqlite3.connect(p)) as con:
            con.executescript("CREATE TABLE new_history(value TEXT); INSERT INTO new_history VALUES('private');")
        self.assertTrue(any("Unsupported table" in e for e in cc.cleanup_all(self.storage)))
        self.assertEqual(self.rows(p, "threads"), [])
        self.assertEqual(self.rows(p, "new_history"), [("private",)])

    def test_read_receipts_follow_selected_thread_then_full_cleanup(self):
        p = self.db("state_5.sqlite", f"""
            CREATE TABLE thread_read_receipts(thread_id TEXT PRIMARY KEY, first_unread_turn TEXT,
                                              revision TEXT NOT NULL, last_published_turn TEXT);
            INSERT INTO thread_read_receipts VALUES ('{T1}', NULL, '1', NULL), ('{T2}', NULL, '2', NULL);
        """)
        self.assertEqual(cc.delete_selected(self.storage, {T1}, []), [])
        self.assertEqual([r[0] for r in self.rows(p, "thread_read_receipts")], [T2])
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertEqual(self.rows(p, "thread_read_receipts"), [])

    def test_changed_read_receipts_schema_is_preserved(self):
        p = self.db("state_5.sqlite", "CREATE TABLE thread_read_receipts(thread_id TEXT, extra TEXT); "
                    "INSERT INTO thread_read_receipts VALUES ('task', 'KEEP');")
        self.assertTrue(any("Unsupported table schema" in e for e in cc.cleanup_all(self.storage)))
        self.assertEqual(self.rows(p, "thread_read_receipts"), [("task", "KEEP")])

    def test_documents_entries_are_not_selectable_or_deleted(self):
        selected = self.file(self.storage.documents / "task/output.json", "private")
        other = self.file(self.storage.documents / "other/output.json", "KEEP")
        external = self.file(self.root / "outside/service.py", "KEEP")
        with patch.object(app, "codex_storage", return_value=self.storage), \
             patch.object(app, "load_codex_records", return_value=[]):
            self.assertEqual(app.load_records(), [])
            rec = app.CleanRecord(app.PROVIDER_CODEX_DOCS, "task", "task", str(selected.parent), 0)
            count, errors = app.delete_selected_records([rec])
            self.assertEqual(count, 0)
            self.assertTrue(errors)
            bad = app.CleanRecord(app.PROVIDER_CODEX_DOCS, "external", "external", str(external), 0)
            count, errors = app.delete_selected_records([bad])
            self.assertEqual(count, 0)
            self.assertTrue(errors)
        self.assertEqual(selected.read_text(), "private")
        self.assertEqual(other.read_text(), "KEEP")
        self.assertEqual(external.read_text(), "KEEP")

    def test_empty_documents_folder_is_preserved(self):
        self.storage.documents.mkdir(parents=True)
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertTrue(self.storage.documents.exists())

    def test_documents_link_and_target_are_preserved(self):
        outside = self.file(self.root / "outside/keep.txt", "KEEP")
        self.storage.documents.mkdir(parents=True)
        link = self.storage.documents / "linked"
        try:
            link.symlink_to(outside.parent, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Cannot create symlink: {exc}")
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertEqual(outside.read_text(), "KEEP")
        self.assertTrue(link.is_symlink())

    def test_external_configured_database_is_preserved(self):
        self.storage.extra_db = self.root / "external-db"
        self.storage.extra_db.mkdir()
        p = self.storage.extra_db / "state_5.sqlite"
        with closing(sqlite3.connect(p)) as con:
            con.executescript("CREATE TABLE threads(id TEXT); INSERT INTO threads VALUES ('KEEP');")
        self.assertTrue(any("Custom database location preserved" in e for e in cc.cleanup_all(self.storage)))
        self.assertEqual(self.rows(p, "threads"), [("KEEP",)])

    def test_consolidation_progress_does_not_block_selected_or_full_cleanup(self):
        p = self.db("memories_1.sqlite", f"""
            CREATE TABLE consolidation_progress (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                max_thread_count INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO consolidation_progress VALUES (1, 7);
            CREATE TABLE jobs (job_key TEXT);
            INSERT INTO jobs VALUES ('{T1}');
        """)
        rollout = self.file(self.home / "sessions" / f"rollout-{T1}.jsonl", "{}\n")
        self.assertEqual(cc.delete_selected(self.storage, {T1}, [str(rollout)]), [])
        self.assertFalse(rollout.exists())
        self.assertEqual(self.rows(p, "jobs"), [])
        self.assertEqual(self.rows(p, "consolidation_progress"), [(1, 7)])
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertEqual(self.rows(p, "consolidation_progress"), [(1, 0)])

    def test_changed_consolidation_progress_schema_is_preserved_and_reported(self):
        p = self.db("memories_1.sqlite", """
            CREATE TABLE consolidation_progress (singleton INTEGER PRIMARY KEY, max_thread_count INTEGER, future_data TEXT);
            INSERT INTO consolidation_progress VALUES (1, 7, 'KEEP');
        """)
        self.assertTrue(any("Unsupported table" in e for e in cc.cleanup_all(self.storage)))
        self.assertEqual(self.rows(p, "consolidation_progress"), [(1, 7, "KEEP")])

    def test_full_cleanup_erases_cached_titles_from_all_hosts_but_not_configuration(self):
        cat = self.db("sqlite/codex-dev.db", f"""
            CREATE TABLE local_thread_catalog(host_id TEXT,thread_id TEXT);
            INSERT INTO local_thread_catalog VALUES('local','{T1}'),('remote','{T1}'),('chatgpt:account','cloud-task');
            CREATE TABLE automations(prompt TEXT); INSERT INTO automations VALUES('KEEP CONFIG');
            CREATE TABLE local_thread_catalog_sync_state(host_id TEXT); INSERT INTO local_thread_catalog_sync_state VALUES('local'),('remote');
        """)
        summary = self.db("sqlite/codex-thread-summaries-dev.db", f"""
            CREATE TABLE thread_turn_summaries(host_key TEXT,thread_id TEXT,summary TEXT);
            INSERT INTO thread_turn_summaries VALUES('local:machine','{T1}','old'),('remote:machine','{T1}','keep');
        """)
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertEqual(self.rows(cat, "local_thread_catalog"), [])
        self.assertEqual(self.rows(cat, "automations"), [("KEEP CONFIG",)])
        self.assertEqual(self.rows(summary, "thread_turn_summaries"), [])

    def test_selected_catalog_and_summary_are_scoped_to_local_host(self):
        cat = self.db("sqlite/codex-dev.db", f"CREATE TABLE local_thread_catalog(host_id TEXT,thread_id TEXT); INSERT INTO local_thread_catalog VALUES('local','{T1}'),('remote','{T1}');")
        summary = self.db("sqlite/codex-thread-summaries-dev.db", f"CREATE TABLE thread_turn_summaries(host_key TEXT,thread_id TEXT); INSERT INTO thread_turn_summaries VALUES('local:machine','{T1}'),('remote:machine','{T1}');")
        self.assertEqual(cc.delete_selected(self.storage, {T1}, []), [])
        self.assertEqual(self.rows(cat, "local_thread_catalog"), [("remote", T1)])
        self.assertEqual(self.rows(summary, "thread_turn_summaries"), [("remote:machine", T1)])

    def test_selected_deletes_auxiliary_data_not_other_tasks_or_projects(self):
        self.global_state()
        state = self.state()
        schemas = [("goals_1.sqlite", "thread_goals", "thread_id"), ("memories_1.sqlite", "stage1_outputs", "thread_id"),
                   ("queue_1.sqlite", "queued_items", "thread_id"), ("thread_history_1.sqlite", "thread_items", "thread_id")]
        for name, table, column in schemas:
            self.db(name, f"CREATE TABLE {table}({column} TEXT); INSERT INTO {table} VALUES('{T1}'),('{T2}');")
        rollout = self.file(self.home / "sessions" / (T1 + ".jsonl"), "{}\n")
        self.file(self.home / "session_index.jsonl", json.dumps({"id": T1}) + "\n" + json.dumps({"id": T2}) + "\n")
        artifact = self.file(self.home / "visualizations/2026/09" / T1 / "result.json")
        other = self.file(self.home / "visualizations/2026/09" / T2 / "result.json")
        self.assertEqual(cc.delete_selected(self.storage, {T1}, [str(rollout)]), [])
        self.assertEqual([r[0] for r in self.rows(state, "threads")], [T2])
        self.assertEqual(self.rows(state, "projects"), [("project",)])
        for name, table, _ in schemas:
            self.assertEqual(self.rows(self.home / name, table), [(T2,)])
        self.assertFalse(rollout.exists())
        self.assertFalse(artifact.exists())
        self.assertTrue(other.exists())
        data = json.loads((self.home / ".codex-global-state.json.bak").read_text())
        self.assertIn("local-projects", data)
        self.assertEqual(data["electron-persisted-atom-state"]["thread-descriptions-v1"], {T2: "other summary"})

    def test_selected_removes_duplicate_transcripts_and_owned_snapshots(self):
        first = self.file(self.home / "sessions/2026" / f"rollout-{T1}.jsonl")
        duplicate = self.file(self.home / "archived_sessions" / f"rollout-{T1}.jsonl")
        other = self.file(self.home / "sessions/2026" / f"rollout-{T2}.jsonl")
        snapshot = self.file(self.home / "shell_snapshots" / f"{T1}.sh")
        self.assertEqual(cc.delete_selected(self.storage, {T1}, [str(first)]), [])
        self.assertFalse(first.exists())
        self.assertFalse(duplicate.exists())
        self.assertFalse(snapshot.exists())
        self.assertTrue(other.exists())

    def test_projectless_output_is_deleted_for_selected_chat(self):
        output = self.storage.documents / "2026-11-10/example/outputs"
        artifact = self.file(output / "report.txt")
        scratch = self.file(output.parent / "work/draft.txt")
        other = self.file(self.storage.documents / "2026-11-10/other/outputs/keep.txt", "KEEP")
        self.file(self.home / ".codex-global-state.json", json.dumps({
            "thread-projectless-output-directories": {T1: str(output), T2: str(other.parent)}
        }))
        self.assertEqual(cc.delete_selected(self.storage, {T1}, []), [])
        self.assertFalse(artifact.exists())
        self.assertFalse(scratch.exists())
        self.assertEqual(other.read_text(), "KEEP")

    def test_projectless_project_and_shared_paths_are_preserved(self):
        output = self.storage.documents / "2026-11-10/example/outputs"
        artifact = self.file(output / "report.txt", "KEEP")
        state = self.home / ".codex-global-state.json"
        self.file(state, json.dumps({"thread-projectless-output-directories": {T1: str(output), T2: str(output)}}))
        self.assertEqual(cc.delete_selected(self.storage, {T1}, []), [])
        self.assertEqual(artifact.read_text(), "KEEP")
        self.file(state, json.dumps({"thread-projectless-output-directories": {T1: str(output)},
                                     "local-projects": {"p": {"rootPaths": [str(output.parent)]}}}))
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertEqual(artifact.read_text(), "KEEP")
        self.assertEqual(json.loads(state.read_text()), {})

    def test_selected_deletes_git_in_dedicated_chat_folder(self):
        output = self.storage.documents / "2026-11-10/example/outputs"
        artifact = self.file(output / "report.txt", "KEEP")
        self.file(output.parent / ".git/config", "KEEP")
        self.file(self.home / ".codex-global-state.json", json.dumps({
            "thread-projectless-output-directories": {T1: str(output)}
        }))
        self.assertEqual(cc.delete_selected(self.storage, {T1}, []), [])
        self.assertFalse(artifact.parent.parent.exists())

    def test_full_cleanup_removes_mapped_projectless_output(self):
        output = self.storage.documents / "2026-11-10/example/outputs"
        artifact = self.file(output / "report.txt")
        self.file(self.home / ".codex-global-state.json", json.dumps({
            "thread-projectless-output-directories": {T1: str(output)}
        }))
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertFalse(artifact.exists())

    def test_selected_reports_owned_item_still_present(self):
        owned = self.file(self.home / "visualizations" / T1 / "image.png")
        original = cc.delete_target
        def leave_artifact(path, root, storage):
            if path == owned.parent:
                return
            return original(path, root, storage)
        with patch.object(cc, "delete_target", side_effect=leave_artifact):
            errors = cc.delete_selected(self.storage, {T1}, [])
        self.assertTrue(any("Remaining owned item" in e for e in errors))
        self.assertTrue(owned.exists())

    def test_selected_database_error_preserves_rollout_for_retry(self):
        self.state()
        p = self.file(self.home / "sessions/task.jsonl")
        with patch.object(cc, "database_rows", side_effect=sqlite3.OperationalError("fixture busy")):
            self.assertTrue(cc.delete_selected(self.storage, {T1}, [str(p)]))
        self.assertTrue(p.exists())

    def test_selected_invalid_path_does_not_touch_database(self):
        state = self.state()
        p = self.file(self.root / "unrelated.jsonl")
        self.assertTrue(cc.delete_selected(self.storage, {T1}, [str(p)]))
        self.assertEqual(len(self.rows(state, "threads")), 2)
        self.assertTrue(p.exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended paths only")
    def test_selected_extended_rollout_path_is_listed_once_and_deleted(self):
        p = self.file(self.home / "sessions" / f"rollout-{T1}.jsonl", "{}\n")
        extended = "\\\\?\\" + str(p)
        state = self.db("state_5.sqlite", "CREATE TABLE threads(id TEXT, title TEXT, rollout_path TEXT, archived INT, updated_at INT);")
        with closing(sqlite3.connect(state)) as con:
            con.execute("INSERT INTO threads VALUES (?, ?, ?, ?, ?)", (T1, "test", extended, 0, 1))
            con.commit()

        records = cc.list_threads(self.storage)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][2], extended)
        outside = self.file(self.root / "unrelated.jsonl")
        outside_extended = "\\\\?\\" + str(outside)
        self.assertTrue(any("Outside transcript boundary" in error for error in
                            cc.delete_selected(self.storage, {T1}, [outside_extended])))
        self.assertTrue(outside.exists())
        self.assertEqual(len(self.rows(state, "threads")), 1)
        self.assertEqual(cc.delete_selected(self.storage, {T1}, [extended]), [])
        self.assertFalse(p.exists())
        self.assertEqual(self.rows(state, "threads"), [])

    def test_common_cleanup_does_not_log_out_browser_or_remove_history(self):
        p = self.file(self.desktop / "Partitions/codex-browser-app/Network/Cookies", "KEEP")
        state = self.state()
        cache = self.file(self.desktop / "Cache/private-cache")
        self.assertEqual(cc.cleanup_all(self.storage, logs_only=True), [])
        self.assertTrue(p.exists())
        self.assertEqual(len(self.rows(state, "threads")), 2)
        self.assertFalse(cache.exists())

    def test_protected_ancestor_and_descendant_rejected(self):
        p = self.file(self.home / "plugins/plugin/auth.json", "KEEP")
        for target in (self.home, self.home / "plugins", p):
            with self.assertRaises(ValueError):
                cc.delete_target(target, self.user, self.storage)
        self.assertTrue(p.exists())

    def test_unlink_file_symlink_without_touching_target(self):
        target = self.file(self.root / "secret.txt", "KEEP")
        alias = self.home / "sessions/link"
        alias.parent.mkdir(parents=True)
        try:
            alias.symlink_to(target)
        except OSError:
            self.skipTest("File symlinks unavailable")
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertFalse(alias.exists())
        self.assertEqual(target.read_text(), "KEEP")

    def test_new_database_version_and_old_folder_are_discovered(self):
        self.state("state_99.sqlite")
        self.state("sqlite/state_5.sqlite")
        self.assertEqual(len(cc.list_threads(self.storage)), 2)
        self.assertEqual(cc.cleanup_all(self.storage), [])

    def test_unindexed_rollout_is_listed(self):
        p = self.file(self.home / "archived_sessions/2026" / f"rollout-{T1}.jsonl", "{}\n")
        rows = cc.list_threads(self.storage)
        self.assertEqual(rows[0][0], T1)
        self.assertEqual(rows[0][2], str(p))

    def test_catalog_only_ghost_is_selectable_and_deletable(self):
        p = self.db("sqlite/codex-dev.db", f"CREATE TABLE local_thread_catalog(host_id TEXT,thread_id TEXT,display_title TEXT); INSERT INTO local_thread_catalog VALUES('local','{T1}','ghost title');")
        records = cc.list_threads(self.storage)
        self.assertEqual(records[0][:3], (T1, "ghost title", ""))
        self.assertEqual(cc.delete_selected(self.storage, {T1}, [""]), [])
        self.assertEqual(self.rows(p, "local_thread_catalog"), [])

    def test_metadata_only_size_does_not_scan_working_directory(self):
        record = app.CleanRecord(app.PROVIDER_CODEX, T1, "ghost", "", 0)
        with patch.object(app, "folder_size", side_effect=AssertionError("must not scan cwd")):
            self.assertEqual(record.size_label, app.tr("none"))

    def test_catalog_and_unindexed_rollout_are_merged(self):
        self.db("sqlite/codex-dev.db", f"CREATE TABLE local_thread_catalog(host_id TEXT,thread_id TEXT,display_title TEXT); INSERT INTO local_thread_catalog VALUES('local','{T1}','display title');")
        p = self.file(self.home / "sessions" / f"rollout-{T1}.jsonl", "{}\n")
        records = cc.list_threads(self.storage)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][:3], (T1, "display title", str(p)))

    def test_catalog_title_preferred_to_history_fallback(self):
        self.db("thread_history_1.sqlite", f"CREATE TABLE thread_items(thread_id TEXT); INSERT INTO thread_items VALUES('{T1}');")
        self.db("sqlite/codex-dev.db", f"CREATE TABLE local_thread_catalog(host_id TEXT,thread_id TEXT,display_title TEXT); INSERT INTO local_thread_catalog VALUES('local','{T1}','display title');")
        self.assertEqual(cc.list_threads(self.storage)[0][1], "display title")

    def test_invalid_index_preserves_transcript_for_retry(self):
        self.state()
        p = self.file(self.home / "sessions" / f"rollout-{T1}.jsonl", "{}\n")
        self.file(self.home / "session_index.jsonl", "invalid JSON")
        self.assertTrue(cc.delete_selected(self.storage, {T1}, [str(p)]))
        self.assertTrue(p.exists())

    def test_configured_log_directory_keeps_non_log_files(self):
        self.storage.extra_log = self.root / "mixed-folder"
        p = self.file(self.storage.extra_log / "important.txt", "KEEP")
        log = self.file(self.storage.extra_log / "codex.log")
        self.assertTrue(any("Custom log location preserved" in e for e in cc.cleanup_all(self.storage, logs_only=True)))
        self.assertTrue(p.exists())
        self.assertTrue(log.exists())

    def test_process_probe_failure_is_not_assumed_stopped(self):
        with patch.object(app, "run_hidden", side_effect=OSError("probe unavailable")):
            with self.assertRaises(OSError):
                app.process_running("codex.exe")

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_junction_unlinked_and_outside_target_untouched(self):
        import subprocess
        target = self.file(self.root / "outside/keep.txt", "KEEP")
        link = self.home / "sessions"
        # Native PowerShell creates only this isolated fixture junction.
        command = "New-Item -ItemType Junction -Path '" + str(link).replace("'", "''") + "' -Target '" + str(target.parent).replace("'", "''") + "' | Out-Null"
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertFalse(link.exists())
        self.assertEqual(target.read_text(), "KEEP")

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_nested_junction_is_unlinked_and_cannot_be_traversed(self):
        import subprocess
        target = self.file(self.root / "outside/keep.txt", "KEEP")
        link = self.home / "sessions/task/link"
        link.parent.mkdir(parents=True)
        command = "New-Item -ItemType Junction -Path '" + str(link).replace("'", "''") + "' -Target '" + str(target.parent).replace("'", "''") + "' | Out-Null"
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        with self.assertRaises(ValueError):
            cc.remove_path(link / "keep.txt", self.home)
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertEqual(target.read_text(), "KEEP")
        self.assertFalse(link.exists())

    def test_corrupt_global_json_reports_error_and_preserves_settings(self):
        p = self.file(self.home / ".codex-global-state.json", '{"settings":')
        self.assertTrue(cc.cleanup_all(self.storage))
        self.assertEqual(p.read_text(), '{"settings":')

    def test_extra_db_root_preserved(self):
        self.storage.extra_db = self.home / "custom-sql"
        p = self.state("custom-sql/state_8.sqlite")
        self.assertTrue(any("Custom database location preserved" in e for e in cc.cleanup_all(self.storage)))
        self.assertEqual(len(self.rows(p, "threads")), 2)

    def test_queue_memory_goal_wal_is_truncated(self):
        p = self.db("goals_1.sqlite", f"PRAGMA journal_mode=WAL; CREATE TABLE thread_goals(thread_id TEXT, objective TEXT); INSERT INTO thread_goals VALUES('{T1}','PRIVATE_SENTINEL_XYZ');")
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertNotIn(b"PRIVATE_SENTINEL_XYZ", p.read_bytes())
        wal = Path(str(p) + "-wal")
        self.assertFalse(wal.exists() and wal.stat().st_size)

    def test_nonempty_manual_review_data_prevents_success(self):
        p = self.file(self.home / "cleanup_backups/sensitive.backup")
        self.assertTrue(any("Manual review" in e for e in cc.cleanup_all(self.storage)))
        self.assertTrue(p.exists())

    def test_app_partial_failure_is_not_counted_as_completed(self):
        rec = app.CleanRecord(app.PROVIDER_CODEX, T1, "fixture", "", 0)
        with patch.object(app, "codex_storage", return_value=self.storage), \
             patch.object(cc, "delete_selected", return_value=["partial failure"]):
            count, errors = app.delete_selected_records([rec])
        self.assertEqual(count, 0)
        self.assertTrue(errors)

    def test_claude_full_cleanup_preserves_history_and_config(self):
        history = self.file(self.user / ".claude/history.jsonl", '{"sessionId":"orphan","display":"private"}\n')
        cfg = self.file(self.user / ".claude.json", '{"oauthAccount":{"keep":"KEEP"}}')
        with patch.object(app, "home", return_value=self.user), patch.object(app, "codex_privacy_data_present", return_value=False), \
             patch.object(app, "claude_desktop_code_sessions_paths", return_value=[]):
            count, errors = app.clean_privacy_traces()
        self.assertEqual((count, errors), (0, []))
        self.assertIn('orphan', history.read_text())
        self.assertEqual(json.loads(cfg.read_text()), {"oauthAccount": {"keep": "KEEP"}})


class DesktopGlobalStateTests(CleanupFixture):
    owner = "electron-owner-atoms:owner-a"
    selected = "electron-owner-value:selected-project:owner-a"
    outputs = "electron-owner-value:thread-projectless-output-directories:owner-a"

    def setUp(self):
        super().setUp()
        self.db_path = self.db(cc.GLOBAL_DB, """
            PRAGMA user_version=1;
            CREATE TABLE settings(scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                                  PRIMARY KEY(scope,key)) WITHOUT ROWID;
        """)
        self.enterContext(patch.object(app, "codex_storage", return_value=self.storage))

    def settings(self, entries):
        with closing(sqlite3.connect(self.db_path)) as con:
            con.executemany("insert into settings values(?,?,?)",
                            [(s, k, json.dumps(v)) for s, k, v in entries])
            con.commit()

    def saved(self):
        return {(s, k): json.loads(v) for s, k, v in self.rows(self.db_path, "settings")}

    def test_full_clears_project_list_and_new_chat_choice_in_every_store(self):
        project = {"type": "local", "projectId": "old-project"}
        order = ["codex:project:old-project", "space:space:keep:me"]
        by_computer = {"computer": "old-project", "another": None}
        project_pref = json.dumps(["account", "user", "old-project"])
        default_pref = json.dumps(["account", "user", None])
        atoms = {"new-task-project-by-computer": by_computer, "unified-sidebar-project-order-v1": order,
                 "sidebar-custom-sections-v3": {"account": {"sections": [{"name": "Work", "itemKeys": order}]}},
                 "sidebar-customization-snapshots-v2": {"account": {"order": order, "pinOverrides": dict.fromkeys(order, True)}},
                 "new-task-execution-by-account-project": {project_pref: 1, default_pref: 2},
                 "sidebar-width": 320}
        data = {"local-projects": {"old-project": project}, self.selected: project, self.owner: atoms,
                "electron-owner-value:open-in-target-preferences:owner-a": {"global": "keep"}}
        files = [self.file(self.home / n, json.dumps(data)) for n in
                 (".codex-global-state.json", ".codex-global-state.json.bak")]
        self.settings([("global", self.selected, project), ("global", "local-projects", data["local-projects"]),
                       ("global", "project-order", ["old-project"]), ("global", self.owner, {}),
                       ("global", "electron-automations-installation-id", "KEEP"),
                       ("atom", "prompt-history", {"workspace": ["draft"]}),
                       ("electron-owner-atoms:second", "new-task-project-by-computer", by_computer),
                       ("future-scope", "selected-project", "KEEP"),
                       *((self.owner, k, v) for k, v in atoms.items())])
        self.assertTrue(cc.inspect_remaining(self.storage))
        self.assertEqual(app.clean_privacy_traces(), (1, []))
        remaining_atoms = {"unified-sidebar-project-order-v1": order[1:],
                           "sidebar-custom-sections-v3": {"account": {"sections": [{"name": "Work", "itemKeys": order[1:]}]}},
                           "sidebar-customization-snapshots-v2": {"account": {"order": order[1:], "pinOverrides": {order[1]: True}}},
                           "new-task-execution-by-account-project": {default_pref: 2}, "sidebar-width": 320}
        for path in files:
            self.assertEqual(json.loads(path.read_text()), {
                self.owner: remaining_atoms,
                "electron-owner-value:open-in-target-preferences:owner-a": {"global": "keep"}})
        self.assertEqual(self.saved(), {("global", self.owner): {}, ("future-scope", "selected-project"): "KEEP",
                                        ("global", "electron-automations-installation-id"): "KEEP",
                                        **{(self.owner, k): v for k, v in remaining_atoms.items()}})
        self.assertEqual(cc.inspect_remaining(self.storage), [])
        self.assertEqual(app.clean_privacy_traces(), (0, []))

    def test_selected_and_common_preserve_projects_and_other_chat(self):
        output = self.file(self.storage.documents / "2026-11-24/task/outputs/report")
        self.settings([("global", self.outputs, {T1: str(output.parent)}), ("global", self.selected, "project"),
                       (self.owner, "thread-descriptions-v1", {T1: "first", T2: "other"}),
                       (self.owner, "thread-client-id-v1:local%3A" + T1, "client"),
                       (self.owner, "unified-sidebar-pinned-order-v1", ["codex:thread:local:" + T1, "codex:project:p"]),
                       (self.owner, "new-task-project-by-computer", {"local": "p"})])
        before = self.saved()
        self.assertEqual(cc.cleanup_all(self.storage, logs_only=True), [])
        self.assertEqual(self.saved(), before)
        with patch.object(cc, "delete_target", side_effect=PermissionError("locked output")):
            self.assertTrue(cc.delete_selected(self.storage, {T1}, []))
        self.assertEqual(self.saved(), before)
        self.assertEqual(cc.delete_selected(self.storage, {T1}, []), [])
        self.assertFalse(output.exists())
        self.assertEqual(self.saved(), {("global", self.outputs): {}, ("global", self.selected): "project",
            (self.owner, "thread-descriptions-v1"): {T2: "other"},
            (self.owner, "unified-sidebar-pinned-order-v1"): ["codex:project:p"],
            (self.owner, "new-task-project-by-computer"): {"local": "p"}})

    def test_full_deletes_embedded_git_and_preserves_database_registered_projects(self):
        base = self.storage.documents / "2026-11-24"
        git = self.file(base / "has-repo/src/.git/config", "KEEP")
        project = self.file(base / "registered/source.txt", "KEEP")
        removable = self.file(base / "ordinary/outputs/report")
        self.settings([("global", self.outputs, {T1: str(base / "has-repo/outputs"),
                                                 T2: str(project.parent), "third": str(removable.parent)})])
        state = self.db("state_5.sqlite", "create table project_roots(path text)")
        with closing(sqlite3.connect(state)) as con:
            con.execute("insert into project_roots values(?)", (str(project.parent),))
            con.commit()
        self.assertEqual(app.clean_privacy_traces(), (1, []))
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.rows(state, "project_roots"), [])
        self.assertFalse(git.exists())
        self.assertEqual(project.read_text(), "KEEP")
        self.assertFalse(removable.exists())

    def test_conflicting_stores_preserve_both_mappings_and_folders_for_retry(self):
        docs = self.storage.documents / "2026-11-24"
        a, b = [self.file(docs / task / "outputs/file") for task in ("first", "second")]
        self.settings([("global", self.outputs, {T1: str(a.parent)})])
        backup = self.file(self.home / ".codex-global-state.json.bak",
                           json.dumps({self.outputs: {T1: str(b.parent)}}))
        errors = cc.cleanup_all(self.storage)
        self.assertTrue(any("Conflicting projectless" in e for e in errors), errors)
        self.assertTrue(a.exists() and b.exists())
        self.assertIn(T1, self.saved()["global", self.outputs])
        self.assertIn(T1, json.loads(backup.read_text())[self.outputs])

    def test_folder_and_outputs_in_different_stores_identify_same_chat(self):
        output = self.file(self.storage.documents / "2026-11-24/日本語 チャット/outputs/report")
        self.settings([("global", self.outputs, {T1: str(output.parent)})])
        self.file(self.home / ".codex-global-state.json", json.dumps({self.outputs: {T1: str(output.parent.parent)}}))
        self.assertEqual(app.clean_privacy_traces(), (1, []))
        self.assertFalse(output.parent.parent.exists())

    def test_future_version_or_changed_schema_is_preserved(self):
        self.settings([("global", self.selected, "KEEP")])
        for sql in ["pragma user_version=2", "pragma user_version=1; alter table settings add column new_data"]:
            self.db(cc.GLOBAL_DB, sql)
            errors = cc.cleanup_all(self.storage)
            self.assertTrue(any("Unsupported global state schema" in e for e in errors), errors)
            self.assertEqual(self.rows(self.db_path, "settings")[0][2], '"KEEP"')

    def test_all_chats_use_full_cleanup_once(self):
        gui = Mock()
        gui.checked_records.return_value = [app.CleanRecord(app.PROVIDER_CODEX, T1, "task", "", 0)]
        self.settings([("global", self.selected, "project")])
        with patch.object(app.messagebox, "askyesno", return_value=True), patch.object(app.messagebox, "showinfo"), \
             patch.object(app, "process_running", return_value=False), patch.object(app, "codex_desktop_process_ids", return_value=[]), \
             patch.object(app, "delete_selected_records") as selected, patch.object(app, "clean_common_traces") as common:
            app.App.delete_checked(gui)
        selected.assert_not_called()
        common.assert_not_called()
        gui.show_cleanup_errors.assert_not_called()
        self.assertEqual(self.saved(), {})

    def test_active_turns_removed_by_selected_session_id(self):
        catalog = self.db("sqlite/codex.db", f"""
            create table active_chat_turns(profile TEXT NOT NULL, account_id TEXT NOT NULL, user_id TEXT NOT NULL,
                thread_id TEXT NOT NULL, launch_id TEXT NOT NULL, observed_at_ms INTEGER NOT NULL,
                primary key(profile, account_id, user_id, thread_id)) WITHOUT ROWID;
            insert into active_chat_turns values('profile','account','user','{T1}','launch',0);
        """)
        self.assertEqual(cc.delete_selected(self.storage, {T1}, []), [])
        self.assertEqual(self.rows(catalog, "active_chat_turns"), [])
        self.assertEqual(app.clean_privacy_traces(), (0, []))
        self.assertEqual(self.rows(catalog, "active_chat_turns"), [])


class AutomaticCleanupTests(CleanupFixture):
    def test_chat_created_during_confirmation_keeps_its_files_and_project(self):
        self.file(self.home / "sessions" / (T1 + ".jsonl"))
        gui = Mock()
        gui.checked_records.return_value = app.load_records()
        new = self.home / "sessions" / (T2 + ".jsonl")
        def confirm(*args):
            self.file(new)
            return True
        with patch.object(app.messagebox, "askyesno", side_effect=confirm), patch.object(app.messagebox, "showinfo"), \
             patch.object(app, "process_running", return_value=False), patch.object(app, "codex_desktop_process_ids", return_value=[]):
            app.App.delete_checked(gui)
        gui.show_cleanup_errors.assert_not_called()
        self.assertTrue(new.exists())
        self.assertFalse((new.parent / (T1 + ".jsonl")).exists())

    def test_other_transcript_and_parent_repository_are_preserved(self):
        other = self.file(self.home / "sessions" / (T2 + ".jsonl"), "KEEP")
        self.assertTrue(cc.delete_selected(self.storage, {T1}, [str(other)]))
        self.assertEqual(other.read_text(), "KEEP")
        self.file(self.storage.documents / ".git/config")
        inside = self.file(self.storage.documents / "2026-11-24/task/outputs/result", "KEEP")
        self.file(self.home / ".codex-global-state.json", json.dumps({"thread-projectless-output-directories":{T1:str(inside.parent)}}))
        self.assertEqual(cc.delete_selected(self.storage,{T1},[]),[])
        self.assertEqual(inside.read_text(),"KEEP")

    def test_partial_always_cleans_logs_and_only_unused_registrations(self):
        a, b = [str(self.root / n) for n in ("remove", "keep")]
        state = self.db("state_5.sqlite", """
            create table projects(id text primary key);
            create table project_roots(project_id text,path text);
            create table threads(id text,project_id text,cwd text,title text);
            insert into projects values('a'),('b'),('shared');
        """)
        with closing(sqlite3.connect(state)) as con:
            con.executemany("insert into project_roots values(?,?)", [("a",a),("b",b)])
            con.executemany("insert into threads values(?,?,?,?)", [(T1,"a",a,"same"),(T2,"b",b,"same")])
            con.commit()
        local = self.file(self.home / ".codex-global-state.json", json.dumps({
            "local-projects": {"a":{"rootPaths":[a]},"b":{"rootPaths":[b]},"shared":{"rootPaths":[b]}},
            "project-order":["a","b","shared"], "active-workspace-roots":[a,b],
            "electron-owner-value:selected-project:owner":{"type":"local","projectId":"a"},
            "electron-owner-atoms:owner":{"new-task-project-by-computer":{"local":"a","other":"b"}}}))
        outside = self.file(Path(a) / "src.py", "KEEP")
        log = self.file(self.home / "log/log.txt")
        current = app.load_records()
        selected = [r for r in current if r.record_id == T1]
        self.assertEqual(app.cleanup_records(selected, current, full=True), [])
        self.assertFalse(log.exists())
        self.assertEqual(outside.read_text(), "KEEP")
        self.assertCountEqual(self.rows(state, "projects"), [("b",),("shared",)])
        self.assertEqual(self.rows(state, "project_roots"), [("b",b)])
        result=json.loads(local.read_text())
        self.assertEqual(result["project-order"], ["b","shared"])
        self.assertEqual(result["active-workspace-roots"], [b])
        self.assertNotIn("electron-owner-value:selected-project:owner", result)
        self.assertEqual(result["electron-owner-atoms:owner"]["new-task-project-by-computer"], {"other":"b"})
        self.assertEqual([r.record_id for r in app.load_records()], [T2])

    def test_hidden_or_new_chat_without_known_location_keeps_projects(self):
        state = self.db("state_5.sqlite", f"""
            create table threads(id text,cwd text); insert into threads values('{T1}',''),('{T2}','');
            create table projects(id text); insert into projects values('project');
        """)
        current = app.load_records()
        self.assertEqual(app.cleanup_records([r for r in current if r.record_id==T1], current, full=True), [])
        self.assertEqual(self.rows(state,"projects"), [("project",)])
        self.assertEqual([r.record_id for r in app.load_records()], [T2])

    def test_alias_files_lock_and_session_metadata(self):
        alias = "client-new-thread:33333333-3333-4333-8333-333333333333"
        state = self.file(self.home / ".codex-global-state.json",json.dumps({
            "client-thread-bindings-v1":{alias:T1}, "recent-workspace-files-v3":{
                "old":{"threadId":alias,"hostId":"local","path":"a"},
                "keep":{"threadId":T2,"hostId":"local","path":"b"}},
            "search-mcp-context:"+json.dumps(["local",T1]):{}, "thread-user-activity-times-v1": {
                f'["local","{T1}"]':1,f'["local","{T2}"]':2},
            "electron-owner-value:app-server-projects-migration-by-host:a":{
                "local:home":{"pendingThreadAssignmentIds":[T1,T2],"version":2}}}))
        locks = [self.file(self.home / "thread-writer-locks" / (sid+".lock")) for sid in (T1,T2)]
        self.assertEqual(cc.delete_selected(self.storage,{T1},[]),[])
        contents=state.read_text()
        self.assertNotIn(T1,contents)
        self.assertNotIn(alias,contents)
        self.assertIn(T2,contents)
        self.assertEqual([p.exists() for p in locks], [False,True])

    def test_claude_selection_full_and_custom_home(self):
        root=self.user / "Claude 設定"
        cwd=str(self.root / "actual repo")
        source=self.file(Path(cwd)/".git/config","KEEP")
        with patch.dict(os.environ,{"CLAUDE_CONFIG_DIR":str(root)}):
            store=root/"projects"/"my-project"
            for sid in (T1,T2):
                self.file(store/(sid+".jsonl"),json.dumps({"type":"custom-title","customTitle":"title "+sid[0],"cwd":cwd,"sessionId":sid}))
                self.file(store/sid/"subagents/agent.jsonl")
                self.file(root/"file-history"/sid/"snapshot")
            self.file(root/"history.jsonl","".join(json.dumps({"sessionId":sid,"project":cwd,"display":"text"})+"\n" for sid in (T1,T2)))
            cfg=self.file(root/".claude.json",json.dumps({"oauthAccount":"KEEP","projects":{cwd:{"lastSessionId":T1,"mcpServers":{"x":"KEEP"}}}}))
            index=self.file(store/"sessions-index.json",json.dumps({"entries":[{"sessionId":sid} for sid in (T1,T2)]}))
            log=self.file(root/"debug/old.log")
            current=app.load_records()
            self.assertCountEqual([r.title for r in current],["title 1","title 2"])
            self.assertEqual(app.cleanup_records([r for r in current if r.record_id==T1],current,full=False),[])
            self.assertFalse(log.exists())
            self.assertFalse((store/T1).exists())
            self.assertFalse((root/"file-history"/T1).exists())
            self.assertTrue((store/T2/"subagents/agent.jsonl").exists())
            self.assertEqual(json.loads(index.read_text())["entries"],[{"sessionId":T2}])
            current=app.load_records()
            self.assertEqual([r.record_id for r in current],[T2])
            self.assertEqual(app.cleanup_records(current,current,full=True),[])
            self.assertEqual(app.load_records(),[])
            self.assertFalse(store.exists())
            self.assertEqual(json.loads(cfg.read_text()),{"oauthAccount":"KEEP","projects":{cwd:{"mcpServers":{"x":"KEEP"}}}})
            self.assertEqual(source.read_text(),"KEEP")


class AttachmentCleanupTests(CleanupFixture):
    coverage = "local_thread_catalog_history_coverage"

    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(app, "codex_storage", return_value=self.storage))
        self.enterContext(patch.object(app, "home", return_value=self.user))
        self.enterContext(patch.object(app, "appdata_local", return_value=self.storage.local))
        self.enterContext(patch.object(app, "appdata_roaming", return_value=self.storage.roaming))
        self.rollouts = {tid: self.file(self.home / "sessions" / f"rollout-{tid}.jsonl") for tid in (T1, T2)}
        self.payload_file = self.file(self.root / "project/attachment.txt", "KEEP")
        self.state_db = self.db("state_5.sqlite", """
            CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL);
            CREATE TABLE thread_attachments(
                id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                attachment_type TEXT NOT NULL, identity_key TEXT NOT NULL, payload TEXT NOT NULL,
                created_at INTEGER NOT NULL, UNIQUE(thread_id, attachment_type, identity_key));
        """)
        with closing(sqlite3.connect(self.state_db)) as con:
            con.executemany("INSERT INTO threads VALUES (?, ?)", [(tid, str(p)) for tid, p in self.rollouts.items()])
            con.executemany("INSERT INTO thread_attachments VALUES (?, ?, 'file', 'key', ?, 1)",
                            [(f"attachment-{i}", tid, str(self.payload_file)) for i, tid in enumerate(self.rollouts)])
            con.commit()
        self.catalog = self.db("sqlite/codex.db", f"""
            CREATE TABLE {self.coverage}(
                host_id TEXT NOT NULL, scope TEXT NOT NULL, cursor TEXT, complete INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(host_id, scope));
            INSERT INTO {self.coverage} VALUES
                ('local', 'all', '{T1}', 0), ('local', '{T1}', NULL, 1), ('remote', 'all', 'cursor', 0);
            CREATE TABLE automations(prompt TEXT);
            INSERT INTO automations VALUES ('KEEP');
        """)

    def delete_first(self):
        records = [rec for rec in app.load_codex_records() if rec.record_id == T1]
        self.assertEqual(len(records), 1)
        return app.delete_selected_records(records)

    def test_selected_deletes_only_first_chat_and_preserves_shared_progress(self):
        progress = self.rows(self.catalog, self.coverage)
        self.assertEqual(self.delete_first(), (1, []))
        self.assertEqual([r[1] for r in self.rows(self.state_db, "thread_attachments")], [T2])
        self.assertFalse(self.rollouts[T1].exists())
        self.assertTrue(self.rollouts[T2].exists())
        self.assertCountEqual(self.rows(self.catalog, self.coverage), progress)
        self.assertEqual(self.payload_file.read_text(), "KEEP")

    def test_common_only_preserves_both_tables_and_chats(self):
        attachments = self.rows(self.state_db, "thread_attachments")
        progress = self.rows(self.catalog, self.coverage)
        log = self.file(self.home / "log/codex.log")
        cache = self.file(self.desktop / "Cache/data")
        self.assertEqual(app.clean_common_traces(), (1, []))
        self.assertFalse(log.exists())
        self.assertFalse(cache.exists())
        self.assertCountEqual(self.rows(self.state_db, "thread_attachments"), attachments)
        self.assertCountEqual(self.rows(self.catalog, self.coverage), progress)
        self.assertTrue(all(p.exists() for p in self.rollouts.values()))

    def test_full_clears_attachments_and_progress_for_all_hosts(self):
        pending = cc.inspect_remaining(self.storage)
        self.assertIn("Remaining: state_5.sqlite/thread_attachments", pending)
        self.assertIn(f"Remaining: codex.db/{self.coverage}", pending)
        self.assertEqual(app.clean_privacy_traces(), (1, []))
        self.assertEqual(self.rows(self.state_db, "thread_attachments"), [])
        self.assertEqual(self.rows(self.catalog, self.coverage), [])
        self.assertFalse(any(p.exists() for p in self.rollouts.values()))
        self.assertEqual(self.rows(self.catalog, "automations"), [("KEEP",)])
        self.assertEqual(self.payload_file.read_text(), "KEEP")
        self.assertEqual(cc.inspect_remaining(self.storage), [])

    def test_retry_finds_attachment_after_parent_row_was_deleted(self):
        self.db("state_5.sqlite", f"DELETE FROM threads WHERE id = '{T1}';")
        self.assertEqual(cc.inspect_remaining(self.storage, {T1}), ["Remaining: state_5.sqlite/thread_attachments"])
        self.assertEqual(self.delete_first(), (1, []))
        self.assertFalse(self.rollouts[T1].exists())
        self.assertEqual([r[1] for r in self.rows(self.state_db, "thread_attachments")], [T2])
        self.assertEqual(cc.inspect_remaining(self.storage, {T1}), [])

    def test_legacy_thread_artifacts_still_supports_selected_and_full(self):
        self.db("state_5.sqlite", """
            ALTER TABLE thread_attachments RENAME TO thread_artifacts;
            ALTER TABLE thread_artifacts RENAME COLUMN attachment_type TO artifact_type;
        """)
        self.assertEqual(self.delete_first(), (1, []))
        self.assertEqual([r[1] for r in self.rows(self.state_db, "thread_artifacts")], [T2])
        self.assertEqual(app.clean_privacy_traces(), (1, []))
        self.assertEqual(self.rows(self.state_db, "thread_artifacts"), [])

    def test_changed_tables_are_preserved_and_reported_on_selected_and_full(self):
        self.db("state_5.sqlite", "ALTER TABLE thread_attachments ADD COLUMN future AS (payload);")
        self.db("sqlite/codex.db", f"ALTER TABLE {self.coverage} RENAME COLUMN scope TO future_scope;")
        warnings = ["Unsupported table schema (preserved): state_5.sqlite/thread_attachments",
                    f"Unsupported table schema (preserved): codex.db/{self.coverage}"]
        attachments = self.rows(self.state_db, "thread_attachments")
        progress = self.rows(self.catalog, self.coverage)
        for ids, clean in [({T1}, self.delete_first), (None, app.clean_privacy_traces)]:
            with self.subTest(ids=ids):
                count, errors = clean()
                self.assertEqual(count, 0)
                remaining = cc.inspect_remaining(self.storage, ids)
                for warning in warnings:
                    self.assertTrue(any(e.endswith(warning) for e in errors), errors)
                    self.assertIn(warning, remaining)
                self.assertCountEqual(self.rows(self.state_db, "thread_attachments"), attachments)
                self.assertCountEqual(self.rows(self.catalog, self.coverage), progress)

    def test_changed_ownership_keys_with_original_column_names_are_preserved(self):
        self.db("state_5.sqlite", "ALTER TABLE threads RENAME COLUMN id TO new_parent_id;")
        self.db("sqlite/codex.db", f"""
            ALTER TABLE {self.coverage} RENAME TO old_coverage;
            CREATE TABLE {self.coverage}(
                host_id TEXT NOT NULL, scope TEXT NOT NULL, cursor TEXT, complete INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(scope, host_id));
            INSERT INTO {self.coverage} SELECT * FROM old_coverage;
            DROP TABLE old_coverage;
        """)
        for path, table in [(self.state_db, "thread_attachments"), (self.catalog, self.coverage)]:
            with self.subTest(table=table):
                before = self.rows(path, table)
                warning = [f"Unsupported table schema (preserved): {path.name}/{table}"]
                self.assertEqual(cc.database_rows(path, clean=True), warning)
                self.assertIn(warning[0], cc.inspect_remaining(self.storage))
                self.assertCountEqual(self.rows(path, table), before)


if __name__ == "__main__":
    unittest.main()
