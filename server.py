"""
SaveIt Backend Server
Menggunakan yt-dlp untuk mendukung TikTok, Instagram, YouTube, Twitter/X
"""
 
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import re
import threading
import time
import uuid
 
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)
 
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response
 
# ── Folder sementara untuk menyimpan file unduhan ──────────────────────────
DOWNLOAD_DIR = tempfile.mkdtemp(prefix="saveit_")
download_jobs = {}  # job_id → status/info
 
 
# ══════════════════════════════════════════════════════════════════════
#  HELPER: Deteksi platform dari URL
# ══════════════════════════════════════════════════════════════════════
def detect_platform(url: str) -> str:
    if "tiktok.com" in url:
        return "tiktok"
    if "instagram.com" in url:
        return "instagram"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "twitter.com" in url or "x.com" in url:
        return "twitter"
    return "unknown"
 
 
# ══════════════════════════════════════════════════════════════════════
#  HELPER: Konfigurasi yt-dlp per platform
# ══════════════════════════════════════════════════════════════════════
def get_ydl_opts(platform: str, quality: str, output_path: str) -> dict:
    base_opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
 
    if platform == "tiktok":
        if quality == "audio":
            return {**base_opts,
                "format": "bestaudio/best",
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
            }
        # TikTok: unduh tanpa watermark
        return {**base_opts,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        }
 
    elif platform == "instagram":
        return {**base_opts,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        }
 
    elif platform == "youtube":
        format_map = {
            "4k":   "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best",
            "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best",
            "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best",
            "mp3":  "bestaudio/best",
        }
        if quality == "mp3":
            return {**base_opts,
                "format": "bestaudio/best",
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
            }
        return {**base_opts,
            "format": format_map.get(quality, format_map["720"]),
            "merge_output_format": "mp4",
        }
 
    elif platform == "twitter":
        if quality == "audio":
            return {**base_opts,
                "format": "bestaudio/best",
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
            }
        fmt = "bestvideo[height<=720]+bestaudio/best" if quality == "hd" else "bestvideo[height<=480]+bestaudio/best"
        return {**base_opts,
            "format": fmt,
            "merge_output_format": "mp4",
        }
 
    # Default fallback
    return {**base_opts, "format": "best"}
 
 
