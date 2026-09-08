#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB = Path.home() / ".local" / "share" / "steeronce" / "corrections.db"
LEGACY_DB = Path.home() / ".local" / "share" / "correction-kit" / "corrections.db"
DEFAULT_CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
DETECTOR_VERSION = 5
PRIVACY_MIGRATION_VERSION = 3
MARKER_PATTERN = re.compile(r"<!--steeronce:(.*?)-->", re.DOTALL)

CATEGORIES = (
    "intent_mismatch",
    "unsupported_assumption",
    "ignored_context",
    "scope_overreach",
    "incomplete_verification",
    "implementation_error",
)

SCOPES = ("global", "project")
TRIGGERS = (
    "general",
    "communication",
    "diagnosis",
    "implementation",
    "research",
    "review",
    "verification",
)


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
    scope_kind TEXT NOT NULL DEFAULT 'global',
    scope_key TEXT,
    trigger TEXT NOT NULL DEFAULT 'general',
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
    project_key TEXT,
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


def project_key(cwd: str) -> str:
    """Create a stable local project scope without storing its path."""
    return digest(str(Path(cwd).expanduser().resolve()))[:16]


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
    event_columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
    event_migrations = {
        "confirmed_at": "TEXT",
        "scope_kind": "TEXT NOT NULL DEFAULT 'global'",
        "scope_key": "TEXT",
        "trigger": "TEXT NOT NULL DEFAULT 'general'",
    }
    for column, definition in event_migrations.items():
        if column not in event_columns:
            db.execute(f"ALTER TABLE events ADD COLUMN {column} {definition}")
    interaction_columns = {
        row[1] for row in db.execute("PRAGMA table_info(interactions)")
    }
    if "project_key" not in interaction_columns:
        db.execute("ALTER TABLE interactions ADD COLUMN project_key TEXT")
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
            (opaque_key, PRIVACY_MIGRATION_VERSION, event_id),
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
    for _, role, _, _ in codex_messages(path):
        if role == "assistant":
            assistant_turns += 1
        else:
            user_turns += 1

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
    return 0, assistant_turns, user_turns


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


