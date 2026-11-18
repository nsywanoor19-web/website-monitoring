import json
import uuid
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import math

from config.settings import load_app_config, load_websites, save_websites
from database.db import (
    get_history,
    get_latest_results,
    get_summary,
    init_db,
)
from monitoring.monitor import run_all_checks, run_single_check
from notifications.telegram_bot import send_test_message


# =========================================================
# KONFIGURASI HALAMAN
# =========================================================

st.set_page_config(
    page_title="Website Monitoring",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()
cfg = load_app_config()


# =========================================================
# STYLE
# =========================================================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.7rem;
        padding-bottom: 2.5rem;
        max-width: 1500px;
    }

    [data-testid="stSidebar"] {
        border-right: 1px solid rgba(128, 128, 128, 0.18);
    }

    [data-testid="stSidebar"] .block-container {
        padding-top: 1.5rem;
    }

    .main-header {
        padding: 1.25rem 1.4rem;
        border: 1px solid rgba(128, 128, 128, 0.20);
        border-radius: 16px;
        margin-bottom: 1.2rem;
        background: linear-gradient(
            115deg,
            rgba(40, 110, 180, 0.15),
            rgba(40, 110, 180, 0.035)
        );
    }

    .main-header h1 {
        margin: 0;
        padding: 0;
        font-size: 2rem;
        font-weight: 750;
        letter-spacing: -0.035em;
    }

    .main-header p {
        margin: 0.45rem 0 0 0;
        opacity: 0.72;
        font-size: 0.96rem;
    }

    .section-heading {
        font-size: 1.15rem;
        font-weight: 700;
        margin: 0.35rem 0 0.7rem 0;
    }

    div[data-testid="stMetric"] {
        border: 1px solid rgba(128, 128, 128, 0.20);
        padding: 0.9rem 1rem;
        border-radius: 13px;
        background: rgba(128, 128, 128, 0.045);
    }

    div[data-testid="stMetricLabel"] {
        font-weight: 600;
    }

    div[data-testid="stTabs"] button {
        font-weight: 600;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(128, 128, 128, 0.16);
        border-radius: 10px;
        overflow: hidden;
    }

    .small-note {
        opacity: 0.68;
        font-size: 0.86rem;
    }

    div.stButton > button,
    div.stFormSubmitButton > button {
        border-radius: 9px;
        font-weight: 600;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# FUNGSI BANTU
# =========================================================

def valid_url(url: str) -> bool:
    """Memastikan URL menggunakan HTTP/HTTPS dan memiliki hostname."""
    try:
        parsed = urlparse(url.strip())
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and "." in parsed.netloc
        )
    except Exception:
        return False


def as_float(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def display_seconds(value):
    number = as_float(value)
    return f"{number:.2f} s" if number is not None else "-"


def format_check_time(value):
    """Mengubah timestamp ISO menjadi format tanggal yang mudah dibaca."""
    if value is None or pd.isna(value):
        return "-"
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return str(value)
    return timestamp.strftime("%d %b %Y, %H:%M:%S")


def prepare_history_dataframe(rows):
    """Menyiapkan riwayat: terbaru di atas dan timestamp sudah diformat."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if "checked_at" in df.columns:
        df["_sort_time"] = pd.to_datetime(df["checked_at"], errors="coerce", utc=True)
        df = df.sort_values("_sort_time", ascending=False, na_position="last")
        df["checked_at"] = df["checked_at"].apply(format_check_time)
        df = df.drop(columns=["_sort_time"])
    return df.reset_index(drop=True)


def create_excel_file(dataframe):
    """Membuat file Excel di memori tanpa menyimpan database ke disk."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Riwayat Monitoring")
        worksheet = writer.sheets["Riwayat Monitoring"]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for column_cells in worksheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 42)
    output.seek(0)
    return output.getvalue()


def is_local_test_url(url: str) -> bool:
    """Pengujian beban dibatasi ke localhost agar tidak membebani situs publik."""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        return parsed.scheme in ("http", "https") and host in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


