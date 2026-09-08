import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "plugins"
    / "steeronce"
    / "skills"
    / "steeronce"
    / "scripts"
    / "steeronce.py"
)
SPEC = importlib.util.spec_from_file_location("steeronce", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def message(role: str, text: str) -> dict:
    kind = "input_text" if role == "user" else "output_text"
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": kind, "text": text}],
        },
    }


class SteerOnceTest(unittest.TestCase):
    def test_plugin_uses_portable_hook_paths(self):
        root = Path(__file__).parents[1]
        plugin = root / "plugins" / "steeronce"
        manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text())
        hooks = json.loads((plugin / "hooks" / "hooks.json").read_text())
        self.assertEqual(manifest["name"], "steeronce")
        commands = [
            hook["command"]
            for groups in hooks["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
        self.assertTrue(commands)
        self.assertTrue(all("$PLUGIN_ROOT" in command for command in commands))
        self.assertTrue(all("/Users/" not in command for command in commands))

    def test_legacy_text_fingerprints_are_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "corrections.db"
            db = MODULE.connect(db_path)
            old_fingerprint = MODULE.digest("don't guess")
            db.execute(
                """
                INSERT INTO events (
                    created_at, source_kind, content_hash, category, confidence,
                    status, detector_version
                ) VALUES (?, 'hook', ?, 'unsupported_assumption', 0.9, 'candidate', 2)
                """,
                (MODULE.now(), old_fingerprint),
            )
            db.commit()
            db.close()

            db = MODULE.connect(db_path)
            fingerprint, version = db.execute(
                "SELECT content_hash, detector_version FROM events"
            ).fetchone()
            self.assertNotEqual(fingerprint, old_fingerprint)
            self.assertEqual(version, MODULE.DETECTOR_VERSION)
            db.close()

    def test_legacy_database_is_copied_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "correction-kit" / "corrections.db"
            target = root / "steeronce" / "corrections.db"
            legacy.parent.mkdir()
            db = sqlite3.connect(legacy)
            db.execute("CREATE TABLE sample (value TEXT)")
            db.execute("INSERT INTO sample VALUES ('existing local data')")
            db.commit()
            db.close()

            MODULE.migrate_legacy_db(target, legacy)

            db = sqlite3.connect(target)
            self.assertEqual(
                db.execute("SELECT value FROM sample").fetchone()[0],
                "existing local data",
            )
            db.close()
            self.assertTrue(legacy.exists())

    def test_scan_is_private_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session.jsonl"
            records = [
                message("user", "Find an original open-source opportunity."),
                message("assistant", "Build a clone of the repository."),
                message("user", "你只会照抄吗？非要做类似的？我意思我们可以发现一个新的机会。"),
                message("assistant", "Understood."),
                message("user", "Thanks."),
            ]
            session.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
            db_path = root / "corrections.db"
            db = MODULE.connect(db_path)

            inserted, assistants, users = MODULE.scan_file(db, session)
            self.assertEqual((inserted, assistants, users), (1, 2, 3))
            self.assertEqual(MODULE.scan_file(db, session), (0, 0, 0))

            row = db.execute(
                "SELECT category, status, content_hash FROM events"
            ).fetchone()
            self.assertEqual(row[:2], ("intent_mismatch", "candidate"))
            self.assertNotIn("不是让你", row[2])
            self.assertNotEqual(row[2], MODULE.digest(records[2]["payload"]["content"][0]["text"]))

            columns = {item[1] for item in db.execute("PRAGMA table_info(events)")}
            self.assertNotIn("raw_text", columns)

            self.assertEqual(MODULE.set_status(db, 1, "confirmed", "Do not clone the example."), 0)
            self.assertEqual(
                db.execute("SELECT rule FROM events WHERE id = 1").fetchone()[0],
                "Do not clone the example.",
            )
            db.close()

    def test_explicit_record_contains_no_raw_text(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "corrections.db"
            db = MODULE.connect(db_path)
            self.assertEqual(MODULE.record(db, "scope_overreach", None), 0)
            row = db.execute(
                "SELECT source_kind, category, status, rule FROM events"
            ).fetchone()
            self.assertEqual(row, ("skill", "scope_overreach", "confirmed", None))
            db.close()

    def test_hooks_capture_hashes_and_load_only_approved_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "session.jsonl"
            transcript.write_text("", encoding="utf-8")
            db = MODULE.connect(root / "corrections.db")
            prompt = "不要猜，我已经把接口定义给你了。"

            self.assertIsNone(MODULE.handle_hook(db, {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-1",
                "transcript_path": str(transcript),
                "prompt": prompt,
            }))
            row = db.execute(
                "SELECT id, category, status, content_hash FROM events"
            ).fetchone()
            self.assertEqual(row[1:3], ("unsupported_assumption", "candidate"))
            self.assertNotEqual(row[3], prompt)
            interaction = db.execute(
                "SELECT correction_category FROM interactions"
            ).fetchone()
            self.assertEqual(interaction[0], "unsupported_assumption")
            self.assertNotEqual(row[3], MODULE.digest(prompt))

            transcript.write_text(
                json.dumps(message("user", prompt)) + "\n", encoding="utf-8"
            )
            self.assertEqual(MODULE.scan_file(db, transcript)[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

            self.assertEqual(
                MODULE.set_status(db, row[0], "confirmed", "Use supplied API definitions before inferring fields."),
                0,
            )
            output = MODULE.handle_hook(db, {
                "hook_event_name": "SessionStart",
                "session_id": "session-2",
            })
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Use supplied API definitions", context)
            self.assertNotIn(prompt, context)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rule_loads").fetchone()[0], 1)
            snapshot = MODULE.report_snapshot(db)
            self.assertEqual(snapshot["hook"]["user_turns"], 1)
            self.assertEqual(snapshot["hook"]["candidate_corrections"], 1)
            db.close()

    def test_report_splits_resumed_session_at_rule_load_time(self):
        with tempfile.TemporaryDirectory() as directory:
            db = MODULE.connect(Path(directory) / "corrections.db")
            session_hash = "same-session"
            db.executemany(
                """
                INSERT INTO interactions (
                    event_key, created_at, session_hash, correction_category, detector_version
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("before", "2026-09-08T10:00:00+00:00", session_hash, "intent_mismatch", MODULE.DETECTOR_VERSION),
                    ("after", "2026-09-08T12:00:00+00:00", session_hash, None, MODULE.DETECTOR_VERSION),
                ],
            )
            db.execute(
                "INSERT INTO rule_loads (session_hash, rules_hash, loaded_at, rule_count) VALUES (?, ?, ?, ?)",
                (session_hash, "rules", "2026-09-08T11:00:00+00:00", 1),
            )
            db.commit()

            hook = MODULE.report_snapshot(db)["hook"]
            self.assertEqual(hook["before_rules_candidate_per_100_turns"], 100.0)
            self.assertEqual(hook["after_rules_candidate_per_100_turns"], 0.0)
            db.close()


if __name__ == "__main__":
    unittest.main()
