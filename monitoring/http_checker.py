import time
import requests

def check_http(url: str, timeout: int = 15) -> dict:
    started = time.perf_counter()
    try:
        response = requests.get(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": "InstansiWebsiteMonitor/1.0"}
        )
        elapsed = time.perf_counter() - started
        return {
            "http_status": response.status_code,
            "response_time": round(elapsed, 3),
            "status": "ONLINE" if response.status_code < 400 else "ERROR",
            "message": f"HTTP {response.status_code}; final URL: {response.url}"
        }
    except requests.RequestException as exc:
        elapsed = time.perf_counter() - started
        return {
            "http_status": None,
            "response_time": round(elapsed, 3),
            "status": "ERROR",
            "message": str(exc)[:500]
        }