def execute_http_load(url: str, concurrent_users: int, requests_per_user: int, timeout: int = 10):
    """Menjalankan pengujian HTTP lokal dengan sejumlah pengguna virtual."""
    def virtual_user(user_number):
        results = []
        for request_number in range(requests_per_user):
            started = time.perf_counter()
            try:
                response = requests.get(
                    url,
                    timeout=timeout,
                    headers={"User-Agent": "WebsiteMonitoring-LocalLoadTest/1.0"},
                )
                elapsed = time.perf_counter() - started
                results.append({
                    "user": user_number,
                    "request": request_number + 1,
                    "success": 200 <= response.status_code < 400,
                    "http_status": response.status_code,
                    "response_time": elapsed,
                    "error": "" if 200 <= response.status_code < 400 else f"HTTP {response.status_code}",
                })
            except requests.RequestException as exc:
                elapsed = time.perf_counter() - started
                results.append({
                    "user": user_number,
                    "request": request_number + 1,
                    "success": False,
                    "http_status": None,
                    "response_time": elapsed,
                    "error": str(exc)[:180],
                })
        return results

    started_all = time.perf_counter()
    all_results = []
    with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        futures = [executor.submit(virtual_user, user) for user in range(1, concurrent_users + 1)]
        for future in as_completed(futures):
            all_results.extend(future.result())
    total_duration = time.perf_counter() - started_all

    response_times = [item["response_time"] for item in all_results]
    success_count = sum(1 for item in all_results if item["success"])
    failed_count = len(all_results) - success_count
    sorted_times = sorted(response_times)
    p95_index = min(
        len(sorted_times) - 1,
        max(0, math.ceil(0.95 * len(sorted_times)) - 1)
    ) if sorted_times else 0

    cpu_percent = None
    memory_percent = None
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.2)
        memory_percent = psutil.virtual_memory().percent
    except ImportError:
        pass

    summary_row = {
        "Waktu Pengujian": pd.Timestamp.now().strftime("%d %b %Y, %H:%M:%S"),
        "Pengguna Bersamaan": concurrent_users,
        "Total Request": len(all_results),
        "Berhasil": success_count,
        "Gagal": failed_count,
        "Rata-rata Response (s)": statistics.mean(response_times) if response_times else 0,
        "P95 Response (s)": sorted_times[p95_index] if sorted_times else 0,
        "Durasi Total (s)": total_duration,
        "Throughput (req/s)": len(all_results) / total_duration if total_duration else 0,
        "Error Rate (%)": (failed_count / len(all_results) * 100) if all_results else 0,
        "CPU (%)": cpu_percent,
        "RAM (%)": memory_percent,
    }
    return summary_row, all_results


def normalize_steps(raw_steps):
    """Mengubah data workflow dari JSON/list menjadi list of dict."""
    if isinstance(raw_steps, str):
        try:
            raw_steps = json.loads(raw_steps)
        except (json.JSONDecodeError, TypeError):
            return []

    if isinstance(raw_steps, dict):
        raw_steps = [raw_steps]

    if not isinstance(raw_steps, list):
        return []

    return [step for step in raw_steps if isinstance(step, dict)]


def show_workflow_details(rows):
    """Menampilkan hanya detail workflow yang benar-benar tersedia."""
    workflow_rows = []

    for row in rows:
        steps = normalize_steps(row.get("workflow_steps", []))
        if steps:
            workflow_rows.append((row.get("website_name", "Website"), steps))

    if not workflow_rows:
        st.info(
            "Belum ada detail langkah workflow yang tersimpan. "
            "Detail akan muncul setelah website dengan workflow aktif diperiksa."
        )
        return

    for website_name, steps in workflow_rows:
        with st.expander(f"Detail workflow — {website_name}", expanded=False):
            step_df = pd.DataFrame(steps)
            st.dataframe(
                step_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "step": "Langkah",
                    "action": "Aksi",
                    "status": "Hasil",
                    "duration": st.column_config.NumberColumn(
                        "Durasi (detik)", format="%.2f"
                    ),
                    "message": "Keterangan",
                },
            )


