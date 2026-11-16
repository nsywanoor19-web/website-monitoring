"""
Dynamic Synthetic Monitoring & Alert
Single-file Streamlit application.

Install:
    py -m pip install "streamlit>=1.37" requests pandas

Run:
    streamlit run app.py

Synthetic steps use sequential GET requests (read-only). Do not submit real
public-service forms or citizen data without authorization and a test environment.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
TARGETS_FILE = APP_DIR / "targets.json"
DB_FILE = APP_DIR / "monitoring_history.db"

DEFAULT_TARGETS = [{
    "name": "Contoh Website",
    "url": "https://example.com",
    "steps": [],
    "expected_text": "",
    "enabled": True,
}]

st.set_page_config(
    page_title="Dynamic Synthetic Monitoring",
    page_icon="🖥️",
    layout="wide",
)


# -------------------- Penyimpanan konfigurasi --------------------

def load_targets() -> list[dict[str, Any]]:
    if not TARGETS_FILE.exists():
        save_targets(DEFAULT_TARGETS)
        return DEFAULT_TARGETS.copy()
    try:
        with TARGETS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else DEFAULT_TARGETS.copy()
    except (json.JSONDecodeError, OSError):
        st.error("targets.json tidak dapat dibaca. Periksa isi file tersebut.")
        return []


def save_targets(targets: list[dict[str, Any]]) -> None:
    with TARGETS_FILE.open("w", encoding="utf-8") as file:
        json.dump(targets, file, ensure_ascii=False, indent=4)


def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at TEXT NOT NULL,
            target_name TEXT NOT NULL,
            target_url TEXT NOT NULL,
            status TEXT NOT NULL,
            http_code INTEGER,
            response_time_ms REAL,
            flow_time_ms REAL,
            details TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_state (
            target_name TEXT PRIMARY KEY,
            last_sent_epoch REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_log(result: dict[str, Any]) -> None:
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO monitoring_logs
            (checked_at, target_name, target_url, status, http_code,
             response_time_ms, flow_time_ms, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result["checked_at"], result["target_name"], result["target_url"],
            result["status"], result["http_code"], result["response_time_ms"],
            result["flow_time_ms"], result["details"],
        ))
        conn.commit()


def load_history(limit: int = 1000) -> pd.DataFrame:
    with db_connection() as conn:
        df = pd.read_sql_query("""
            SELECT checked_at, target_name, target_url, status, http_code,
                   response_time_ms, flow_time_ms, details
            FROM monitoring_logs
            ORDER BY id DESC LIMIT ?
        """, conn, params=(limit,))
    if not df.empty:
        df["checked_at"] = pd.to_datetime(df["checked_at"], errors="coerce")
    return df


# -------------------- Pemeriksaan HTTP dan synthetic flow --------------------

def valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def check_target(
    target: dict[str, Any],
    timeout_seconds: int,
    slow_threshold_seconds: float,
) -> dict[str, Any]:
    """GET URL utama dan URL langkah berikutnya secara berurutan."""
    checked_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    name = target["name"]
    main_url = target["url"]
    steps = target.get("steps") or []
    expected_text = (target.get("expected_text") or "").strip()

    urls = [main_url] + steps
    details: list[str] = []
    primary_code = None
    primary_time_ms = None
    failed = False
    flow_start = time.perf_counter()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "DPRD-Synthetic-Monitor/1.0 (authorized availability check)"
    })

    try:
        for step_no, url in enumerate(urls, start=1):
            if not valid_url(url):
                failed = True
                details.append(f"Langkah {step_no}: URL tidak valid: {url}")
                break

            request_start = time.perf_counter()
            try:
                response = session.get(
                    url, timeout=timeout_seconds, allow_redirects=True
                )
                elapsed_ms = (time.perf_counter() - request_start) * 1000

                if step_no == 1:
                    primary_code = response.status_code
                    primary_time_ms = elapsed_ms

                if response.status_code >= 400:
                    failed = True
                    details.append(
                        f"Langkah {step_no}: HTTP {response.status_code} — {url}"
                    )
                    break

                if expected_text and expected_text.casefold() not in response.text.casefold():
                    failed = True
                    details.append(
                        f"Langkah {step_no}: teks '{expected_text}' tidak ditemukan — {url}"
                    )
                    break

                details.append(
                    f"Langkah {step_no}: HTTP {response.status_code}, "
                    f"{elapsed_ms:.0f} ms — {url}"
                )

            except requests.RequestException as exc:
                failed = True
                details.append(f"Langkah {step_no}: gagal mengakses {url} — {exc}")
                break
    finally:
        session.close()

    flow_ms = (time.perf_counter() - flow_start) * 1000

    if failed or primary_code is None:
        status = "DOWN"
    elif primary_time_ms is not None and primary_time_ms / 1000 > slow_threshold_seconds:
        status = "SLOW"
    else:
        status = "UP"

    return {
        "checked_at": checked_at,
        "target_name": name,
        "target_url": main_url,
        "status": status,
        "http_code": primary_code,
        "response_time_ms": round(primary_time_ms, 2) if primary_time_ms is not None else None,
        "flow_time_ms": round(flow_ms, 2),
        "details": " | ".join(details),
    }


# -------------------- Telegram alert --------------------

def send_telegram(token: str, chat_id: str, message: str) -> tuple[bool, str]:
    if not token or not chat_id:
        return False, "Bot Token atau Chat ID belum diisi."
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            api_url, data={"chat_id": chat_id, "text": message}, timeout=10
        )
        response.raise_for_status()
        body = response.json()
        if body.get("ok"):
            return True, "Pesan Telegram berhasil dikirim."
        return False, body.get("description", "Telegram menolak permintaan.")
    except requests.RequestException as exc:
        return False, f"Gagal mengirim Telegram: {exc}"


def alert_allowed(target_name: str, cooldown_minutes: int) -> bool:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT last_sent_epoch FROM alert_state WHERE target_name = ?",
            (target_name,),
        ).fetchone()
    return row is None or (time.time() - float(row["last_sent_epoch"])) >= cooldown_minutes * 60


def record_alert(target_name: str) -> None:
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO alert_state (target_name, last_sent_epoch)
            VALUES (?, ?)
            ON CONFLICT(target_name)
            DO UPDATE SET last_sent_epoch = excluded.last_sent_epoch
        """, (target_name, time.time()))
        conn.commit()


