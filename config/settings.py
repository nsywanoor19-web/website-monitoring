
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def load_json(path, default=None):
    file_path = BASE_DIR / path

    if not file_path.exists():
        return default if default is not None else {}

    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    file_path = BASE_DIR / path
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_app_config():
    return load_json("config.json", {})


def load_websites():
    data = load_json("config/websites.json", {"websites": []})
    return data.get("websites", [])


def save_websites(websites):
    data = {
        "websites": websites
    }

    save_json("config/websites.json", data)
