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
from unittest.mock import patch

import codex_cleanup as cc
import app


T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cleaner-test-")
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.home = self.user / ".codex"
        self.home.mkdir(parents=True)
        self.storage = cc.Storage(self.home, self.user, self.user / "Roaming", self.user / "Local",
                                  self.user / "Documents/Codex")
        self.desktop = self.storage.roaming / "Codex"

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
        self.file(self.storage.documents / "2026/task/output.json")
        temp = self.file(self.home / "..codex-global-state.json.tmp-old", "partial private JSON")
        browser_files = [self.file(self.desktop / p, "browser secret") for p in (
            "Partitions/codex-browser-app/Network/Cookies", "web/Codex/codex-browser-app/Login Data",
            "web/Codex/codex-browser-app/Local Storage/data", "web/Codex/browser-sidebar-page-states.json",
            "Cache/cache", "web/Codex/Default/History")]
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
        self.assertTrue(all(not p.exists() for p in browser_files))
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}, hashes)
        after = json.loads((self.home / ".codex-global-state.json").read_text())
        self.assertNotIn("local-projects", after)
        self.assertEqual(after["electron-main-window-bounds"], {"width": 1200})
        self.assertEqual(after["electron-persisted-atom-state"], {"composer-model-picker-selection-mode-v1": "keep mode"})

    def test_independent_file_failure_does_not_skip_global_metadata(self):
        self.global_state()
        bad = self.file(self.storage.documents / "locked.data")
        original = cc.delete_target
        def fail(path, root, storage):
            if path == self.storage.documents:
                raise PermissionError("fixture locked")
            return original(path, root, storage)
        with patch.object(cc, "delete_target", side_effect=fail):
            errors = cc.cleanup_all(self.storage)
        self.assertTrue(errors)
        self.assertTrue(bad.exists())
        self.assertNotIn("local-projects", json.loads((self.home / ".codex-global-state.json").read_text()))

    @unittest.skipUnless(os.name == "nt", "Windows readonly semantics")
    def test_readonly_git_files_removed_without_acl_changes(self):
        p = self.file(self.storage.documents / "task/.git/objects/pack/test.idx")
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

    def test_reject_file_symlink_without_touching_target(self):
        target = self.file(self.root / "secret.txt", "KEEP")
        alias = self.home / "sessions/link"
        alias.parent.mkdir(parents=True)
        try:
            alias.symlink_to(target)
        except OSError:
            self.skipTest("File symlinks unavailable")
        try:
            self.assertTrue(cc.cleanup_all(self.storage))
            self.assertEqual(target.read_text(), "KEEP")
        finally:
            alias.unlink()

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
        self.assertEqual(cc.cleanup_all(self.storage, logs_only=True), [])
        self.assertTrue(p.exists())
        self.assertFalse(log.exists())

    def test_process_probe_failure_is_not_assumed_stopped(self):
        with patch.object(app, "run_hidden", side_effect=OSError("probe unavailable")):
            with self.assertRaises(OSError):
                app.process_running("codex.exe")

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_junction_rejected_and_outside_target_untouched(self):
        import subprocess
        target = self.file(self.root / "outside/keep.txt", "KEEP")
        link = self.home / "sessions"
        # Native PowerShell creates only this isolated fixture junction.
        command = "New-Item -ItemType Junction -Path '" + str(link).replace("'", "''") + "' -Target '" + str(target.parent).replace("'", "''") + "' | Out-Null"
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertTrue(cc.cleanup_all(self.storage))
            self.assertEqual(target.read_text(), "KEEP")
        finally:
            # rmdir unlinks the junction, not its target directory.
            link.rmdir()

    def test_corrupt_global_json_reports_error_and_preserves_settings(self):
        p = self.file(self.home / ".codex-global-state.json", '{"settings":')
        self.assertTrue(cc.cleanup_all(self.storage))
        self.assertEqual(p.read_text(), '{"settings":')

    def test_extra_db_root_supported(self):
        self.storage.extra_db = self.home / "custom-sql"
        p = self.state("custom-sql/state_8.sqlite")
        self.assertEqual(cc.cleanup_all(self.storage), [])
        self.assertEqual(self.rows(p, "threads"), [])

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
             patch.object(cc, "delete_selected", return_value=["partial failure"]), \
             patch.object(app, "cleanup_empty_dirs"), patch.object(app, "claude_projects_path", return_value=self.user / ".claude/projects"):
            count, errors = app.delete_selected_records([rec])
        self.assertEqual(count, 0)
        self.assertTrue(errors)

    def test_claude_full_cleanup_removes_orphan_history_preserves_config(self):
        history = self.file(self.user / ".claude/history.jsonl", '{"sessionId":"orphan","display":"private"}\n')
        cfg = self.file(self.user / ".claude.json", '{"oauthAccount":{"keep":"KEEP"}}')
        with patch.object(app, "home", return_value=self.user), patch.object(app, "codex_privacy_data_present", return_value=False), \
             patch.object(app, "claude_desktop_code_sessions_paths", return_value=[]):
            count, errors = app.clean_privacy_traces()
        self.assertEqual((count, errors), (1, []))
        self.assertEqual(history.read_text(), "")
        self.assertEqual(json.loads(cfg.read_text()), {"oauthAccount": {"keep": "KEEP"}})


if __name__ == "__main__":
    unittest.main()