def maybe_alert(
    result: dict[str, Any], token: str, chat_id: str, cooldown_minutes: int
) -> str | None:
    if result["status"] == "UP":
        return None
    if not token or not chat_id:
        return "Alert tidak dikirim karena kredensial Telegram belum diisi."
    if not alert_allowed(result["target_name"], cooldown_minutes):
        return f"Alert {result['target_name']} masih dalam masa cooldown."

    message = (
        "⚠️ MONITORING WEBSITE DPRD\n"
        f"Layanan: {result['target_name']}\n"
        f"URL: {result['target_url']}\n"
        f"Waktu: {result['checked_at']}\n"
        f"Status: {result['status']}\n"
        f"HTTP: {result['http_code'] or '-'}\n"
        f"Response time: {result['response_time_ms'] if result['response_time_ms'] is not None else '-'} ms\n"
        f"Keterangan: {result['details']}"
    )
    ok, info = send_telegram(token, chat_id, message)
    if ok:
        record_alert(result["target_name"])
    return info


# -------------------- Jalankan seluruh target --------------------

def run_checks(
    target_list: list[dict[str, Any]],
    timeout_seconds: int,
    slow_threshold_seconds: float,
    token: str,
    chat_id: str,
    cooldown_minutes: int,
) -> list[dict[str, Any]]:
    active = [t for t in target_list if t.get("enabled", True)]
    results = []
    if not active:
        st.warning("Belum ada target aktif.")
        return results

    progress = st.progress(0, text="Memulai pemeriksaan...")
    for number, target in enumerate(active, start=1):
        result = check_target(target, timeout_seconds, slow_threshold_seconds)
        save_log(result)
        alert_info = maybe_alert(result, token, chat_id, cooldown_minutes)
        if alert_info:
            result["alert_info"] = alert_info
        results.append(result)
        progress.progress(number / len(active), text=f"Memeriksa {target['name']}...")
    progress.empty()
    return results


