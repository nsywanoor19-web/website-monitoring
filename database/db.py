import sqlite3

from config.settings import load_app_config, BASE_DIR


def get_connection():
    cfg = load_app_config()

    db_path = BASE_DIR / cfg.get(
        "database",
        "data/monitoring.db"
    )

    db_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = sqlite3.connect(
        db_path,
        timeout=20
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():
    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitoring_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                website_name TEXT NOT NULL,
                checked_at TEXT NOT NULL,

                http_status INTEGER,
                response_time REAL,
                status TEXT NOT NULL,
                message TEXT,

                workflow_status TEXT,
                workflow_duration REAL,
                workflow_message TEXT,

                page_load_time REAL,
                final_url TEXT,
                page_title TEXT,
                workflow_steps TEXT
            )
        """)

        # Menambahkan kolom baru jika database sudah pernah dibuat.
        existing_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(monitoring_results)"
            ).fetchall()
        }

        new_columns = {
            "page_load_time": "REAL",
            "final_url": "TEXT",
            "page_title": "TEXT",
            "workflow_steps": "TEXT"
        }

        for column_name, column_type in new_columns.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"""
                    ALTER TABLE monitoring_results
                    ADD COLUMN {column_name} {column_type}
                    """
                )

        conn.commit()


def get_latest_results():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT m.*
            FROM monitoring_results m
            INNER JOIN (
                SELECT website_id, MAX(id) AS max_id
                FROM monitoring_results
                GROUP BY website_id
            ) latest
            ON m.id = latest.max_id
            ORDER BY website_name
        """).fetchall()

    return [dict(row) for row in rows]


def get_history(limit=500):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM monitoring_results
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    return [dict(row) for row in rows][::-1]


def get_summary():
    latest = get_latest_results()

    total = len(latest)

    online = sum(
        1 for result in latest
        if result["status"] == "ONLINE"
    )

    errors = sum(
        1 for result in latest
        if result["status"] in ("ERROR", "SLOW")
    )

    values = [
        result["response_time"]
        for result in latest
        if result["response_time"] is not None
    ]

    return {
        "total": total,
        "online": online,
        "error": errors,
        "avg_response": (
            sum(values) / len(values)
            if values else None
        )
    }