def make_display_dataframe(rows, columns, labels):
    df = pd.DataFrame(rows)
    available = [column for column in columns if column in df.columns]
    if df.empty or not available:
        return pd.DataFrame()
    return df[available].rename(columns=labels)


# =========================================================
# HEADER
# =========================================================

st.markdown(
    """
    <div class="main-header">
        <h1>🌐 Website Monitoring</h1>
        <p>
            Pemantauan ketersediaan website, waktu respons HTTP,
            dan simulasi alur pengguna melalui browser.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# SIDEBAR — KONTROL MONITORING
# =========================================================

with st.sidebar:
    st.markdown("## ⚙️ Kontrol Monitoring")
    interval = cfg.get("monitoring_interval", 300)
    st.caption(f"Interval worker: setiap {interval} detik")

    if st.button(
        "▶ Jalankan Semua Pengecekan",
        use_container_width=True,
        key="btn_run_all_monitoring",
    ):
        with st.spinner("Memeriksa seluruh website aktif..."):
            try:
                results = run_all_checks()
                st.success(f"Pengecekan selesai. {len(results)} website diproses.")
                st.rerun()
            except Exception as exc:
                st.error(f"Monitoring gagal: {exc}")

    st.divider()
    st.markdown("### 🔎 Cek Website Tertentu")

    active_websites = [
        site for site in load_websites()
        if site.get("enabled", True)
    ]

    if active_websites:
        website_options = {
            site["id"]: site["name"] for site in active_websites
        }

        selected_website_id = st.selectbox(
            "Pilih website",
            options=list(website_options.keys()),
            format_func=lambda site_id: website_options[site_id],
            key="single_website_selector",
        )

        if st.button(
            "Periksa Website Terpilih",
            use_container_width=True,
            key="btn_run_single_monitoring",
        ):
            with st.spinner("Sedang memeriksa website..."):
                try:
                    result = run_single_check(selected_website_id)
                    st.session_state["last_single_result"] = result
                    st.success(
                        f"Pengecekan {result.get('website_name', 'website')} selesai. "
                        "Hasil ditampilkan pada tab Dashboard."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gagal memeriksa website: {exc}")
    else:
        st.info("Belum ada website aktif.")

    st.divider()
    st.markdown("### 📨 Notifikasi")

    if st.button(
        "Tes Notifikasi Telegram",
        use_container_width=True,
        key="btn_test_telegram",
    ):
        try:
            success, message = send_test_message()
            if success:
                st.success(message)
            else:
                st.error(message)
        except Exception as exc:
            st.error(f"Gagal mengirim tes Telegram: {exc}")

    st.divider()
    st.caption(
        "Monitoring berkala dijalankan melalui worker.py "
        "pada terminal terpisah."
    )


# =========================================================
# DATA TERBARU
# =========================================================

summary = get_summary()
latest = get_latest_results()
history = get_history(limit=500)

# Urutkan data terbaru ke terlama agar waktu pengecekan mudah dibaca.
latest = sorted(
    latest,
    key=lambda row: pd.to_datetime(row.get("checked_at"), errors="coerce", utc=True),
    reverse=True,
) if latest else []
history_display_df = prepare_history_dataframe(history)
registered_websites = load_websites()


# =========================================================
# NAVIGASI UTAMA
# =========================================================

tab_dashboard, tab_websites, tab_history, tab_performance = st.tabs(
    ["📊 Dashboard", "🖥️ Kelola Website", "🧾 Riwayat Pengujian", "🧪 Uji Performa"]
)


# =========================================================
# TAB 1 — DASHBOARD
# =========================================================

with tab_dashboard:
    st.markdown("## Ringkasan Monitoring")
    st.caption("Gambaran kondisi website berdasarkan hasil pemeriksaan terakhir.")

    last_result = st.session_state.get("last_single_result")
    if last_result:
        with st.container(border=True):
            result_title = last_result.get("website_name", "Website")
            st.markdown(f"#### Hasil pengecekan terakhir — {result_title}")
            result_cols = st.columns(5)
            result_cols[0].metric("Status", last_result.get("status", "-"))
            result_cols[1].metric("HTTP", last_result.get("http_status", "-"))
            result_cols[2].metric("HTTP response", display_seconds(last_result.get("response_time")))
            result_cols[3].metric("Page load", display_seconds(last_result.get("page_load_time")))
            result_cols[4].metric("Workflow", last_result.get("workflow_status", "SKIPPED"))
            st.caption(last_result.get("message", ""))
            last_steps = normalize_steps(last_result.get("workflow_steps", []))
            if last_steps:
                with st.expander("Lihat detail langkah workflow"):
                    st.dataframe(pd.DataFrame(last_steps), use_container_width=True, hide_index=True)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Total Website", summary.get("total", 0))
    metric_cols[1].metric("Online", summary.get("online", 0))
    metric_cols[2].metric("Error / Lambat", summary.get("error", 0))
    metric_cols[3].metric(
        "Rata-rata Respons HTTP",
        display_seconds(summary.get("avg_response")),
    )

    extra_cols = st.columns(2)
    extra_cols[0].metric(
        "Rata-rata Page Load",
        display_seconds(summary.get("avg_page_load")),
    )
    extra_cols[1].metric(
        "Rata-rata Durasi Workflow",
        display_seconds(summary.get("avg_workflow")),
    )

    st.divider()
    st.markdown("### Status Website Terbaru")

    if latest:
        latest_columns = [
            "website_name",
            "checked_at",
            "http_status",
            "response_time",
            "status",
            "page_load_time",
            "workflow_duration",
            "workflow_status",
            "message",
        ]
        latest_labels = {
            "website_name": "Nama Website",
            "checked_at": "Waktu Pengecekan",
            "http_status": "HTTP",
            "response_time": "Response (s)",
            "status": "Status HTTP",
            "page_load_time": "Page Load (s)",
            "workflow_duration": "Workflow (s)",
            "workflow_status": "Status Workflow",
            "message": "Keterangan",
        }

        latest_df = make_display_dataframe(latest, latest_columns, latest_labels)
        if "Waktu Pengecekan" in latest_df.columns:
            latest_df["Waktu Pengecekan"] = latest_df["Waktu Pengecekan"].apply(format_check_time)
        st.dataframe(
            latest_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Response (s)": st.column_config.NumberColumn(format="%.2f"),
                "Page Load (s)": st.column_config.NumberColumn(format="%.2f"),
                "Workflow (s)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        st.markdown("### Detail Workflow Terbaru")
        show_workflow_details(latest)
    else:
        st.info(
            "Belum ada hasil monitoring. Tambahkan website, "
            "kemudian jalankan pengecekan pertama."
        )

    st.divider()
    st.markdown("### Grafik Response Time")

    if history:
        hist_df = pd.DataFrame(history)
        if {"checked_at", "response_time", "website_name"}.issubset(hist_df.columns):
            hist_df["checked_at"] = pd.to_datetime(
                hist_df["checked_at"], errors="coerce"
            )
            hist_df["response_time"] = pd.to_numeric(
                hist_df["response_time"], errors="coerce"
            )
            hist_df = hist_df.dropna(
                subset=["checked_at", "response_time"]
            ).sort_values("checked_at")

            if not hist_df.empty:
                fig = px.line(
                    hist_df,
                    x="checked_at",
                    y="response_time",
                    color="website_name",
                    markers=True,
                    labels={
                        "checked_at": "Waktu Pengecekan",
                        "response_time": "Response Time (detik)",
                        "website_name": "Website",
                    },
                )
                fig.update_layout(
                    height=390,
                    margin=dict(l=15, r=15, t=25, b=15),
                    legend_title_text="Website",
                    hovermode="x unified",
                )
                fig.update_traces(line=dict(width=2.5), marker=dict(size=6))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Belum ada data response time yang dapat digambarkan.")
        else:
            st.info("Data riwayat belum memiliki kolom yang diperlukan untuk grafik.")
    else:
        st.info("Grafik akan muncul setelah pengecekan pertama.")


# =========================================================
# TAB 2 — KELOLA WEBSITE
# =========================================================

with tab_websites:
    st.markdown("## Pengelolaan Website")
    st.caption(
        "Tambahkan website baru, ubah pengaturan, atau hapus website "
        "dari daftar pemantauan."
    )

    add_tab, edit_tab, delete_tab = st.tabs(
        ["➕ Tambah", "✏️ Edit", "🗑️ Hapus"]
    )

    with add_tab:
        st.markdown("### Tambahkan Website Baru")
        with st.form("add_website_form", clear_on_submit=True):
            new_name = st.text_input(
                "Nama Website",
                placeholder="Contoh: Website DPRD Kota Bogor",
            )
            new_url = st.text_input(
                "Alamat Website (URL)",
                placeholder="https://contoh.go.id",
            )
            new_threshold = st.number_input(
                "Batas respons lambat (detik)",
                min_value=0.1,
                max_value=300.0,
                value=5.0,
                step=0.5,
            )
            new_enabled = st.checkbox("Aktifkan monitoring", value=True)
            add_submit = st.form_submit_button(
                "Simpan Website",
                use_container_width=True,
            )

            if add_submit:
                if not new_name.strip():
                    st.error("Nama website harus diisi.")
                elif not valid_url(new_url):
                    st.error(
                        "URL tidak valid. Gunakan alamat yang diawali "
                        "http:// atau https://."
                    )
                else:
                    website_data = load_websites()
                    new_website = {
                        "id": "website_" + uuid.uuid4().hex[:12],
                        "name": new_name.strip(),
                        "url": new_url.strip(),
                        "enabled": new_enabled,
                        "threshold_seconds": float(new_threshold),
                        "workflow_enabled": True,
                        "workflow": [
                            {
                                "action": "open",
                                "url": new_url.strip(),
                                "wait_until": "load"
                            }
                        ],
                    }
                    website_data.append(new_website)
                    save_websites(website_data)
                    st.success(f"Website '{new_name}' berhasil ditambahkan.")
                    st.rerun()

    with edit_tab:
        st.markdown("### Ubah Pengaturan Website")
        current_websites = load_websites()

        if not current_websites:
            st.info("Belum ada website yang dapat diedit.")
        else:
            website_map = {
                site["id"]: site for site in current_websites
            }
            selected_edit_id = st.selectbox(
                "Pilih website",
                options=list(website_map.keys()),
                format_func=lambda site_id: website_map[site_id]["name"],
                key="edit_website_selector",
            )
            selected_site = website_map[selected_edit_id]

            with st.form("edit_website_form"):
                edit_name = st.text_input(
                    "Nama Website",
                    value=selected_site.get("name", ""),
                )
                edit_url = st.text_input(
                    "Alamat Website (URL)",
                    value=selected_site.get("url", ""),
                )
                edit_threshold = st.number_input(
                    "Batas respons lambat (detik)",
                    min_value=0.1,
                    max_value=300.0,
                    value=float(selected_site.get("threshold_seconds", 5)),
                    step=0.5,
                )
                edit_enabled = st.checkbox(
                    "Aktifkan monitoring",
                    value=selected_site.get("enabled", True),
                )
                edit_submit = st.form_submit_button(
                    "Simpan Perubahan",
                    use_container_width=True,
                )

                if edit_submit:
                    if not edit_name.strip():
                        st.error("Nama website harus diisi.")
                    elif not valid_url(edit_url):
                        st.error("URL website tidak valid.")
                    else:
                        updated_websites = load_websites()
                        for site in updated_websites:
                            if site["id"] == selected_edit_id:
                                site["name"] = edit_name.strip()
                                site["url"] = edit_url.strip()
                                site["threshold_seconds"] = float(edit_threshold)
                                site["enabled"] = edit_enabled
                                break

                        save_websites(updated_websites)
                        st.success("Pengaturan website berhasil diperbarui.")
                        st.rerun()

    with delete_tab:
        st.markdown("### Hapus Website")
        current_websites = load_websites()

        if not current_websites:
            st.info("Belum ada website yang dapat dihapus.")
        else:
            website_map = {
                site["id"]: site for site in current_websites
            }
            selected_delete_id = st.selectbox(
                "Pilih website yang akan dihapus",
                options=list(website_map.keys()),
                format_func=lambda site_id: website_map[site_id]["name"],
                key="delete_website_selector",
            )
            selected_delete_site = website_map[selected_delete_id]
            st.warning(
                f"Website yang dipilih: **{selected_delete_site['name']}**"
            )

            with st.form("delete_website_form"):
                confirm_delete = st.checkbox(
                    "Saya yakin ingin menghapus website ini."
                )
                delete_submit = st.form_submit_button(
                    "Hapus Website",
                    use_container_width=True,
                )

                if delete_submit:
                    if not confirm_delete:
                        st.error("Centang konfirmasi sebelum menghapus.")
                    else:
                        updated_websites = [
                            site for site in load_websites()
                            if site["id"] != selected_delete_id
                        ]
                        save_websites(updated_websites)
                        st.success(
                            "Website berhasil dihapus dari daftar monitoring."
                        )
                        st.info(
                            "Riwayat monitoring sebelumnya tetap tersimpan "
                            "di database."
                        )
                        st.rerun()

    st.divider()
    st.markdown("### Daftar Website Terdaftar")

    registered_websites = load_websites()
    if registered_websites:
        website_table = []
        for site in registered_websites:
            website_table.append(
                {
                    "Nama Website": site.get("name", "-"),
                    "URL": site.get("url", "-"),
                    "Status": (
                        "Aktif" if site.get("enabled", True) else "Nonaktif"
                    ),
                    "Batas Respons (detik)": site.get(
                        "threshold_seconds", 5
                    ),
                }
            )

        st.dataframe(
            pd.DataFrame(website_table),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Batas Respons (detik)": st.column_config.NumberColumn(
                    format="%.1f"
                )
            },
        )
    else:
        st.info("Belum ada website terdaftar.")


# =========================================================
# TAB 3 — RIWAYAT PENGUJIAN
# =========================================================

with tab_history:
    st.markdown("## Riwayat Pengujian")
    st.caption(
        "Catatan hasil pemeriksaan sebelumnya untuk membantu "
        "menganalisis perubahan performa website."
    )

    if not history_display_df.empty:
        # Filter agar riwayat lebih mudah ditelusuri.
        filter_col1, filter_col2 = st.columns([2, 1])
        website_names = ["Semua Website"]
        if "website_name" in history_display_df.columns:
            website_names += sorted(history_display_df["website_name"].dropna().astype(str).unique().tolist())
        selected_history_website = filter_col1.selectbox(
            "Filter website", website_names, key="history_website_filter"
        )
        search_text = filter_col2.text_input(
            "Cari status / keterangan", placeholder="Contoh: ONLINE", key="history_search"
        )

        filtered_df = history_display_df.copy()
        if selected_history_website != "Semua Website" and "website_name" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["website_name"] == selected_history_website]
        if search_text.strip():
            searchable = filtered_df.astype(str).apply(
                lambda column: column.str.contains(search_text.strip(), case=False, na=False)
            ).any(axis=1)
            filtered_df = filtered_df[searchable]

        history_columns = [
            "website_name", "checked_at", "http_status", "response_time",
            "status", "page_load_time", "workflow_duration", "workflow_status",
            "workflow_message",
        ]
        history_labels = {
            "website_name": "Nama Website",
            "checked_at": "Waktu Pengecekan",
            "http_status": "HTTP",
            "response_time": "Response (s)",
            "status": "Status HTTP",
            "page_load_time": "Page Load (s)",
            "workflow_duration": "Workflow (s)",
            "workflow_status": "Status Workflow",
            "workflow_message": "Keterangan Workflow",
        }
        available_columns = [column for column in history_columns if column in filtered_df.columns]
        display_df = filtered_df[available_columns].rename(columns=history_labels)

        st.caption(f"Menampilkan {len(display_df)} dari {len(history_display_df)} catatan. Urutan: terbaru ke terlama.")
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Response (s)": st.column_config.NumberColumn(format="%.2f"),
                "Page Load (s)": st.column_config.NumberColumn(format="%.2f"),
                "Workflow (s)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        st.markdown("### Unduh Data Riwayat")
        st.caption("Unduh data sesuai filter yang sedang dipilih. File berisi catatan monitoring, bukan data rahasia konfigurasi.")
        export_df = filtered_df.copy()
        export_df = export_df.rename(columns=history_labels)
        export_csv = export_df.to_csv(index=False).encode("utf-8-sig")
        download_col1, download_col2, download_col3 = st.columns([1, 1, 2])
        download_col1.download_button(
            "⬇️ Unduh CSV",
            data=export_csv,
            file_name="riwayat_monitoring.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_history_csv",
        )
        try:
            excel_bytes = create_excel_file(export_df)
            download_col2.download_button(
                "⬇️ Unduh Excel",
                data=excel_bytes,
                file_name="riwayat_monitoring.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_history_excel",
            )
        except ImportError:
            download_col2.warning("Ekspor Excel membutuhkan openpyxl. Jalankan: pip install openpyxl")

        with st.expander("Lihat informasi teknis tambahan", expanded=False):
            extra_columns = ["workflow_final_url", "workflow_page_title", "workflow_message"]
            available_extra = [column for column in extra_columns if column in filtered_df.columns]
            if available_extra:
                extra_df = filtered_df[available_extra].rename(
                    columns={
                        "workflow_final_url": "URL Akhir",
                        "workflow_page_title": "Judul Halaman",
                        "workflow_message": "Keterangan Workflow",
                    }
                )
                st.dataframe(extra_df, use_container_width=True, hide_index=True)
            else:
                st.caption("Belum ada informasi teknis tambahan.")
    else:
        st.info("Belum ada riwayat pengujian.")

    st.divider()
    st.caption(
        "HTTP Check mengukur respons endpoint website. "
        "Workflow browser mengukur keberhasilan langkah interaksi "
        "yang dikonfigurasi."
    )



# =========================================================
# TAB 4 — LOAD TESTING & STRESS TESTING
# =========================================================

with tab_performance:
    st.markdown("## Pengujian Performa Aplikasi")
    st.caption(
        "Pengujian HTTP untuk mengamati respons aplikasi lokal ketika menerima "
        "permintaan secara bersamaan."
    )

    st.warning(
        "Demi keamanan, pengujian dibatasi ke localhost (127.0.0.1 / localhost). "
        "Jangan arahkan pengujian beban ke website publik seperti SKM atau DPRD "
        "tanpa izin tertulis."
    )

    test_url = st.text_input(
        "URL aplikasi lokal yang diuji",
        value="http://127.0.0.1:8501",
        help="Gunakan alamat aplikasi yang sedang berjalan di komputer ini. Sesuaikan port jika Streamlit memakai port lain.",
        key="performance_test_url",
    )

    load_col1, load_col2 = st.columns(2)
    with load_col1:
        st.markdown("### Load Testing")
        load_users = st.number_input(
            "Pengguna virtual bersamaan",
            min_value=1,
            max_value=20,
            value=5,
            step=1,
            key="load_users",
        )
        load_requests = st.number_input(
            "Request per pengguna",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="load_requests",
        )
        st.caption("Mengukur respons saat beban normal yang ditentukan diberikan secara bersamaan.")
        run_load = st.button("Jalankan Load Testing", use_container_width=True, key="run_load_test")

    with load_col2:
        st.markdown("### Stress Testing")
        st.caption("Menaikkan jumlah pengguna virtual secara bertahap untuk melihat perubahan respons dan kegagalan.")
        stress_start = st.selectbox("Mulai dari pengguna", [1, 2, 3], index=0, key="stress_start")
        stress_max = st.selectbox("Batas pengguna", [4, 6, 8, 10, 12, 16], index=2, key="stress_max")
        stress_requests = st.number_input(
            "Request per pengguna pada setiap tahap",
            min_value=1,
            max_value=5,
            value=2,
            step=1,
            key="stress_requests",
        )
        run_stress = st.button("Jalankan Stress Testing", use_container_width=True, key="run_stress_test")

    if run_load or run_stress:
        if not is_local_test_url(test_url):
            st.error("URL pengujian harus menggunakan localhost atau 127.0.0.1.")
        elif run_stress and stress_max < stress_start:
            st.error("Batas pengguna harus lebih besar atau sama dengan jumlah pengguna awal.")
        else:
            all_summaries = []
            all_details = []
            if run_load:
                stages = [int(load_users)]
                mode = "Load Testing"
                per_user = int(load_requests)
            else:
                stages = []
                current = int(stress_start)
                while current < int(stress_max):
                    stages.append(current)
                    current *= 2
                stages.append(int(stress_max))
                stages = sorted(set(stages))
                mode = "Stress Testing"
                per_user = int(stress_requests)

            progress = st.progress(0, text="Menyiapkan pengujian...")
            for index, users in enumerate(stages, start=1):
                progress.progress((index - 1) / len(stages), text=f"Menguji {users} pengguna bersamaan...")
                summary_row, detail_rows = execute_http_load(
                    test_url.strip(), users, per_user
                )
                summary_row["Jenis Pengujian"] = mode
                all_summaries.append(summary_row)
                for detail in detail_rows:
                    detail["Jenis Pengujian"] = mode
                    detail["Pengguna Bersamaan"] = users
                all_details.extend(detail_rows)
            progress.progress(1.0, text="Pengujian selesai.")
            st.session_state["performance_summary"] = all_summaries
            st.session_state["performance_details"] = all_details
            st.session_state["performance_mode"] = mode

    saved_summary = st.session_state.get("performance_summary", [])
    saved_details = st.session_state.get("performance_details", [])
    if saved_summary:
        st.divider()
        st.markdown(f"### Hasil {st.session_state.get('performance_mode', 'Pengujian')}")
        results_df = pd.DataFrame(saved_summary)
        st.dataframe(
            results_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rata-rata Response (s)": st.column_config.NumberColumn(format="%.3f"),
                "P95 Response (s)": st.column_config.NumberColumn(format="%.3f"),
                "Durasi Total (s)": st.column_config.NumberColumn(format="%.3f"),
                "Throughput (req/s)": st.column_config.NumberColumn(format="%.2f"),
                "Error Rate (%)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        if len(results_df) > 1:
            chart_df = results_df[["Pengguna Bersamaan", "Rata-rata Response (s)", "P95 Response (s)"]].melt(
                id_vars="Pengguna Bersamaan", var_name="Metrik", value_name="Detik"
            )
            fig = px.line(
                chart_df,
                x="Pengguna Bersamaan",
                y="Detik",
                color="Metrik",
                markers=True,
                title="Perubahan Response Time berdasarkan Beban",
            )
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("Lihat detail setiap request"):
            details_df = pd.DataFrame(saved_details)
            st.dataframe(details_df, use_container_width=True, hide_index=True)

        st.markdown("### Unduh Hasil Pengujian")
        result_col1, result_col2 = st.columns(2)
        result_col1.download_button(
            "⬇️ Unduh Ringkasan CSV",
            data=results_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="hasil_pengujian_performa.csv",
            mime="text/csv",
            use_container_width=True,
        )
        try:
            result_col2.download_button(
                "⬇️ Unduh Ringkasan Excel",
                data=create_excel_file(results_df),
                file_name="hasil_pengujian_performa.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except ImportError:
            result_col2.warning("Ekspor Excel membutuhkan openpyxl. Jalankan: pip install openpyxl")

    st.divider()
    st.caption(
        "Catatan metodologi: pengujian ini mengirim HTTP GET ke endpoint lokal. "
        "Hasilnya mengukur lapisan HTTP aplikasi, bukan simulasi browser penuh "
        "atau pengujian interaksi WebSocket Streamlit. Jalankan secara bertahap "
        "dan hentikan jika komputer menjadi tidak responsif."
    )