# -------------------- Sidebar dan pengaturan --------------------

targets = load_targets()

st.sidebar.title("⚙️ Pengaturan")
st.sidebar.subheader("Telegram Bot")
telegram_token = st.sidebar.text_input("Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Chat ID")

if st.sidebar.button("Kirim Tes Telegram", use_container_width=True):
    ok, info = send_telegram(
        telegram_token, telegram_chat_id,
        "✅ Tes notifikasi Dynamic Synthetic Monitoring berhasil."
    )
    st.sidebar.success(info) if ok else st.sidebar.error(info)

st.sidebar.divider()
st.sidebar.subheader("Parameter Monitoring")
slow_threshold = st.sidebar.number_input(
    "Ambang response time (detik)", min_value=0.5, max_value=120.0,
    value=5.0, step=0.5
)
timeout_seconds = st.sidebar.number_input(
    "Timeout (detik)", min_value=2, max_value=120, value=15, step=1
)
cooldown_minutes = st.sidebar.number_input(
    "Cooldown alert per layanan (menit)", min_value=1, max_value=1440,
    value=15, step=1
)
auto_interval = st.sidebar.selectbox(
    "Interval auto-check", [60, 120, 300, 600, 900], index=2,
    format_func=lambda sec: f"{sec // 60} menit"
)
auto_enabled = st.sidebar.toggle(
    "Aktifkan auto-check", value=False,
    help="Tab dashboard harus tetap terbuka agar pemeriksaan otomatis berjalan."
)

st.sidebar.divider()
st.sidebar.subheader("Kelola Target Website")
names = [target["name"] for target in targets]
selected_name = st.sidebar.selectbox(
    "Pilih target untuk diubah", ["Tambah target baru"] + names
)
selected = next((t for t in targets if t["name"] == selected_name), None)

with st.sidebar.form("target_form"):
    name_value = st.text_input("Nama layanan", value=selected["name"] if selected else "")
    url_value = st.text_input("URL utama", value=selected["url"] if selected else "")
    steps_value = st.text_area(
        "URL langkah berikutnya (satu URL per baris)",
        value="\n".join(selected.get("steps", [])) if selected else "",
        help="Semua langkah diakses berurutan menggunakan GET/read-only."
    )
    expected_value = st.text_input(
        "Teks yang harus ditemukan (opsional)",
        value=selected.get("expected_text", "") if selected else "",
        help="Teks ini diperiksa pada halaman utama dan setiap langkah."
    )
    enabled_value = st.checkbox(
        "Target aktif", value=selected.get("enabled", True) if selected else True
    )
    save_clicked = st.form_submit_button("Simpan target", use_container_width=True)

if save_clicked:
    clean_name = name_value.strip()
    clean_url = url_value.strip()
    clean_steps = [line.strip() for line in steps_value.splitlines() if line.strip()]
    if not clean_name:
        st.sidebar.error("Nama layanan wajib diisi.")
    elif not valid_url(clean_url):
        st.sidebar.error("URL harus diawali http:// atau https:// dan memiliki hostname.")
    elif any(not valid_url(url) for url in clean_steps):
        st.sidebar.error("Ada URL langkah yang tidak valid.")
    elif any(
        t["name"].casefold() == clean_name.casefold() and t["name"] != selected_name
        for t in targets
    ):
        st.sidebar.error("Nama layanan sudah digunakan.")
    else:
        new_target = {
            "name": clean_name,
            "url": clean_url,
            "steps": clean_steps,
            "expected_text": expected_value.strip(),
            "enabled": enabled_value,
        }
        if selected:
            targets = [
                new_target if t["name"] == selected_name else t for t in targets
            ]
        else:
            targets.append(new_target)
        save_targets(targets)
        st.sidebar.success("Target berhasil disimpan.")
        st.rerun()

