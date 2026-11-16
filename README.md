
# Website Monitoring System

Aplikasi pemantauan ketersediaan dan performa website berbasis Python dan Streamlit. Aplikasi ini menggunakan HTTP monitoring dan browser automation untuk memeriksa kondisi website serta mensimulasikan aktivitas pengguna.

## Fitur Utama

- **Dashboard Monitoring:** Menampilkan status website dan hasil pemeriksaan.
- **HTTP Monitoring:** Memeriksa ketersediaan website, HTTP status code, dan response time.
- **Browser Workflow:** Menjalankan simulasi aktivitas pengguna menggunakan Playwright.
- **Monitoring History:** Menyimpan hasil pemeriksaan ke database SQLite.
- **Website Management:** Mengelola daftar website yang akan dipantau.
- **Performance Visualization:** Menampilkan riwayat hasil monitoring dalam bentuk grafik.
- **Telegram Notification:** Mengirim notifikasi ketika ditemukan masalah pada website.
- **Scheduled Monitoring:** Menjalankan monitoring secara berkala menggunakan worker.

## Teknologi

- Python 3.12
- Streamlit
- Playwright
- SQLite
- Requests
- Pandas
- Plotly
- APScheduler
- Python-dotenv

## 1. Persiapan

Pastikan Python 3.11 atau 3.12 sudah terpasang.

Clone repository:

```bash
git clone URL_REPOSITORY
cd website-monitoring
```

Buat virtual environment:

```bash
py -m venv .venv
```

Aktifkan virtual environment melalui CMD:

```cmd
.venv\Scripts\activate.bat
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Install browser Chromium untuk Playwright:

```bash
python -m playwright install chromium
```

## 2. Menjalankan Dashboard

Jalankan perintah:

```bash
streamlit run main.py
```

Dashboard dapat diakses melalui alamat lokal yang ditampilkan Streamlit, biasanya:

```text
http://localhost:8501
```

## 3. Menjalankan Monitoring Berkala

Buka terminal CMD kedua, masuk ke folder project, kemudian aktifkan virtual environment.

Jalankan:

```bash
python worker.py
```

Worker akan menjalankan pemeriksaan langsung saat pertama kali aktif, kemudian melanjutkan pemeriksaan berdasarkan interval pada `config.json`.

Dashboard dan worker dapat dijalankan pada dua terminal terpisah.

## 4. Konfigurasi Monitoring

Pengaturan aplikasi terdapat pada file `config.json`.

Parameter utama:

- `monitoring_interval`: Interval monitoring dalam detik.
- `default_timeout`: Batas waktu pemeriksaan.
- `slow_threshold`: Batas response time untuk kategori lambat.
- `database`: Lokasi database monitoring.
- `telegram_enabled`: Mengaktifkan atau menonaktifkan notifikasi Telegram.

Daftar website yang dipantau disimpan dalam:

```text
config/websites.json
```

Website dapat dikelola melalui fitur pengelolaan website pada aplikasi atau melalui konfigurasi yang tersedia.

## 5. Browser Workflow

Browser workflow menggunakan Playwright untuk mensimulasikan aktivitas pengguna pada website.

Action yang didukung:

| Action | Fungsi |
|---|---|
| `open` | Membuka halaman website |
| `fill` | Mengisi elemen input |
| `click` | Menekan elemen |
| `check_text` | Memeriksa keberadaan teks |
| `check_visible` | Memeriksa visibilitas elemen |
| `check_enabled` | Memeriksa apakah elemen aktif |
| `check_url` | Memeriksa URL halaman |
| `check_title` | Memeriksa judul halaman |
| `wait` | Menunggu selama waktu tertentu |
| `wait_for_url` | Menunggu sampai URL sesuai |

Contoh konfigurasi workflow:

```json
[
  {
    "action": "open",
    "url": "https://skm.go.id/",
    "wait_until": "load"
  },
  {
    "action": "check_url",
    "url": "skm.go.id"
  }
]
```

Untuk action `fill`, `click`, `check_visible`, dan `check_enabled`, gunakan selector CSS yang sesuai dengan elemen pada website target.

## 6. Konfigurasi Telegram

Untuk mengaktifkan notifikasi Telegram:

1. Buat bot melalui BotFather.
2. Salin token bot.
3. Kirim `/start` ke bot.
4. Dapatkan Chat ID.
5. Salin `.env.example` menjadi `.env`.
6. Isi token dan Chat ID pada file `.env`.
7. Aktifkan `telegram_enabled` pada `config.json`.

Contoh isi `.env`:

```env
TELEGRAM_BOT_TOKEN=token_bot
TELEGRAM_CHAT_ID=chat_id
```

Jangan membagikan token bot dan jangan mengunggah file `.env` ke repository.

## 7. Struktur Project

```text
website-monitoring/
│
├── config/
│   ├── settings.py
│   └── websites.json
│
├── database/
│   ├── db.py
│   └── repository.py
│
├── monitoring/
│   ├── http_checker.py
│   ├── monitor.py
│   └── workflow_runner.py
│
├── notifications/
│   └── telegram_bot.py
│
├── utils/
│   ├── helpers.py
│   └── logger.py
│
├── main.py
├── app.py
├── worker.py
├── config.json
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Catatan Penggunaan

- Gunakan hanya website yang telah memberikan izin untuk diuji.
- Hindari pengiriman formulir resmi atau data masyarakat.
- Gunakan akun uji dan data dummy jika diperlukan.
- Website yang menggunakan CAPTCHA, OTP, atau proteksi anti-bot mungkin tidak dapat diuji otomatis.
- Sesuaikan interval monitoring dengan kebutuhan dan izin pemilik website.
