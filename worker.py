from apscheduler.schedulers.blocking import BlockingScheduler
from config.settings import load_app_config
from database.db import init_db
from monitoring.monitor import run_all_checks

def job():
    print("Memulai monitoring...")
    results = run_all_checks()
    print(f"Selesai. {len(results)} website diproses.")

if __name__ == "__main__":
    init_db()
    cfg = load_app_config()
    interval = int(cfg.get("monitoring_interval", 300))
    print(f"Worker aktif. Interval: {interval} detik. Tekan Ctrl+C untuk berhenti.")
    job()  # pengecekan langsung saat worker dinyalakan
    scheduler = BlockingScheduler(timezone="Asia/Jakarta")
    scheduler.add_job(job, "interval", seconds=interval, max_instances=1, coalesce=True)
    scheduler.start()
