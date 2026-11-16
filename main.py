import streamlit as st
import pandas as pd
import plotly.express as px
import uuid
import json

from urllib.parse import urlparse
from notifications.telegram_bot import send_test_message
from monitoring.monitor import run_all_checks, run_single_check
from database.db import (
    init_db,
    get_latest_results,
    get_history,
    get_summary,
)
from config.settings import (
    load_app_config,
    load_websites,
    save_websites,
)


# =====================================================
# KONFIGURASI HALAMAN
# =====================================================

st.set_page_config(
    page_title="Website Monitoring",
    page_icon="🌐",
    layout="wide",
)

init_db()
cfg = load_app_config()


# =====================================================
# FUNGSI BANTU
# =====================================================

def valid_url(url):
    try:
        parsed = urlparse(url.strip())
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and "." in parsed.netloc
        )
    except Exception:
        return False


# =====================================================
# JUDUL DASHBOARD
# =====================================================

st.title("🌐 Website Monitoring Dashboard")
st.caption(
    "Monitoring status, performa, dan simulasi alur pengguna website."
)


# =====================================================
# SIDEBAR - KONTROL MONITORING
# =====================================================

with st.sidebar:
    st.header("Kontrol Monitoring")

    st.write(
        f"Interval worker: "
        f"**{cfg.get('monitoring_interval', 300)} detik**"
    )

    # Periksa semua website aktif.
    if st.button(
        "▶ Jalankan pengecekan semua website",
        use_container_width=True,
        key="btn_run_all_monitoring",
    ):
        with st.spinner("Sedang mengecek seluruh website aktif..."):
            try:
                results = run_all_checks()
                st.success(
                    f"Pengecekan selesai. {len(results)} website diproses."
                )
            except Exception as exc:
                st.error(f"Terjadi kesalahan saat monitoring: {exc}")

    st.divider()
    st.subheader("Pengecekan Website Tertentu")

    active_websites = [
        site for site in load_websites()
        if site.get("enabled", True)
    ]

    if active_websites:
        website_options = {
            site["id"]: site["name"] for site in active_websites
        }

        selected_website_id = st.selectbox(
            "Pilih website yang ingin diperiksa",
            options=list(website_options.keys()),
            format_func=lambda site_id: website_options[site_id],
            key="single_website_selector",
        )

        if st.button(
            "🔍 Cek Website Terpilih",
            use_container_width=True,
            key="btn_run_single_monitoring",
        ):
            with st.spinner("Sedang memeriksa website terpilih..."):
                try:
                    result = run_single_check(selected_website_id)

                    st.success(
                        f"Pengecekan {result['website_name']} selesai."
                    )
                    st.write(f"Status: **{result['status']}**")
                    st.write(
                        f"HTTP: **{result['http_status']}**"
                    )

                    if result["response_time"] is not None:
                        st.write(
                            "Response time: "
                            f"**{result['response_time']:.2f} detik**"
                        )

                    st.write(f"Keterangan: {result['message']}")

                    st.divider()
                    st.write("**Hasil Simulasi Browser (Workflow)**")
                    st.write(
                        f"Status Workflow: **{result.get('workflow_status', 'SKIPPED')}**"
                    )
                    st.write(
                        f"Durasi Workflow: **{result.get('workflow_duration', 0):.2f} detik**"
                    )

                    page_load = result.get("page_load_time")
                    if page_load is not None:
                        st.write(f"Page Load Time: **{page_load:.2f} detik**")

                    if result.get("workflow_final_url"):
                        st.write(f"URL Akhir: {result['workflow_final_url']}")

                    if result.get("workflow_page_title"):
                        st.write(f"Judul Halaman: {result['workflow_page_title']}")

                    step_rows = result.get("workflow_steps", [])
                    if step_rows:
                        st.write("**Detail Setiap Langkah**")
                        st.dataframe(
                            pd.DataFrame(step_rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info("Tidak ada detail langkah workflow untuk pengecekan ini.")

                except Exception as exc:
                    st.error(f"Gagal memeriksa website: {exc}")
    else:
        st.info(
            "Belum ada website aktif. Tambahkan website atau aktifkan "
            "website melalui menu Edit Website."
        )

    st.divider()

    # Tes koneksi Telegram.
    if st.button(
        "📨 Tes Notifikasi Telegram",
        use_container_width=True,
        key="btn_test_telegram",
    ):
        success, message = send_test_message()

        if success:
            st.success(message)
        else:
            st.error(message)

    st.divider()
    st.info(
        "Untuk monitoring berkala, jalankan worker.py "
        "di terminal terpisah."
    )


# =====================================================
# MANAJEMEN WEBSITE
# =====================================================

st.header("⚙️ Kelola Website")
st.caption(
    "Tambahkan, ubah, aktifkan, nonaktifkan, atau hapus website "
    "yang ingin dipantau."
)

tab_add, tab_edit, tab_delete = st.tabs(
    ["➕ Tambah Website", "✏️ Edit Website", "🗑️ Hapus Website"]
)


# =====================================================
# TAMBAH WEBSITE
# =====================================================

with tab_add:
    st.subheader("Tambah Website Baru")

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

        new_enabled = st.checkbox(
            "Aktifkan monitoring",
            value=True,
        )

        add_submit = st.form_submit_button(
            "＋ Simpan Website",
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
                    "workflow_enabled": False,
                    "workflow": [],
                }

                website_data.append(new_website)
                save_websites(website_data)

                st.success(
                    f"Website '{new_name}' berhasil ditambahkan."
                )
                st.rerun()


# =====================================================
# EDIT WEBSITE
# =====================================================

with tab_edit:
    st.subheader("Edit Pengaturan Website")
    current_websites = load_websites()

    if not current_websites:
        st.info("Belum ada website yang dapat diedit.")
    else:
        website_map = {
            site["id"]: site for site in current_websites
        }

        selected_edit_id = st.selectbox(
            "Pilih Website",
            options=list(website_map.keys()),
            format_func=lambda site_id: website_map[site_id]["name"],
            key="edit_website_selector",
        )

        selected_site = website_map[selected_edit_id]

        with st.form("edit_website_form"):
            edit_name = st.text_input(
                "Nama Website",
                value=selected_site["name"],
            )

            edit_url = st.text_input(
                "Alamat Website (URL)",
                value=selected_site["url"],
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
                            site["threshold_seconds"] = float(
                                edit_threshold
                            )
                            site["enabled"] = edit_enabled
                            break

                    save_websites(updated_websites)
                    st.success(
                        "Pengaturan website berhasil diperbarui."
                    )
                    st.rerun()


# =====================================================
# HAPUS WEBSITE
# =====================================================

with tab_delete:
    st.subheader("Hapus Website")
    current_websites = load_websites()

    if not current_websites:
        st.info("Belum ada website yang dapat dihapus.")
    else:
        website_map = {
            site["id"]: site for site in current_websites
        }

        selected_delete_id = st.selectbox(
            "Pilih Website yang akan dihapus",
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
                    st.error(
                        "Centang konfirmasi sebelum menghapus."
                    )
                else:
                    updated_websites = [
                        site
                        for site in load_websites()
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


# =====================================================
# DAFTAR WEBSITE TERDAFTAR
# =====================================================

st.divider()
st.subheader("📋 Daftar Website Terdaftar")
registered_websites = load_websites()

if registered_websites:
    website_table = []

    for site in registered_websites:
        website_table.append(
            {
                "Nama Website": site["name"],
                "URL": site["url"],
                "Status Monitoring": (
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
    )
else:
    st.info(
        "Belum ada website terdaftar. "
        "Tambahkan website melalui menu Tambah Website."
    )


# =====================================================
# RINGKASAN MONITORING
# =====================================================

st.divider()
st.header("📊 Ringkasan Monitoring")
summary = get_summary()

c1, c2, c3, c4 = st.columns(4)

c1.metric("Total Website", summary["total"])
c2.metric("Online", summary["online"])
c3.metric("Error / Lambat", summary["error"])
c4.metric(
    "Rata-rata Respons HTTP",
    (
        f'{summary["avg_response"]:.2f} s'
        if summary["avg_response"] is not None
        else "-"
    ),
)

c5, c6 = st.columns(2)
c5.metric(
    "Rata-rata Page Load",
    (
        f'{summary["avg_page_load"]:.2f} s'
        if summary.get("avg_page_load") is not None
        else "-"
    ),
)
c6.metric(
    "Rata-rata Durasi Workflow",
    (
        f'{summary["avg_workflow"]:.2f} s'
        if summary.get("avg_workflow") is not None
        else "-"
    ),
)


# =====================================================
# STATUS WEBSITE TERBARU
# =====================================================

st.subheader("Status Website Terbaru")
latest = get_latest_results()

if latest:
    df = pd.DataFrame(latest)

    display_cols = [
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

    st.dataframe(
        df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "website_name": "Nama Website",
            "checked_at": "Waktu Pengecekan",
            "http_status": "HTTP Status",
            "response_time": "HTTP Response (s)",
            "status": "Status HTTP",
            "page_load_time": "Page Load (s)",
            "workflow_duration": "Durasi Workflow (s)",
            "workflow_status": "Status Workflow",
            "message": "Keterangan",
        },
    )

    st.write("**Detail Workflow Website Terbaru**")
    for row in latest:
        steps = row.get("workflow_steps", [])

        # Mengubah JSON berbentuk teks menjadi list
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError:
                steps = []

        # Memastikan data berbentuk list
        if isinstance(steps, dict):
            steps = [steps]

        if isinstance(steps, list) and steps:
            st.dataframe(
                pd.DataFrame(steps),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "step": "Langkah",
                    "action": "Aksi",
                    "status": "Hasil",
                    "duration": "Durasi (detik)",
                    "message": "Keterangan",
                },
            )
        else:
            st.caption("Belum ada detail langkah workflow yang tersimpan.")
else:
    st.info(
        "Belum ada hasil monitoring. "
        "Tambahkan website, lalu jalankan pengecekan."
    )


# =====================================================
# RIWAYAT RESPONSE TIME
# =====================================================

st.subheader("Riwayat Response Time")
history = get_history(limit=500)

if history:
    hist_df = pd.DataFrame(history)
    hist_df["checked_at"] = pd.to_datetime(hist_df["checked_at"])

    fig = px.line(
        hist_df,
        x="checked_at",
        y="response_time",
        color="website_name",
        markers=True,
        title="HTTP Response Time Website (Detik)",
    )

    fig.update_layout(
        xaxis_title="Waktu Pengecekan",
        yaxis_title="Detik",
        legend_title="Website",
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Grafik akan muncul setelah pengecekan pertama.")


# =====================================================
# RIWAYAT PENGUJIAN
# =====================================================

st.subheader("Riwayat Pengujian")

if history:
    history_display = pd.DataFrame(history)
    history_columns = [
        "website_name",
        "checked_at",
        "http_status",
        "response_time",
        "status",
        "page_load_time",
        "workflow_duration",
        "workflow_status",
        "workflow_message",
        "workflow_final_url",
        "workflow_page_title",
    ]
    available_history_columns = [
        column for column in history_columns
        if column in history_display.columns
    ]
    st.dataframe(
        history_display[available_history_columns],
        use_container_width=True,
        hide_index=True,
        column_config={
            "website_name": "Nama Website",
            "checked_at": "Waktu Pengecekan",
            "http_status": "HTTP Status",
            "response_time": "HTTP Response (s)",
            "status": "Status HTTP",
            "page_load_time": "Page Load (s)",
            "workflow_duration": "Durasi Workflow (s)",
            "workflow_status": "Status Workflow",
            "workflow_message": "Keterangan Workflow",
            "workflow_final_url": "URL Akhir",
            "workflow_page_title": "Judul Halaman",
        },
    )
else:
    st.info("Belum ada riwayat pengujian.")


# =====================================================
# CATATAN
# =====================================================

st.divider()
st.caption(
    "HTTP Check mengukur respons endpoint website. "
    "Workflow browser mengukur keberhasilan langkah "
    "interaksi yang dikonfigurasi."
)