if selected and st.sidebar.button("Hapus target terpilih", use_container_width=True):
    targets = [t for t in targets if t["name"] != selected_name]
    save_targets(targets)
    st.rerun()


# -------------------- Dashboard --------------------

st.title("🖥️ Dynamic Synthetic Monitoring & Alert")
st.caption("Pemantauan ketersediaan dan respons layanan web — DPRD Kota Bogor")
st.info(
    "Response time di sini adalah waktu respons dari server ke komputer yang "
    "menjalankan aplikasi monitoring, bukan pengukuran langsung dari HP setiap pengunjung."
)

history = load_history()
latest = (
    history.sort_values("checked_at").groupby("target_name", as_index=False).tail(1)
    if not history.empty else pd.DataFrame()
)
active_count = sum(1 for t in targets if t.get("enabled", True))
up = int((latest["status"] == "UP").sum()) if not latest.empty else 0
slow = int((latest["status"] == "SLOW").sum()) if not latest.empty else 0
down = int((latest["status"] == "DOWN").sum()) if not latest.empty else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Target aktif", active_count)
c2.metric("Status UP", up)
c3.metric("Status SLOW", slow)
c4.metric("Status DOWN", down)
st.divider()

if hasattr(st, "fragment"):
    @st.fragment(run_every=auto_interval if auto_enabled else None)
    def monitoring_panel():
        col1, col2 = st.columns([1, 3])
        with col1:
            clicked = st.button("▶️ Uji Sekarang", type="primary", use_container_width=True)
        if clicked or auto_enabled:
            with st.spinner("Sedang memeriksa target..."):
                results = run_checks(
                    targets, int(timeout_seconds), float(slow_threshold),
                    telegram_token, telegram_chat_id, int(cooldown_minutes)
                )
            if results:
                st.success(f"Pemeriksaan selesai: {len(results)} target.")
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
        else:
            with col2:
                st.caption("Klik Uji Sekarang untuk pengecekan manual atau aktifkan auto-check di sidebar.")
    monitoring_panel()
else:
    st.warning("Auto-check membutuhkan Streamlit 1.37+. Perbarui Streamlit terlebih dahulu.")
    if st.button("▶️ Uji Sekarang", type="primary"):
        results = run_checks(
            targets, int(timeout_seconds), float(slow_threshold),
            telegram_token, telegram_chat_id, int(cooldown_minutes)
        )
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

history = load_history()
st.subheader("📈 Grafik Response Time")
if history.empty:
    st.caption("Belum ada riwayat. Jalankan pengecekan pertama.")
else:
    chart_df = history.dropna(subset=["response_time_ms"]).sort_values("checked_at").copy()
    if chart_df.empty:
        st.caption("Belum ada data response time.")
    else:
        chart_df["Waktu"] = chart_df["checked_at"].dt.strftime("%d/%m %H:%M:%S")
        pivot = chart_df.pivot_table(
            index="Waktu", columns="target_name",
            values="response_time_ms", aggfunc="last"
        )
        st.line_chart(pivot, y_label="Response time (ms)")

st.subheader("🧾 Log Riwayat Pemeriksaan")
if history.empty:
    st.caption("Log pemeriksaan akan tampil di sini.")
else:
    shown = history.copy()
    shown["checked_at"] = shown["checked_at"].dt.strftime("%Y-%m-%d %H:%M:%S %z")
    shown = shown.rename(columns={
        "checked_at": "Waktu",
        "target_name": "Nama Layanan",
        "target_url": "URL",
        "status": "Status",
        "http_code": "HTTP Code",
        "response_time_ms": "Response Time (ms)",
        "flow_time_ms": "Total Flow (ms)",
        "details": "Keterangan",
    })
    st.dataframe(shown, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Unduh riwayat CSV",
        data=history.to_csv(index=False).encode("utf-8-sig"),
        file_name="riwayat_monitoring.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "File lokal yang dibuat otomatis: targets.json dan monitoring_history.db. "
    "Auto-check berjalan selama aplikasi dan tab dashboard tetap aktif."
)
