
import os
import requests


def send_alert(result: dict) -> bool:
    """
    Mengirim notifikasi ketika website mengalami
    ERROR, SLOW, atau workflow gagal.
    """

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram belum dikonfigurasi: token/chat ID kosong.")
        return False

    message = (
        "⚠️ WEBSITE MONITORING ALERT\n\n"
        f"Website: {result['website_name']}\n"
        f"Status: {result['status']}\n"
        f"HTTP: {result['http_status']}\n"
        f"Response time: {result['response_time']} detik\n"
        f"Workflow: {result['workflow_status']}\n"
        f"Waktu: {result['checked_at']}\n"
        f"Keterangan: {result['message']}"
    )

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message
            },
            timeout=10
        )

        response.raise_for_status()

        result_data = response.json()

        if not result_data.get("ok"):
            print("Telegram API menolak pengiriman pesan.")
            return False

        return True

    except requests.RequestException as exc:
        print(f"Gagal mengirim Telegram: {exc}")
        return False


def send_test_message():
    """
    Mengirim pesan percobaan untuk memastikan
    koneksi Telegram berhasil.
    """

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return False, "Token atau Chat ID belum diisi."

    message = (
        "✅ TEST BERHASIL!\n\n"
        "Website Monitoring DPRD sudah terhubung "
        "dengan Telegram.\n\n"
        "Notifikasi monitoring siap digunakan."
    )

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message
            },
            timeout=10
        )

        response.raise_for_status()

        result_data = response.json()

        if not result_data.get("ok"):
            return False, "Telegram gagal mengirim pesan."

        return True, "Pesan berhasil dikirim ke Telegram!"

    except requests.RequestException as exc:
        return False, f"Gagal mengirim pesan: {exc}"
