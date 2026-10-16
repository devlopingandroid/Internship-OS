import sqlite3
from pathlib import Path
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "applications.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        # Original jobs table — schema unchanged
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "url TEXT NOT NULL UNIQUE, "
            "title TEXT NOT NULL, "
            "company TEXT DEFAULT '', "
            "description TEXT DEFAULT '', "
            "location TEXT DEFAULT '', "
            "pay_status TEXT DEFAULT 'unknown', "
            "source TEXT DEFAULT 'Manual', "
            "status TEXT DEFAULT 'saved', "
            "score INTEGER DEFAULT 0, "
            "reasons TEXT DEFAULT '[]', "
            "cover_letter TEXT DEFAULT '', "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        columns = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        additions = {
            'work_mode': "TEXT DEFAULT 'unknown'", 'eligibility': "TEXT DEFAULT 'unknown'",
            'section': "TEXT DEFAULT 'other'", 'metadata': "TEXT DEFAULT '{}'",
            'source_id': 'TEXT', 'application_url': 'TEXT', 'publication_date': 'TEXT',
            'updated_at': 'TEXT', 'last_verified_at': 'TEXT', 'decision': "TEXT DEFAULT 'review_required'",
        }
        for name, definition in additions.items():
            if name not in columns: conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS jobs_source_id ON jobs(source, source_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS jobs_section_score ON jobs(section, score DESC)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(2)")
        conn.execute("CREATE TABLE IF NOT EXISTS source_cache(url TEXT PRIMARY KEY, payload TEXT, fetched_at REAL, verified_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS source_backoff(url TEXT PRIMARY KEY, retry_at REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS discovery_runs(id TEXT PRIMARY KEY, status TEXT, summary TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_discovery ON discovery_runs((1)) WHERE status IN ('running','cancelling')")
        conn.execute("CREATE TABLE IF NOT EXISTS status_history(id INTEGER PRIMARY KEY, job_id INTEGER, old_status TEXT, new_status TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)")

        # Preferences table — stores user config as a single JSON blob (row id=1)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS preferences ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "data TEXT NOT NULL DEFAULT '{}'"
            ")"
        )
        # Seed with defaults if the row doesn't exist yet
        import json
        from .rules import DEFAULT_PREFERENCES
        conn.execute(
            "INSERT OR IGNORE INTO preferences(id, data) VALUES(1, ?)",
            (json.dumps(DEFAULT_PREFERENCES),),
        )

def get_preferences(conn=None) -> dict:
    import json
    from .rules import DEFAULT_PREFERENCES
    should_close = False
    if conn is None:
        conn = connect()
        should_close = True
    try:
        row = conn.execute("SELECT data FROM preferences WHERE id=1").fetchone()
        if row and row["data"]:
            loaded = json.loads(row["data"])
            merged = {**DEFAULT_PREFERENCES, **loaded}
            return merged
        return dict(DEFAULT_PREFERENCES)
    finally:
        if should_close:
            conn.close()

def save_preferences(prefs: dict, conn=None) -> dict:
    import json
    from .rules import DEFAULT_PREFERENCES
    merged = {**DEFAULT_PREFERENCES, **prefs}
    should_close = False
    if conn is None:
        conn = connect()
        should_close = True
    try:
        conn.execute(
            "INSERT INTO preferences(id, data) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (json.dumps(merged),),
        )
        if should_close:
            conn.commit()
        return merged
    finally:
        if should_close:
            conn.close()

def reclassify_all_jobs(conn=None, prefs: dict = None) -> dict:
    """Reclassify and re-score all jobs in the database against preferences."""
    import json
    from .rules import evaluate_job
    should_close = False
    if conn is None:
        conn = connect()
        should_close = True
    try:
        if prefs is None:
            prefs = get_preferences(conn)

        rows = conn.execute("SELECT * FROM jobs").fetchall()
        counts = {"best_matches": 0, "needs_review": 0, "other": 0, "total": 0}

        for r in rows:
            job_dict = {**json.loads(r["metadata"] or '{}'), **dict(r)}
            # Persisted inferred mode is not independent evidence on subsequent runs.
            job_dict['work_mode'] = job_dict.get('source_work_mode', '')
            eval_res = evaluate_job(job_dict, prefs)
            section = eval_res["section"]

            conn.execute(
                "UPDATE jobs SET work_mode=?, eligibility=?, section=?, score=?, reasons=?, decision=?, metadata=? WHERE id=?",
                (
                    eval_res["work_mode"],
                    eval_res["eligibility"],
                    eval_res["section"],
                    eval_res["score"],
                    json.dumps(eval_res["reasons"]),
                    eval_res["decision"],
                    json.dumps({**json.loads(r["metadata"] or "{}"), **eval_res}),
                    r["id"],
                ),
            )
            # Only count as reclassified after the update statement successfully executes
            counts[section] = counts.get(section, 0) + 1
            counts["total"] += 1

        if should_close:
            conn.commit()
        return counts
    finally:
        if should_close:
            conn.close()

