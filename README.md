# 🎬 ViralClipper — YouTube → TikTok

Auto-clip bagian paling viral dari video YouTube + Auto Subtitle AI (Whisper).
Deploy online gratis di Railway.

---

## 🚀 Cara Deploy ke Railway (Step by Step)

### Langkah 1 — Upload ke GitHub

1. Buka [github.com](https://github.com) → login → klik **New repository**
2. Beri nama repo: `viralclipper`
3. Set **Public** → klik **Create repository**
4. Upload semua file ini:
   - Klik **uploading an existing file**
   - Drag & drop semua file (termasuk folder `templates/`)
   - Klik **Commit changes**

Atau pakai Git di terminal:
```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/USERNAME/viralclipper.git
git push -u origin main
```

---

### Langkah 2 — Deploy ke Railway

1. Buka [railway.app](https://railway.app) → login dengan GitHub
2. Klik **New Project** → pilih **Deploy from GitHub repo**
3. Pilih repo `viralclipper`
4. Railway otomatis detect Dockerfile dan mulai build
5. Tunggu ~3-5 menit hingga deploy selesai
6. Klik **Generate Domain** → dapat URL publik!

---

### Langkah 3 — Setting Environment Variables (opsional)

Di Railway dashboard → project → **Variables**, tambahkan:

| Key | Value | Keterangan |
|-----|-------|------------|
| `MAX_CLIP_DURATION` | `90` | Maks durasi clip (detik) |
| `JOB_TTL` | `3600` | Hapus file setelah 1 jam |
| `MAX_JOBS` | `5` | Max job serentak |

---

## 🍪 Mengatasi YouTube Bot Detection

Railway server sering diblokir YouTube. Solusinya pakai cookies browser:

### Cara export cookies dari Chrome/Firefox:

1. Install extension **Get cookies.txt LOCALLY** di Chrome
2. Buka youtube.com (login dulu)
3. Klik ekstensi → klik **Export** → simpan sebagai `cookies.txt`
4. Upload file `cookies.txt` ke repo GitHub (di root folder)

> ⚠️ Jangan share cookies kamu ke orang lain!

---

## 📁 Struktur File

```
viralclipper/
├── app.py              ← Flask backend (cloud-optimized)
├── requirements.txt    ← Python dependencies
├── Dockerfile          ← Container config
├── railway.toml        ← Railway deploy config
├── cookies.txt         ← (opsional) YouTube cookies
├── .gitignore
└── templates/
    └── index.html      ← Frontend UI
```

---

## ✨ Fitur

- 🔥 **Deteksi Most Replayed** — clip otomatis bagian paling viral
- 📺 **Format TikTok** — output 1080×1920 (9:16) langsung
- 🤖 **Auto Subtitle AI** — Whisper AI transcribe + burn ke video
- 🌐 **99+ bahasa** — auto-detect atau pilih manual
- ⚡ **Cloud-optimized** — hemat RAM & disk, auto cleanup
- 🛡️ **Rate limit** — max 5 job serentak

---

## ⚠️ Catatan Penting

- Tool ini untuk **tujuan edukasi/personal**
- Download video orang lain dapat melanggar **ToS YouTube & hak cipta**
- File hasil download **otomatis dihapus** setelah 1 jam
- **Whisper model** didownload saat pertama dipakai (~244MB untuk `small`)
- Railway free tier: **500 jam/bulan** — cukup untuk penggunaan pribadi

---

## 🆘 Troubleshooting

| Masalah | Solusi |
|---------|--------|
| "Sign in to confirm you're not a bot" | Upload `cookies.txt` ke repo |
| Whisper lambat | Pakai model `tiny` di UI |
| Build gagal | Cek log di Railway dashboard |
| File tidak bisa didownload | File sudah expired (1 jam), proses ulang |
