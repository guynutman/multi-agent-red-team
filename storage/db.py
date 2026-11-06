import functools
import sqlite3
import threading
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = '''
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_model TEXT NOT NULL,
    attacker_model TEXT NOT NULL,
    budget INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    sub_agent_type TEXT NOT NULL,
    owasp_category TEXT,
    payload TEXT NOT NULL,
    target_context TEXT,
    target_response TEXT NOT NULL,
    retries INTEGER NOT NULL DEFAULT 0,
    tool_trace TEXT,
    attempt_index INTEGER,
    seed INTEGER,
    latency_ms INTEGER,
    output_tokens INTEGER,
    target_calls INTEGER,
    extra TEXT,
    attempted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES attempts(id),
    verdict TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    judged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    turn INTEGER NOT NULL,
    role TEXT NOT NULL,              -- 'attacker' | 'target'
    content TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_attempt ON turns(attempt_id);
CREATE INDEX IF NOT EXISTS idx_attempts_campaign ON attempts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_attempts_subagent ON attempts(sub_agent_type);
CREATE INDEX IF NOT EXISTS idx_judgments_attempt ON judgments(attempt_id);
'''

# Columns added after v1, with their types, for migrating older databases.
_ADDED_COLUMNS = {
    "owasp_category": "TEXT", "tool_trace": "TEXT", "attempt_index": "INTEGER",
    "seed": "INTEGER", "latency_ms": "INTEGER", "output_tokens": "INTEGER",
    "target_calls": "INTEGER", "extra": "TEXT",
}


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Storage:
    """SQLite-backed storage for campaigns, attempts, and judgments.

    Thread-safe: one connection shared across worker threads, serialized by a lock
    (SQLite writes are serialized anyway; the LLM calls are the slow part).
    """

    def __init__(self, db_path: str = "campaigns.db"):
        """Open (or create) the SQLite database at db_path. Runs schema setup if empty."""
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after v1 to databases created before them."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(attempts)")}
        for col, typ in _ADDED_COLUMNS.items():
            if col not in cols:
                self.conn.execute(f"ALTER TABLE attempts ADD COLUMN {col} {typ}")

    @_locked
    def create_campaign(self, name: str, target_model: str, attacker_model: str, budget: int) -> int:
        """Insert a new campaign row. Returns the new campaign's id."""
        cursor = self.conn.execute(
            "INSERT INTO campaigns (name, target_model, attacker_model, budget, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, target_model, attacker_model, budget, now_iso()),
        )
        self.conn.commit()
        return cursor.lastrowid

    @_locked
    def finish_campaign(self, campaign_id: int, status: str = "completed") -> None:
        """Set finished_at=now and status on a campaign."""
        self.conn.execute(
            "UPDATE campaigns SET finished_at = ?, status = ? WHERE id = ?",
            (now_iso(), status, campaign_id),
        )
        self.conn.commit()

    @_locked
    def record_attempt(
        self,
        campaign_id: int,
        sub_agent_type: str,
        payload: str,
        target_context: str | None,
        target_response: str,
        retries: int,
        owasp_category: str | None = None,
        tool_trace: str | None = None,
        attempt_index: int | None = None,
        seed: int | None = None,
        latency_ms: int | None = None,
        output_tokens: int | None = None,
        target_calls: int | None = None,
        extra: str | None = None,
    ) -> int:
        """Insert an attempt row. Returns the new attempt's id."""
        cursor = self.conn.execute(
            "INSERT INTO attempts (campaign_id, sub_agent_type, owasp_category, payload, "
            "target_context, target_response, retries, tool_trace, attempt_index, seed, "
            "latency_ms, output_tokens, target_calls, extra, attempted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sub_agent_type, owasp_category, payload, target_context,
             target_response, retries, tool_trace, attempt_index, seed, latency_ms,
             output_tokens, target_calls, extra, now_iso()),
        )
        self.conn.commit()
        return cursor.lastrowid

    @_locked
    def record_judgment(self, attempt_id: int, verdict: str, reasoning: str) -> int:
        """Insert a judgment row ('success' | 'failure' | 'unclear' | 'error')."""
        cursor = self.conn.execute(
            "INSERT INTO judgments (attempt_id, verdict, reasoning, judged_at) VALUES (?, ?, ?, ?)",
            (attempt_id, verdict, reasoning, now_iso()),
        )
        self.conn.commit()
        return cursor.lastrowid

    @_locked
    def record_turns(self, attempt_id: int, turns: list[dict]) -> None:
        """Persist a multi-turn conversation: dicts with turn, role, content."""
        self.conn.executemany(
            "INSERT INTO turns (attempt_id, turn, role, content) VALUES (?, ?, ?, ?)",
            [(attempt_id, t["turn"], t["role"], t["content"]) for t in turns],
        )
        self.conn.commit()

    @_locked
    def get_attempt_turns(self, attempt_id: int) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT turn, role, content FROM turns WHERE attempt_id = ? ORDER BY id",
            (attempt_id,),
        )
        return [dict(r) for r in cursor.fetchall()]

    @_locked
    def get_campaign(self, campaign_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if row is None:
            raise ValueError(f"No campaign with id {campaign_id}")
        return dict(row)

    @_locked
    def list_campaigns(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM campaigns ORDER BY id")]

    @_locked
    def get_campaign_attempts(self, campaign_id: int) -> list[dict]:
        """Return all attempts + their judgments for a campaign, joined, in dispatch order."""
        cursor = self.conn.execute(
            """
            SELECT a.*, j.verdict, j.reasoning, j.judged_at
            FROM attempts a
            LEFT JOIN judgments j ON j.attempt_id = a.id
            WHERE a.campaign_id = ?
            ORDER BY COALESCE(a.attempt_index, a.id), a.id
            """,
            (campaign_id,),
        )
        return [dict(r) for r in cursor.fetchall()]

    def close(self) -> None:
        """Close the DB connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
