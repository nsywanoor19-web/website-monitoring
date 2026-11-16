import json

from database.db import get_connection


def save_result(result: dict):
    workflow_steps = json.dumps(
        result.get("workflow_steps", []),
        ensure_ascii=False
    )

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO monitoring_results (
                website_id,
                website_name,
                checked_at,

                http_status,
                response_time,
                status,
                message,

                workflow_status,
                workflow_duration,
                workflow_message,

                page_load_time,
                final_url,
                page_title,
                workflow_steps
            )
            VALUES (
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            )
        """, (
            result["website_id"],
            result["website_name"],
            result["checked_at"],

            result.get("http_status"),
            result.get("response_time"),
            result["status"],
            result.get("message"),

            result.get("workflow_status"),
            result.get("workflow_duration"),
            result.get("workflow_message"),

            result.get("page_load_time"),
            result.get("final_url"),
            result.get("page_title"),
            workflow_steps
        ))

        conn.commit()