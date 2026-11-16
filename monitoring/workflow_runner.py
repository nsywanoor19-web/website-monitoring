import time
from playwright.sync_api import sync_playwright


def run_workflow(steps: list, timeout_ms: int = 15000) -> dict:
    """
    Menjalankan simulasi aktivitas pengguna pada website.

    Actions:
    open, fill, click, check_text, check_visible,
    check_enabled, check_url, check_title, wait,
    wait_for_url.
    """

    if not steps:
        return {
            "status": "SKIPPED",
            "message": "Workflow kosong.",
            "duration": 0,
            "page_load_time": None,
            "final_url": None,
            "page_title": None,
            "steps": []
        }

    started = time.perf_counter()
    step_results = []

    page_load_time = None
    final_url = None
    page_title = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)

                for index, step in enumerate(steps, start=1):
                    action = step.get("action")
                    step_started = time.perf_counter()

                    try:
                        if action == "open":
                            navigation_started = time.perf_counter()

                            page.goto(
                                step["url"],
                                wait_until=step.get("wait_until", "load"),
                                timeout=timeout_ms
                            )

                            page_load_time = round(
                                time.perf_counter() - navigation_started,
                                3
                            )

                            final_url = page.url
                            page_title = page.title()

                        elif action == "fill":
                            page.locator(
                                step["selector"]
                            ).fill(
                                str(step.get("value", ""))
                            )

                        elif action == "click":
                            page.locator(
                                step["selector"]
                            ).click()

                            final_url = page.url
                            page_title = page.title()

                        elif action == "check_text":
                            expected_text = step["text"]
                            actual_text = page.locator("body").inner_text()

                            if expected_text not in actual_text:
                                raise AssertionError(
                                    f"Teks tidak ditemukan: {expected_text}"
                                )

                        elif action == "check_visible":
                            locator = page.locator(step["selector"])

                            if not locator.is_visible():
                                raise AssertionError(
                                    f"Elemen tidak terlihat: {step['selector']}"
                                )

                        elif action == "check_enabled":
                            locator = page.locator(step["selector"])

                            if not locator.is_enabled():
                                raise AssertionError(
                                    f"Elemen tidak aktif: {step['selector']}"
                                )

                        elif action == "check_url":
                            expected_url = step["url"]

                            if expected_url not in page.url:
                                raise AssertionError(
                                    f"URL tidak sesuai. URL saat ini: {page.url}"
                                )

                        elif action == "check_title":
                            expected_title = step["title"]
                            actual_title = page.title()

                            if expected_title not in actual_title:
                                raise AssertionError(
                                    "Judul halaman tidak sesuai. "
                                    f"Judul saat ini: {actual_title}"
                                )

                        elif action == "wait":
                            page.wait_for_timeout(
                                int(step.get("milliseconds", 1000))
                            )

                        elif action == "wait_for_url":
                            page.wait_for_url(
                                step["url"],
                                timeout=timeout_ms
                            )

                            final_url = page.url
                            page_title = page.title()

                        else:
                            raise ValueError(
                                f"Action tidak dikenal: {action}"
                            )

                        duration = round(
                            time.perf_counter() - step_started,
                            3
                        )

                        step_results.append({
                            "step": index,
                            "action": action,
                            "status": "PASS",
                            "duration": duration,
                            "message": "Berhasil"
                        })

                    except Exception as exc:
                        duration = round(
                            time.perf_counter() - step_started,
                            3
                        )

                        step_results.append({
                            "step": index,
                            "action": action,
                            "status": "FAIL",
                            "duration": duration,
                            "message": str(exc)[:300]
                        })

                        raise

                total_duration = round(
                    time.perf_counter() - started,
                    3
                )

                final_url = page.url
                page_title = page.title()

                return {
                    "status": "PASS",
                    "message": "Semua langkah berhasil.",
                    "duration": total_duration,
                    "page_load_time": page_load_time,
                    "final_url": final_url,
                    "page_title": page_title,
                    "steps": step_results
                }

            finally:
                browser.close()

    except Exception as exc:
        total_duration = round(
            time.perf_counter() - started,
            3
        )

        return {
            "status": "FAIL",
            "message": str(exc)[:500],
            "duration": total_duration,
            "page_load_time": page_load_time,
            "final_url": final_url,
            "page_title": page_title,
            "steps": step_results
        }