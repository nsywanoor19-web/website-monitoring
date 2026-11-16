import logging
from pathlib import Path
from config.settings import BASE_DIR

def get_logger():
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "monitoring.log",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8"
    )
    return logging.getLogger("website_monitor")
