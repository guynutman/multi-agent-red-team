import sqlite3
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
    payload TEXT NOT NULL,
    target_context TEXT,
    target_response TEXT NOT NULL,
    retries INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES attempts(id),
    verdict TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    judged_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_campaign ON attempts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_attempts_subagent ON attempts(sub_agent_type);
CREATE INDEX IF NOT EXISTS idx_judgments_attempt ON judgments(attempt_id);
'''


class Storage:
    """SQLite-backed storage for campaigns, attempts, and judgments."""
    
    def __init__(self, db_path: str = "campaigns.db"):
        """Open (or create) the SQLite database at db_path. Runs schema setup if empty."""
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        
    def create_campaign(
        self,
        name: str,
        target_model: str,
        attacker_model: str,
        budget: int,
    ) -> int:
        """Insert a new campaign row. Returns the new campaign's id."""
        cursor = self.conn.execute(
            "INSERT INTO campaigns (name, target_model, attacker_model, budget, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, target_model, attacker_model, budget, now_iso()),
        )
        self.conn.commit()
        new_id = cursor.lastrowid
        return new_id
        
    def finish_campaign(self, campaign_id: int, status: str = "completed") -> None:
        """Set finished_at=now and status on a campaign."""
        self.conn.execute(
            "UPDATE campaigns SET finished_at = ?, status = ? WHERE id = ?",
            (now_iso(), status, campaign_id),
        )
        self.conn.commit()
        
    def record_attempt(
        self,
        campaign_id: int, 
        sub_agent_type: str,
        payload: str,
        target_context: str | None,
        target_response: str,
        retries: int, 
    ) -> int:
        """Insert an attempt row. Returns the new attempt's id."""
        cursor = self.conn.execute(
            "INSERT INTO attempts (campaign_id, sub_agent_type, payload, target_context, "
            "target_response, retries, attempted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sub_agent_type, payload, target_context, target_response, retries, now_iso()),
        )
        self.conn.commit()
        return cursor.lastrowid
        
    def record_judgment(
        self,
        attempt_id: int,
        verdict: str,           # 'success' | 'failure' | 'unclear'
        reasoning: str,
    ) -> int:
        """Insert a judgment row. Returns the new judgment's id."""
        cursor = self.conn.execute(
            "INSERT INTO judgments (attempt_id, verdict, reasoning, judged_at) "
            "VALUES (?, ?, ?, ?)",
            (attempt_id, verdict, reasoning, now_iso())
        )
        self.conn.commit()
        return cursor.lastrowid
        
    def get_campaign_attempts(self, campaign_id: int) -> list[dict]:
        """Return all attempts + their judgments for a campaign, joined."""
        cursor = self.conn.execute(
            """
            SELECT a.*, j.verdict, j.reasoning, j.judged_at
            FROM attempts a
            LEFT JOIN judgments j ON j.attempt_id = a.id
            WHERE a.campaign_id = ?
            ORDER BY a.attempted_at
            """,
            (campaign_id,),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
        
    def close(self) -> None:
        """Close the DB connection."""
        self.conn.close()
        
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()