#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB = Path.home() / ".local" / "share" / "steeronce" / "corrections.db"
LEGACY_DB = Path.home() / ".local" / "share" / "correction-kit" / "corrections.db"
DEFAULT_CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
DETECTOR_VERSION = 3

CATEGORIES: dict[str, tuple[str, ...]] = {
    "scope_overreach": (
        "谁让你",
        "没让你",
        "不要改",
        "别改",
        "didn't ask you to",
        "do not change",
        "don't change",
    ),
    "unsupported_assumption": (
        "不要猜",
        "别猜",
        "凭什么猜",
        "don't guess",
        "stop assuming",
        "made that up",
        "hallucinat",
    ),
    "ignored_context": (
        "都给你了",
        "已经给你",
        "我已经说了",
        "read what i sent",
        "already gave you",
        "already told you",
    ),
    "intent_mismatch": (
        "我意思",
        "我意思是",
        "我的意思是",
        "你理解错",
        "不是这个意思",
        "不是让你",
        "非要做类似",
        "not what i meant",
        "that's not what i meant",
        "you misunderstood",
    ),
    "incomplete_verification": (
        "没测试",
        "没有测试",
        "没验证",
        "没有验证",
        "did you test",
        "not tested",
        "not verified",
    ),
    "implementation_error": (
        "还是不行",
        "又报错",
        "仍然报错",
        "doesn't work",
        "still broken",
        "still failing",
    ),
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_path TEXT,
    source_line INTEGER,
    session_hash TEXT,
    content_hash TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('candidate', 'confirmed', 'dismissed')),
    rule TEXT,
    confirmed_at TEXT,
    detector_version INTEGER NOT NULL,
    UNIQUE(source_kind, source_path, source_line, content_hash)
);