# ══════════════════════════════════════════════════════════════════════
#  ROUTE 1: GET /info  — ambil info video (judul, thumbnail, durasi, dll)
# ══════════════════════════════════════════════════════════════════════
@app.route("/info", methods=["GET"])
def get_info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL diperlukan"}), 400
 
    platform = detect_platform(url)
    if platform == "unknown":
        return jsonify({"error": "Platform tidak didukung"}), 400
 
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,   # Hanya ambil info, jangan unduh
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
 
        # Format respons berdasarkan platform
        result = {
            "platform": platform,
            "title": info.get("title", "Video"),
            "uploader": info.get("uploader") or info.get("creator") or "Unknown",
            "duration": info.get("duration"),          # detik
            "thumbnail": info.get("thumbnail"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "description": (info.get("description") or "")[:200],
            "options": build_download_options(platform, info),
        }
        return jsonify(result)
 
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "private" in msg.lower():
            return jsonify({"error": "Video bersifat privat, tidak bisa diunduh."}), 403
        if "age" in msg.lower():
            return jsonify({"error": "Video dibatasi usia."}), 403
        return jsonify({"error": f"Gagal mengambil info: {msg[:120]}"}), 400
    except Exception as e:
        return jsonify({"error": f"Error tidak terduga: {str(e)[:120]}"}), 500
 
 
def build_download_options(platform: str, info: dict) -> list:
    """Buat daftar opsi unduhan sesuai platform."""
    opts = []
    height = info.get("height") or 0
 
    if platform == "tiktok":
        opts = [
            {"quality": "hd",    "label": "Video HD",   "desc": "MP4 · 720p · Tanpa Watermark", "icon": "🎬"},
            {"quality": "sd",    "label": "Video SD",   "desc": "MP4 · 480p · Tanpa Watermark", "icon": "📱"},
            {"quality": "audio", "label": "Audio Saja", "desc": "MP3 · 128kbps",                "icon": "🎵"},
        ]
    elif platform == "instagram":
        opts = [
            {"quality": "hd", "label": "Video HD",      "desc": "MP4 · Kualitas Terbaik",       "icon": "🎬"},
            {"quality": "sd", "label": "Video SD",      "desc": "MP4 · Ukuran Lebih Kecil",     "icon": "📱"},
        ]
    elif platform == "youtube":
        if height >= 2160:
            opts.append({"quality": "4k",   "label": "Video 4K",   "desc": "MP4 · 2160p · Ultra HD", "icon": "🎬"})
        if height >= 1080 or not opts:
            opts.append({"quality": "1080", "label": "Video 1080p","desc": "MP4 · Full HD",           "icon": "🎬"})
        opts.append({"quality": "720",  "label": "Video 720p",  "desc": "MP4 · HD",                   "icon": "🎬"})
        opts.append({"quality": "mp3",  "label": "Audio MP3",   "desc": "MP3 · 320kbps",              "icon": "🎵"})
    elif platform == "twitter":
        opts = [
            {"quality": "hd",    "label": "Video HD",   "desc": "MP4 · 720p", "icon": "🎬"},
            {"quality": "sd",    "label": "Video SD",   "desc": "MP4 · 480p", "icon": "📱"},
            {"quality": "audio", "label": "Audio",      "desc": "MP3 · 128kbps", "icon": "🎵"},
        ]
    return opts
 
 
# ══════════════════════════════════════════════════════════════════════
#  ROUTE 2: POST /download  — mulai unduh, return job_id
# ══════════════════════════════════════════════════════════════════════
@app.route("/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = (data or {}).get("url", "").strip()
    quality = (data or {}).get("quality", "hd").lower()
 
    if not url:
        return jsonify({"error": "URL diperlukan"}), 400
 
    platform = detect_platform(url)
    if platform == "unknown":
        return jsonify({"error": "Platform tidak didukung"}), 400
 
    job_id = str(uuid.uuid4())[:8]
    ext = "mp3" if quality in ("mp3", "audio") else "mp4"
    output_path = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
 
    download_jobs[job_id] = {"status": "processing", "platform": platform, "quality": quality}
 
    def run():
        try:
            opts = get_ydl_opts(platform, quality, output_path)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                # Cek file yang sebenarnya (bisa berubah ekstensi)
                base = os.path.splitext(filename)[0]
                for candidate in [filename, base + ".mp4", base + ".mp3", base + ".webm"]:
                    if os.path.exists(candidate):
                        download_jobs[job_id].update({
                            "status": "done",
                            "filepath": candidate,
                            "filename": os.path.basename(candidate),
                            "title": info.get("title", "video"),
                        })
                        return
            download_jobs[job_id]["status"] = "error"
            download_jobs[job_id]["error"] = "File tidak ditemukan setelah unduh."
        except Exception as e:
            download_jobs[job_id]["status"] = "error"
            download_jobs[job_id]["error"] = str(e)[:200]
 
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id, "status": "processing"})
 
 
# ══════════════════════════════════════════════════════════════════════
#  ROUTE 3: GET /status/<job_id>  — cek status job
# ══════════════════════════════════════════════════════════════════════
@app.route("/status/<job_id>", methods=["GET"])
def job_status(job_id):
    job = download_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job tidak ditemukan"}), 404
    resp = {"status": job["status"], "job_id": job_id}
    if job["status"] == "done":
        resp["filename"] = job.get("filename")
        resp["title"] = job.get("title")
    if job["status"] == "error":
        resp["error"] = job.get("error")
    return jsonify(resp)
 
 
# ══════════════════════════════════════════════════════════════════════
#  ROUTE 4: GET /file/<job_id>  — unduh file yang sudah siap
# ══════════════════════════════════════════════════════════════════════
@app.route("/file/<job_id>", methods=["GET"])
def get_file(job_id):
    job = download_jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File belum siap atau tidak ditemukan"}), 404
 
    filepath = job["filepath"]
    if not os.path.exists(filepath):
        return jsonify({"error": "File sudah dihapus dari server"}), 404
 
    title = re.sub(r'[^\w\s-]', '', job.get("title", "video"))[:60]
    ext = os.path.splitext(filepath)[1]
    download_name = f"{title}{ext}"
 
    return send_file(filepath, as_attachment=True, download_name=download_name)
 
 
# ══════════════════════════════════════════════════════════════════════
#  CLEANUP: hapus file lama setiap 30 menit
# ══════════════════════════════════════════════════════════════════════
def cleanup_old_files():
    while True:
        time.sleep(1800)
        now = time.time()
        for jid, job in list(download_jobs.items()):
            fp = job.get("filepath")
            if fp and os.path.exists(fp):
                if now - os.path.getmtime(fp) > 3600:  # Hapus setelah 1 jam
                    os.remove(fp)
                    del download_jobs[jid]
 
threading.Thread(target=cleanup_old_files, daemon=True).start()
 
 
# ══════════════════════════════════════════════════════════════════════
#  ROUTE 5: GET /health  — cek server aktif
# ══════════════════════════════════════════════════════════════════════
@app.route("/info", methods=["OPTIONS"])
@app.route("/download", methods=["OPTIONS"])
@app.route("/health", methods=["OPTIONS"])
def handle_options():
    return "", 204
 
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "SaveIt Backend", "version": "1.0"})
 
 
if __name__ == "__main__":
    raw_port = os.environ.get("PORT", "8080")
    print(f"RAW PORT VALUE: '{raw_port}'")  # debug
    # Bersihkan jika ada karakter aneh
    raw_port = raw_port.strip().replace("$", "").replace("{", "").replace("}", "")
    try:
        port = int(raw_port)
    except ValueError:
        port = 8080
    print(f"🚀 SaveIt Backend berjalan di http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
 
