
import json

from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import load_app_config, load_websites
from monitoring.http_checker import check_http
from monitoring.workflow_runner import run_workflow
from database.repository import save_result
from notifications.telegram_bot import send_alert


def check_one_website(site: dict, cfg: dict) -> dict:
    """Melakukan pengecekan HTTP dan workflow pada satu website."""

    # 1. HTTP Check
    http = check_http(
        site["url"],
        int(cfg.get("default_timeout", 15))
    )

    threshold = float(
        site.get(
            "threshold_seconds",
            cfg.get("slow_threshold", 5)
        )
    )

    if (
        http["status"] == "ONLINE"
        and http["response_time"] is not None
        and http["response_time"] > threshold
    ):
        http["status"] = "SLOW"

        http["message"] += (
            f" | Melebihi ambang {threshold} detik"
        )

    # 2. Workflow Check
    # Jika website belum memiliki workflow khusus,
    # gunakan workflow dasar secara otomatis.
    workflow_steps = site.get("workflow") or [
        {
            "action": "open",
            "url": site["url"],
            "wait_until": "load"
        }
    ]

    workflow = run_workflow(
        workflow_steps,
        int(cfg.get("default_timeout", 15)) * 1000
    )

    # 3. Waktu pengecekan
    checked_at = datetime.now(
        ZoneInfo("Asia/Jakarta")
    ).isoformat(timespec="seconds")

    # 4. Gabungkan hasil
    result = {
        "website_id": site["id"],
        "website_name": site["name"],
        "checked_at": checked_at,

        "http_status": http.get("http_status"),
        "response_time": http.get("response_time"),
        "status": http.get("status"),
        "message": http.get("message"),

        "workflow_status": workflow.get("status"),
        "workflow_duration": workflow.get("duration"),
        "workflow_message": workflow.get("message"),

        "page_load_time": workflow.get("page_load_time"),
        "final_url": workflow.get("final_url"),
        "page_title": workflow.get("page_title"),
        "workflow_steps": workflow.get("steps", [])
    }

    # 5. Simpan hasil ke database
    save_result(result)

    # 6. Kirim Telegram jika ada masalah
    if cfg.get("telegram_enabled", False):
        if (
            result["status"] in ("ERROR", "SLOW")
            or result["workflow_status"] == "FAIL"
        ):
            send_alert(result)

    return result


def run_single_check(website_id: str) -> dict:
    """Mengecek satu website berdasarkan ID."""

    cfg = load_app_config()
    websites = load_websites()

    selected_site = next(
        (
            site for site in websites
            if site.get("id") == website_id
        ),
        None
    )

    if selected_site is None:
        raise ValueError(
            "Website yang dipilih tidak ditemukan."
        )

    if not selected_site.get("enabled", True):
        raise ValueError(
            "Website sedang nonaktif. "
            "Aktifkan melalui menu Edit Website."
        )

    return check_one_website(selected_site, cfg)


def run_all_checks() -> list:
    """Mengecek seluruh website yang aktif."""

    cfg = load_app_config()
    results = []

    for site in load_websites():

        if not site.get("enabled", True):
            continue

        result = check_one_website(site, cfg)
        results.append(result)

    return results