CREATE TABLE IF NOT EXISTS source_stats (
    source_path TEXT PRIMARY KEY,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    assistant_turns INTEGER NOT NULL,
    user_turns INTEGER NOT NULL,
    detector_version INTEGER NOT NULL,
    scanned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    event_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    correction_category TEXT,
    detector_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_loads (
    session_hash TEXT NOT NULL,
    rules_hash TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    rule_count INTEGER NOT NULL,
    PRIMARY KEY(session_hash, rules_hash)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def event_key(*parts: object) -> str:
    """Create an opaque identity from event metadata, never message text."""
    return digest("\0".join(str(part) for part in parts))


def migrate_legacy_db(target: Path, legacy: Path) -> None:
    if target.exists() or not legacy.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()


def connect(path: Path) -> sqlite3.Connection:
    if path == DEFAULT_DB:
        migrate_legacy_db(path, LEGACY_DB)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
    if "confirmed_at" not in columns:
        db.execute("ALTER TABLE events ADD COLUMN confirmed_at TEXT")
    legacy = db.execute(
        """
        SELECT id, source_kind, source_path, source_line, session_hash
        FROM events WHERE detector_version < 3
        """
    ).fetchall()
    for event_id, source_kind, source_path, source_line, session_hash in legacy:
        if source_kind == "codex" and source_path and source_line:
            opaque_key = event_key("codex", source_path, source_line, session_hash)
        else:
            opaque_key = event_key("legacy", event_id, secrets.token_hex(16))
        db.execute(
            "UPDATE events SET content_hash=?, detector_version=? WHERE id=?",
            (opaque_key, DETECTOR_VERSION, event_id),
        )
    db.execute(
        "UPDATE events SET confirmed_at=created_at WHERE status='confirmed' AND confirmed_at IS NULL"
    )
    db.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return db


def message_text(payload: dict) -> str | None:
    if payload.get("type") != "message":
        return None
    pieces = []
    for item in payload.get("content", []):
        text = item.get("text")
        if isinstance(text, str):
            pieces.append(text)
    return "\n".join(pieces).strip() or None


def detect(text: str) -> tuple[str, float] | None:
    lowered = text.casefold()
    matches: list[tuple[int, str]] = []
    for category, phrases in CATEGORIES.items():
        longest = max((len(p) for p in phrases if p.casefold() in lowered), default=0)
        if longest:
            matches.append((longest, category))
    if not matches:
        return None
    length, category = max(matches)
    confidence = min(0.98, 0.72 + length / 100)
    return category, confidence


def insert_candidate(
    db: sqlite3.Connection,
    *,
    source_kind: str,
    source_path: str,
    source_line: int,
    session_hash: str,
    opaque_key: str,
    category: str,
    confidence: float,
) -> int:
    existing = db.execute(
        "SELECT id, status, source_line FROM events WHERE content_hash = ?",
        (opaque_key,),
    ).fetchone()
    if existing:
        event_id, status, old_line = existing
        if status == "candidate" and source_line and not old_line:
            db.execute(
                """
                UPDATE events SET source_kind=?, source_path=?, source_line=?,
                    category=?, confidence=?, detector_version=? WHERE id=?
                """,
                (
                    source_kind, source_path, source_line, category, confidence,
                    DETECTOR_VERSION, event_id,
                ),
            )
        return 0
    db.execute(
        """
        INSERT INTO events (
            created_at, source_kind, source_path, source_line, session_hash,
            content_hash, category, confidence, status, detector_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
        """,
        (
            now(), source_kind, source_path, source_line, session_hash,
            opaque_key, category, confidence, DETECTOR_VERSION,
        ),
    )
    return 1


def codex_messages(path: Path):
    session_hash = digest(str(path))[:16]
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("type") != "response_item":
                continue
            payload = item.get("payload", {})
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = message_text(payload)
            if text:
                yield line_number, role, text, session_hash


def scan_file(db: sqlite3.Connection, path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    prior = db.execute(
        "SELECT size_bytes, mtime_ns, detector_version FROM source_stats WHERE source_path = ?",
        (str(path),),
    ).fetchone()
    if prior == (stat.st_size, stat.st_mtime_ns, DETECTOR_VERSION):
        return 0, 0, 0

    assistant_turns = 0
    user_turns = 0
    inserted = 0
    session_hash = digest(str(path))[:16]
    hook_observed = db.execute(
        "SELECT 1 FROM interactions WHERE session_hash=? LIMIT 1", (session_hash,)
    ).fetchone() is not None
    for line_number, role, text, session_hash in codex_messages(path):
        if role == "assistant":
            assistant_turns += 1
            continue
        user_turns += 1
        result = detect(text)
        if not result:
            continue
        category, confidence = result
        if hook_observed:
            continue
        inserted += insert_candidate(
            db,
            source_kind="codex",
            source_path=str(path),
            source_line=line_number,
            session_hash=session_hash,
            opaque_key=event_key("codex", path, line_number, session_hash),
            category=category,
            confidence=confidence,
        )

    db.execute(
        """
        INSERT INTO source_stats (
            source_path, size_bytes, mtime_ns, assistant_turns, user_turns,
            detector_version, scanned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
            size_bytes=excluded.size_bytes,
            mtime_ns=excluded.mtime_ns,
            assistant_turns=excluded.assistant_turns,
            user_turns=excluded.user_turns,
            detector_version=excluded.detector_version,
            scanned_at=excluded.scanned_at
        """,
        (
            str(path), stat.st_size, stat.st_mtime_ns, assistant_turns, user_turns,
            DETECTOR_VERSION, now(),
        ),
    )
    db.commit()
    return inserted, assistant_turns, user_turns


def scan(db: sqlite3.Connection, roots: list[Path]) -> int:
    paths: list[Path] = []
    for root in roots:
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            paths.extend(sorted(root.rglob("*.jsonl")))
    inserted = assistant_turns = user_turns = scanned = 0
    for path in paths:
        new, assistants, users = scan_file(db, path)
        if assistants or users:
            scanned += 1
            assistant_turns += assistants
            user_turns += users
        inserted += new
    print(
        f"scanned={scanned} new_candidates={inserted} "
        f"assistant_turns={assistant_turns} user_turns={user_turns}"
    )
    return 0


def record(db: sqlite3.Connection, category: str, rule: str | None) -> int:
    if category not in CATEGORIES:
        print(f"unknown category: {category}", file=sys.stderr)
        return 2
    nonce = f"{now()}:{os.getpid()}:{category}"
    db.execute(
        """
        INSERT INTO events (
            created_at, source_kind, content_hash, category, confidence,
            status, rule, detector_version
        ) VALUES (?, 'skill', ?, ?, 1.0, 'confirmed', ?, ?)
        """,
        (now(), digest(nonce), category, rule, DETECTOR_VERSION),
    )
    db.commit()
    print(f"recorded category={category} raw_text_stored=no")
    return 0


def set_status(db: sqlite3.Connection, event_id: int, status: str, rule: str | None) -> int:
    if rule is not None:
        rule = " ".join(rule.split())
        if len(rule) > 300:
            print("rule must be 300 characters or fewer", file=sys.stderr)
            return 2
    cursor = db.execute(
        """
        UPDATE events SET status = ?, rule = COALESCE(?, rule),
            confirmed_at = CASE WHEN ?='confirmed' THEN COALESCE(confirmed_at, ?) ELSE confirmed_at END
        WHERE id = ?
        """,
        (status, rule, status, now(), event_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        print(f"event not found: {event_id}", file=sys.stderr)
        return 2
    print(f"event={event_id} status={status}")
    return 0


def list_events(db: sqlite3.Connection, status: str) -> int:
    rows = db.execute(
        """
        SELECT id, created_at, category, confidence, source_kind, source_line
        FROM events WHERE status = ? ORDER BY id DESC
        """,
        (status,),
    ).fetchall()
    if not rows:
        print("no events")
        return 0
    for event_id, created_at, category, confidence, source_kind, source_line in rows:
        location = f"line:{source_line}" if source_line else "no-source"
        print(
            f"{event_id:>4}  {category:<25} {confidence:.2f}  "
            f"{source_kind}:{location}  {created_at}"
        )
    return 0


def show_event(db: sqlite3.Connection, event_id: int) -> int:
    row = db.execute(
        "SELECT source_kind, source_path, source_line, category, status FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if not row:
        print(f"event not found: {event_id}", file=sys.stderr)
        return 2
    source_kind, source_path, source_line, category, status = row
    print(f"event={event_id} category={category} status={status}")
    if source_kind != "codex" or not source_path or not source_line:
        print("raw_text_stored=no source_preview=unavailable")
        return 0

    previous_assistant = None
    correction = None
    for line_number, role, text, _ in codex_messages(Path(source_path)):
        if line_number > source_line:
            break
        if role == "assistant":
            previous_assistant = text
        elif line_number == source_line:
            correction = text
    if correction is None:
        print("source_preview=missing", file=sys.stderr)
        return 2

    # The source remains canonical; previews are read on demand and never copied to SQLite.
    print("\n[assistant before correction]")
    print((previous_assistant or "(none)")[:2000])
    print("\n[user correction]")
    print(correction[:2000])
    return 0


def approved_rules(db: sqlite3.Connection) -> list[str]:
    return [row[0] for row in db.execute(
        """
        SELECT DISTINCT rule FROM events
        WHERE status = 'confirmed' AND rule IS NOT NULL AND trim(rule) != ''
        ORDER BY rule LIMIT 20
        """
    ).fetchall()]


def rules(db: sqlite3.Connection) -> int:
    rows = approved_rules(db)
    if not rows:
        print("no confirmed rules")
        return 0
    for rule in rows:
        print(f"- {rule}")
    return 0


def handle_hook(db: sqlite3.Connection, payload: dict) -> dict | None:
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return None
        transcript = payload.get("transcript_path")
        session_id = str(payload.get("session_id") or "unknown")
        source_path = str(transcript or f"hook:{session_id}")
        session_hash = digest(source_path)[:16]
        result = detect(prompt)
        category = result[0] if result else None
        turn_id = str(payload.get("turn_id") or secrets.token_hex(16))
        db.execute(
            """
            INSERT OR IGNORE INTO interactions (
                event_key, created_at, session_hash, correction_category, detector_version
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (digest(f"{session_hash}:{turn_id}"), now(), session_hash, category, DETECTOR_VERSION),
        )
        if not result:
            db.commit()
            return None
        category, confidence = result
        insert_candidate(
            db,
            source_kind="hook",
            source_path=source_path,
            source_line=0,
            session_hash=session_hash,
            opaque_key=event_key("hook", session_hash, turn_id),
            category=category,
            confidence=confidence,
        )
        db.commit()
        return None
    if event == "SessionStart":
        current_rules = approved_rules(db)
        if not current_rules:
            return None
        transcript = payload.get("transcript_path")
        session_id = str(payload.get("session_id") or "unknown")
        session_hash = digest(str(transcript or f"hook:{session_id}"))[:16]
        rules_hash = digest("\n".join(current_rules))
        db.execute(
            """
            INSERT OR REPLACE INTO rule_loads (
                session_hash, rules_hash, loaded_at, rule_count
            ) VALUES (?, ?, ?, ?)
            """,
            (session_hash, rules_hash, now(), len(current_rules)),
        )
        db.commit()
        lines = "\n".join(f"- {rule[:300]}" for rule in current_rules)
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "User-approved SteerOnce rules. Apply them when relevant; "
                    "the current user request takes precedence.\n" + lines
                ),
            }
        }
    return None


def hook(db: sqlite3.Connection) -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    output = handle_hook(db, payload)
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


def report_snapshot(db: sqlite3.Connection) -> dict:
    assistant_turns = db.execute(
        "SELECT COALESCE(SUM(assistant_turns), 0) FROM source_stats"
    ).fetchone()[0]
    rows = db.execute("SELECT status, category, COUNT(*) FROM events GROUP BY status, category").fetchall()
    counts = Counter({(status, category): count for status, category, count in rows})
    candidates = sum(count for (status, _), count in counts.items() if status == "candidate")
    confirmed = sum(count for (status, _), count in counts.items() if status == "confirmed")
    snapshot = {
        "assistant_turns": assistant_turns,
        "candidate_corrections": candidates,
        "confirmed_corrections": confirmed,
        "confirmed_per_100_turns": (
            round(confirmed / assistant_turns * 100, 2) if assistant_turns else None
        ),
        "categories": {},
    }
    for category in CATEGORIES:
        total = sum(counts[(status, category)] for status in ("candidate", "confirmed"))
        if total:
            snapshot["categories"][category] = total
    hook_turns, hook_corrections = db.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(correction_category IS NOT NULL), 0)
        FROM interactions
        """
    ).fetchone()
    hook_metrics = {
        "user_turns": hook_turns,
        "candidate_corrections": hook_corrections,
        "candidate_per_100_turns": (
            round(hook_corrections / hook_turns * 100, 2) if hook_turns else None
        ),
        "before_rules_candidate_per_100_turns": None,
        "after_rules_candidate_per_100_turns": None,
    }
    if hook_turns:
        protected_turns, protected_corrections = db.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(i.correction_category IS NOT NULL), 0)
            FROM interactions i
            WHERE EXISTS (
                SELECT 1 FROM rule_loads r WHERE r.session_hash=i.session_hash
            )
            """
        ).fetchone()
        unprotected_turns = hook_turns - protected_turns
        unprotected_corrections = hook_corrections - protected_corrections
        if unprotected_turns:
            hook_metrics["before_rules_candidate_per_100_turns"] = round(
                unprotected_corrections / unprotected_turns * 100, 2
            )
        if protected_turns:
            hook_metrics["after_rules_candidate_per_100_turns"] = round(
                protected_corrections / protected_turns * 100, 2
            )
    snapshot["hook"] = hook_metrics
    return snapshot


def report(db: sqlite3.Connection, as_json: bool = False) -> int:
    snapshot = report_snapshot(db)
    if as_json:
        print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
        return 0

    print(f"assistant_turns={snapshot['assistant_turns']}")
    print(f"candidate_corrections={snapshot['candidate_corrections']}")
    print(f"confirmed_corrections={snapshot['confirmed_corrections']}")
    confirmed_rate = snapshot["confirmed_per_100_turns"]
    if confirmed_rate is not None:
        print(f"confirmed_per_100_turns={confirmed_rate:.2f}")
    for category, total in snapshot["categories"].items():
        print(f"{category}={total}")
    hook_metrics = snapshot["hook"]
    if hook_metrics["user_turns"]:
        print(f"hook_user_turns={hook_metrics['user_turns']}")
        print(
            "hook_candidate_per_100_turns="
            f"{hook_metrics['candidate_per_100_turns']:.2f}"
        )
        before = hook_metrics["before_rules_candidate_per_100_turns"]
        after = hook_metrics["after_rules_candidate_per_100_turns"]
        if before is not None:
            print(f"before_rules_candidate_per_100_turns={before:.2f}")
        if after is not None:
            print(f"after_rules_candidate_per_100_turns={after:.2f}")
    return 0


def doctor(db: sqlite3.Connection, db_path: Path) -> int:
    event_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    mode = "unknown"
    try:
        mode = oct(db_path.stat().st_mode & 0o777)
    except OSError:
        pass
    print("status=ok")
    print(f"database={db_path.expanduser().resolve()}")
    print(f"database_mode={mode}")
    print(f"events={event_count}")
    print(f"approved_rules={len(approved_rules(db))}")
    print("raw_prompt_storage=no")
    print("content_fingerprint_storage=no")
    print("network_calls=no")
    print("hook_trust=review with /hooks after install or update")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="steeronce")
    root.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = root.add_subparsers(dest="command", required=True)

    scan_command = commands.add_parser("scan", help="scan Codex JSONL logs locally")
    scan_command.add_argument("paths", nargs="*", type=Path, default=[DEFAULT_CODEX_SESSIONS])

    record_command = commands.add_parser("record", help="record an explicit correction without raw text")
    record_command.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    record_command.add_argument("--rule")

    list_command = commands.add_parser("list", help="list metadata-only events")
    list_command.add_argument("--status", choices=("candidate", "confirmed", "dismissed"), default="candidate")

    show_command = commands.add_parser("show", help="read a candidate preview from its original local log")
    show_command.add_argument("id", type=int)

    confirm_command = commands.add_parser("confirm", help="confirm a candidate")
    confirm_command.add_argument("id", type=int)
    confirm_command.add_argument("--rule")

    dismiss_command = commands.add_parser("dismiss", help="dismiss a false positive")
    dismiss_command.add_argument("id", type=int)

    report_command = commands.add_parser("report", help="print aggregate local metrics")
    report_command.add_argument("--json", action="store_true", help="emit aggregate JSON only")
    commands.add_parser("rules", help="print user-approved local rules")
    commands.add_parser("doctor", help="check the local privacy and storage setup")
    commands.add_parser("hook", help=argparse.SUPPRESS)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    db = connect(args.db)
    try:
        if args.command == "scan":
            return scan(db, args.paths)
        if args.command == "record":
            return record(db, args.category, args.rule)
        if args.command == "list":
            return list_events(db, args.status)
        if args.command == "show":
            return show_event(db, args.id)
        if args.command == "confirm":
            return set_status(db, args.id, "confirmed", args.rule)
        if args.command == "dismiss":
            return set_status(db, args.id, "dismissed", None)
        if args.command == "report":
            return report(db, args.json)
        if args.command == "rules":
            return rules(db)
        if args.command == "doctor":
            return doctor(db, args.db)
        if args.command == "hook":
            return hook(db)
    finally:
        db.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