def valid_event_key(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def normalize_rule(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    rule = " ".join(value.split())
    if not rule or len(rule) > 300 or "<!--" in rule or "-->" in rule:
        return None
    return rule


def propose_interaction(
    db: sqlite3.Connection,
    interaction_key: str,
    category: str,
    scope_kind: str,
    trigger: str,
    rule: str,
) -> int | None:
    normalized_rule = normalize_rule(rule)
    if (
        not valid_event_key(interaction_key)
        or category not in CATEGORIES
        or scope_kind not in SCOPES
        or trigger not in TRIGGERS
        or normalized_rule is None
    ):
        return None
    interaction = db.execute(
        """
        SELECT session_hash, project_key, correction_category
        FROM interactions WHERE event_key=?
        """,
        (interaction_key,),
    ).fetchone()
    if interaction is None:
        return None
    session_hash, interaction_project_key, existing_category = interaction
    if existing_category is not None and existing_category != category:
        return None
    preference_scope_key = interaction_project_key if scope_kind == "project" else None
    if scope_kind == "project" and not preference_scope_key:
        return None

    db.execute(
        "UPDATE interactions SET correction_category=?, detector_version=? WHERE event_key=?",
        (category, DETECTOR_VERSION, interaction_key),
    )
    insert_candidate(
        db,
        source_kind="semantic",
        source_path="",
        source_line=0,
        session_hash=session_hash,
        opaque_key=interaction_key,
        category=category,
        confidence=1.0,
    )
    event = db.execute(
        "SELECT id, status FROM events WHERE content_hash=?",
        (interaction_key,),
    ).fetchone()
    if event is None or event[1] != "candidate":
        db.rollback()
        return None
    db.execute(
        """
        UPDATE events
        SET category=?, rule=?, scope_kind=?, scope_key=?, trigger=?, detector_version=?
        WHERE id=?
        """,
        (
            category,
            normalized_rule,
            scope_kind,
            preference_scope_key,
            trigger,
            DETECTOR_VERSION,
            event[0],
        ),
    )
    db.commit()
    return event[0]


def mark_interaction(db: sqlite3.Connection, interaction_key: str, category: str) -> int:
    if not valid_event_key(interaction_key):
        print("invalid event key", file=sys.stderr)
        return 2
    if category not in CATEGORIES:
        print(f"unknown category: {category}", file=sys.stderr)
        return 2

    row = db.execute(
        "SELECT session_hash, correction_category FROM interactions WHERE event_key=?",
        (interaction_key,),
    ).fetchone()
    if row is None:
        print("event key not found", file=sys.stderr)
        return 2
    session_hash, existing_category = row
    if existing_category is not None:
        if existing_category != category:
            print(f"event already marked as {existing_category}", file=sys.stderr)
            return 2
        print(f"marked category={category} raw_text_stored=no")
        return 0

    db.execute(
        "UPDATE interactions SET correction_category=?, detector_version=? WHERE event_key=?",
        (category, DETECTOR_VERSION, interaction_key),
    )
    insert_candidate(
        db,
        source_kind="semantic",
        source_path="",
        source_line=0,
        session_hash=session_hash,
        opaque_key=interaction_key,
        category=category,
        confidence=1.0,
    )
    db.commit()
    print(f"marked category={category} raw_text_stored=no")
    return 0


def set_status(
    db: sqlite3.Connection,
    event_id: int,
    status: str,
    rule: str | None,
    scope_kind: str | None = None,
    project_scope_key: str | None = None,
    emit: bool = True,
) -> int:
    event = db.execute(
        "SELECT rule, scope_kind, scope_key, content_hash FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    if event is None:
        if emit:
            print(f"event not found: {event_id}", file=sys.stderr)
        return 2
    existing_rule, existing_scope, existing_scope_key, content_hash = event
    normalized_rule = normalize_rule(rule) if rule is not None else existing_rule
    if status == "confirmed" and not normalized_rule:
        if emit:
            print("a non-empty abstract rule is required", file=sys.stderr)
        return 2
    if rule is not None and normalized_rule is None:
        if emit:
            print("rule must be non-empty and 300 characters or fewer", file=sys.stderr)
        return 2

    final_scope = scope_kind or existing_scope or "global"
    if final_scope not in SCOPES:
        if emit:
            print(f"unknown scope: {final_scope}", file=sys.stderr)
        return 2
    final_scope_key = existing_scope_key
    if final_scope == "global":
        final_scope_key = None
    elif not final_scope_key:
        final_scope_key = project_scope_key
        if not final_scope_key:
            row = db.execute(
                "SELECT project_key FROM interactions WHERE event_key=?",
                (content_hash,),
            ).fetchone()
            final_scope_key = row[0] if row else None
        if not final_scope_key:
            if emit:
                print("project scope is unavailable for this event", file=sys.stderr)
            return 2

    db.execute(
        """
        UPDATE events SET status=?, rule=?, scope_kind=?, scope_key=?,
            confirmed_at=CASE WHEN ?='confirmed' THEN COALESCE(confirmed_at, ?) ELSE confirmed_at END
        WHERE id=?
        """,
        (
            status,
            normalized_rule,
            final_scope,
            final_scope_key,
            status,
            now(),
            event_id,
        ),
    )
    db.commit()
    if emit:
        print(f"event={event_id} status={status} scope={final_scope}")
    return 0


def list_events(db: sqlite3.Connection, status: str, include_legacy: bool = False) -> int:
    legacy_filter = ""
    parameters: tuple[object, ...] = (status,)
    if status == "candidate" and not include_legacy:
        legacy_filter = (
            " AND NOT (source_kind IN ('codex', 'hook') AND detector_version < ?)"
        )
        parameters = (status, DETECTOR_VERSION)
    rows = db.execute(
        """
        SELECT id, created_at, category, confidence, source_kind, source_line,
               rule, scope_kind, trigger
        FROM events WHERE status = ?
        """ + legacy_filter + " ORDER BY id DESC",
        parameters,
    ).fetchall()
    if not rows:
        print("no events")
        return 0
    for (
        event_id, created_at, category, confidence, source_kind, source_line,
        rule, scope_kind, trigger,
    ) in rows:
        location = f"line:{source_line}" if source_line else "no-source"
        print(
            f"{event_id:>4}  {category:<25} {confidence:.2f}  "
            f"scope={scope_kind} trigger={trigger} {source_kind}:{location}  {created_at}"
        )
        if rule:
            print(f"      preference: {rule[:300]}")
    return 0


def show_event(db: sqlite3.Connection, event_id: int) -> int:
    row = db.execute(
        """
        SELECT source_kind, source_path, source_line, category, status,
               rule, scope_kind, trigger
        FROM events WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    if not row:
        print(f"event not found: {event_id}", file=sys.stderr)
        return 2
    source_kind, source_path, source_line, category, status, rule, scope_kind, trigger = row
    print(
        f"event={event_id} category={category} status={status} "
        f"scope={scope_kind} trigger={trigger}"
    )
    if rule:
        print(f"proposed_preference={rule}")
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


def approved_preferences(
    db: sqlite3.Connection, current_project_key: str | None = None
) -> list[tuple[str, str, str]]:
    parameters: tuple[object, ...] = ()
    scope_filter = ""
    if current_project_key is not None:
        scope_filter = " AND (scope_kind='global' OR (scope_kind='project' AND scope_key=?))"
        parameters = (current_project_key,)
    rows = db.execute(
        """
        SELECT scope_kind, trigger, rule FROM events
        WHERE status = 'confirmed' AND rule IS NOT NULL AND trim(rule) != ''
        """ + scope_filter + " ORDER BY CASE scope_kind WHEN 'project' THEN 0 ELSE 1 END, id DESC",
        parameters,
    ).fetchall()
    preferences: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for scope_kind, trigger, rule in rows:
        if rule in seen:
            continue
        seen.add(rule)
        preferences.append((scope_kind, trigger, rule))
        if len(preferences) == 20:
            break
    return preferences


def approved_rules(db: sqlite3.Connection) -> list[str]:
    return [rule for _, _, rule in approved_preferences(db)]


def rules(db: sqlite3.Connection) -> int:
    rows = approved_preferences(db)
    if not rows:
        print("no confirmed rules")
        return 0
    for scope_kind, trigger, rule in rows:
        print(f"- [{scope_kind}; trigger={trigger}] {rule}")
    return 0


def hook_identity(payload: dict) -> tuple[str, str]:
    transcript = payload.get("transcript_path")
    session_id = str(payload.get("session_id") or "unknown")
    source_path = str(transcript or f"hook:{session_id}")
    session_hash = digest(source_path)[:16]
    turn_id = str(payload.get("turn_id") or "")
    return session_hash, digest(f"{session_hash}:{turn_id}")


def marker_for_event(message: object, expected_event_key: str) -> dict | None:
    if not isinstance(message, str):
        return None
    for encoded in reversed(MARKER_PATTERN.findall(message)):
        try:
            marker = json.loads(encoded)
        except json.JSONDecodeError:
            continue
        if isinstance(marker, dict) and marker.get("event") == expected_event_key:
            return marker
    return None


def latest_candidate(db: sqlite3.Connection, session_hash: str) -> int | None:
    row = db.execute(
        """
        SELECT id FROM events
        WHERE session_hash=? AND status='candidate'
          AND rule IS NOT NULL AND trim(rule) != ''
        ORDER BY id DESC LIMIT 1
        """,
        (session_hash,),
    ).fetchone()
    return row[0] if row else None


def apply_stop_marker(db: sqlite3.Connection, payload: dict) -> None:
    session_hash, expected_event_key = hook_identity(payload)
    marker = marker_for_event(payload.get("last_assistant_message"), expected_event_key)
    if marker is None:
        return
    interaction = db.execute(
        "SELECT project_key FROM interactions WHERE event_key=? AND session_hash=?",
        (expected_event_key, session_hash),
    ).fetchone()
    if interaction is None:
        return
    current_project_key = interaction[0]
    action = marker.get("action")
    if action == "propose":
        propose_interaction(
            db,
            expected_event_key,
            marker.get("category"),
            marker.get("scope"),
            marker.get("trigger"),
            marker.get("rule"),
        )
        return
    if action not in {"confirm", "confirm_latest", "dismiss", "dismiss_latest"}:
        return
    event_id = marker.get("candidate_id")
    if action.endswith("_latest"):
        event_id = latest_candidate(db, session_hash)
    if not isinstance(event_id, int):
        return
    if action.startswith("confirm"):
        scope_kind = marker.get("scope")
        if scope_kind not in SCOPES:
            return
        set_status(
            db,
            event_id,
            "confirmed",
            None,
            scope_kind=scope_kind,
            project_scope_key=current_project_key,
            emit=False,
        )
    else:
        set_status(db, event_id, "dismissed", None, emit=False)


def handle_hook(db: sqlite3.Connection, payload: dict) -> dict | None:
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return None
        session_hash, interaction_key = hook_identity(payload)
        cwd = str(payload.get("cwd") or ".")
        db.execute(
            """
            INSERT OR IGNORE INTO interactions (
                event_key, created_at, session_hash, project_key,
                correction_category, detector_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                interaction_key,
                now(),
                session_hash,
                project_key(cwd),
                None,
                DETECTOR_VERSION,
            ),
        )
        db.commit()
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    f"SteerOnce event `{interaction_key}`. Use the SteerOnce skill "
                    "only if this message explicitly corrects the agent, approves or "
                    "rejects a proposed preference, or asks to manage SteerOnce. The "
                    "skill can emit a local marker handled after the response. "
                    "Otherwise ignore this context."
                ),
            }
        }
    if event == "Stop":
        apply_stop_marker(db, payload)
        return None
    if event == "SessionStart":
        cwd = str(payload.get("cwd") or ".")
        current_preferences = approved_preferences(db, project_key(cwd))
        if not current_preferences:
            return None
        session_hash, _ = hook_identity(payload)
        rendered_preferences = [
            f"[{scope_kind}; trigger={trigger}] {rule[:300]}"
            for scope_kind, trigger, rule in current_preferences
        ]
        rules_hash = digest("\n".join(rendered_preferences))
        db.execute(
            """
            INSERT OR REPLACE INTO rule_loads (
                session_hash, rules_hash, loaded_at, rule_count
            ) VALUES (?, ?, ?, ?)
            """,
            (session_hash, rules_hash, now(), len(current_preferences)),
        )
        db.commit()
        lines = "\n".join(f"- {rule}" for rule in rendered_preferences)
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "User-approved SteerOnce working preferences for this context. "
                    "Apply them when relevant. The user's current explicit request "
                    "always takes precedence.\n" + lines
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
    rows = db.execute(
        """
        SELECT status, category, COUNT(*) FROM events
        WHERE status != 'candidate'
           OR source_kind NOT IN ('codex', 'hook')
           OR detector_version >= ?
        GROUP BY status, category
        """,
        (DETECTOR_VERSION,),
    ).fetchall()
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
                SELECT 1 FROM rule_loads r
                WHERE r.session_hash=i.session_hash
                  AND r.loaded_at <= i.created_at
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
    print(f"approved_preferences={len(approved_rules(db))}")
    print("raw_prompt_storage=no")
    print("content_fingerprint_storage=no")
    print("network_calls=no")
    print("hook_trust=review in Codex CLI with /hooks after install or update")
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

    mark_command = commands.add_parser(
        "mark", help="mark an anonymous interaction as a correction"
    )
    mark_command.add_argument("event_key")
    mark_command.add_argument("--category", required=True, choices=sorted(CATEGORIES))

    list_command = commands.add_parser("list", help="list metadata-only events")
    list_command.add_argument("--status", choices=("candidate", "confirmed", "dismissed"), default="candidate")
    list_command.add_argument(
        "--include-legacy",
        action="store_true",
        help="include unreviewed candidates from the retired phrase detector",
    )

    show_command = commands.add_parser("show", help="read a candidate preview from its original local log")
    show_command.add_argument("id", type=int)

    confirm_command = commands.add_parser("confirm", help="confirm a candidate")
    confirm_command.add_argument("id", type=int)
    confirm_command.add_argument("--rule")
    confirm_command.add_argument("--scope", choices=SCOPES)

    dismiss_command = commands.add_parser("dismiss", help="dismiss a false positive")
    dismiss_command.add_argument("id", type=int)

    report_command = commands.add_parser("report", help="print aggregate local metrics")
    report_command.add_argument("--json", action="store_true", help="emit aggregate JSON only")
    commands.add_parser("preferences", help="print user-approved working preferences")
    commands.add_parser("rules", help="alias for preferences")
    commands.add_parser("doctor", help="check the local privacy and storage setup")
    commands.add_parser("hook", help="process a Codex hook payload")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    db = connect(args.db)
    try:
        if args.command == "scan":
            return scan(db, args.paths)
        if args.command == "record":
            return record(db, args.category, args.rule)
        if args.command == "mark":
            return mark_interaction(db, args.event_key, args.category)
        if args.command == "list":
            return list_events(db, args.status, args.include_legacy)
        if args.command == "show":
            return show_event(db, args.id)
        if args.command == "confirm":
            return set_status(
                db, args.id, "confirmed", args.rule, scope_kind=args.scope
            )
        if args.command == "dismiss":
            return set_status(db, args.id, "dismissed", None)
        if args.command == "report":
            return report(db, args.json)
        if args.command in {"preferences", "rules"}:
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
