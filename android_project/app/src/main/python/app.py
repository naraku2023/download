import os
import sys
import uuid
import json
import time
import shutil
import threading
import platform
from flask import Flask, request, jsonify, send_from_directory

# Standard imports
try:
    import flask
    import yt_dlp
except ImportError:
    pass

# We find the static folder relative to the script location inside the Chaquopy extraction directory
base_dir = os.path.dirname(os.path.abspath(__file__))
static_folder_path = os.path.join(base_dir, 'static')
app = Flask(__name__, static_folder=static_folder_path)

@app.before_request
def handle_options_preflight():
    if request.method == 'OPTIONS':
        response = app.make_response('')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
        return response

# Android-specific directories
app_dir = os.path.expanduser("~") # Writable private directory inside app sandbox
SETTINGS_FILE = os.path.join(app_dir, 'settings.json')
HISTORY_FILE = os.path.join(app_dir, 'history.json')
TASKS_FILE = os.path.join(app_dir, 'tasks.json')

# We will initialize DOWNLOADS_DIR dynamically inside run_server
DOWNLOADS_DIR = ""

def is_ffmpeg_ready():
    try:
        from com.chaquo.python import Python
        context = Python.getPlatform().getApplication()
        private_bin = os.path.join(context.getFilesDir().getAbsolutePath(), 'bin')
        ffmpeg_bin_path = os.path.join(private_bin, 'ffmpeg')
        return os.path.exists(ffmpeg_bin_path)
    except Exception:
        return shutil.which("ffmpeg") is not None


# Thread-safe download tracking
download_tasks = {}
tasks_lock = threading.Lock()

# Custom Scraper and Decryptor for rou.video
def check_and_parse_rou_video(url):
    if "rou.video" not in url:
        return None
    try:
        import urllib.request
        import re
        import json
        import base64
        
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        next_data = re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.IGNORECASE)
        if not next_data:
            return None
            
        data = json.loads(next_data.group(1))
        page_props = data.get("props", {}).get("pageProps", {})
        video_meta = page_props.get("video", {})
        ev = page_props.get("ev", {})
        
        if not ev or 'd' not in ev or 'k' not in ev:
            return None
            
        # Decrypt using shift-minus decryption
        d = ev['d']
        k = ev['k']
        decoded_bytes = base64.b64decode(d)
        decrypted_bytes = bytes([(b - k) % 256 for b in decoded_bytes])
        decrypted_str = decrypted_bytes.decode('utf-8', errors='ignore')
        
        decrypted_data = json.loads(decrypted_str)
        video_url = decrypted_data.get("videoUrl")
        
        if not video_url:
            return None
            
        title = video_meta.get("nameZh") or video_meta.get("name") or "RouVideo"
        thumbnail = video_meta.get("coverImageUrl") or ""
        duration_raw = video_meta.get("duration", 0)
        
        duration_str = "Unknown"
        if duration_raw:
            duration_raw = int(duration_raw)
            if duration_raw > 3600:
                duration_str = time.strftime('%H:%M:%S', time.gmtime(duration_raw))
            else:
                duration_str = time.strftime('%M:%S', time.gmtime(duration_raw))
                
        formats = [{
            "format_id": "rou_hls",
            "ext": "mp4",
            "resolution": "HD",
            "label": "解密高清画质 (HLS)",
            "size": "自动 (分段下载)",
            "filesize": 0,
            "has_video": True,
            "has_audio": True,
            "fps": "",
            "direct_url": video_url
        }]
        
        metadata = {
            "title": title,
            "duration": duration_str,
            "thumbnail": thumbnail,
            "author": "RouVideo 播放器",
            "platform": "RouVideo",
            "formats": formats,
            "url": url,
            "scraped": True
        }
        return metadata
    except Exception as e:
        print("Error parsing rou.video:", e)
        return None

# Load/Save Tasks Queue State
def load_tasks_from_file():
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_tasks_to_file():
    try:
        with open(TASKS_FILE, 'w', encoding='utf-8') as f:
            with tasks_lock:
                tasks_copy = {tid: task.copy() for tid, task in download_tasks.items()}
            json.dump(tasks_copy, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving tasks:", e)

# Load/Save Settings
def load_settings():
    default_settings = {
        "download_dir": DOWNLOADS_DIR,
        "max_concurrent": 3
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                if not os.path.exists(settings.get("download_dir", "")):
                    os.makedirs(settings["download_dir"], exist_ok=True)
                return settings
        except Exception:
            return default_settings
    return default_settings

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving settings:", e)

# Load/Save History
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving history:", e)

def get_mp4_duration_pure(filepath):
    try:
        with open(filepath, 'rb') as f:
            f.seek(0, 2)
            file_size = f.tell()
            f.seek(0)
            
            chunk_size = 5 * 1024 * 1024
            data = b""
            mvhd_pos = -1
            
            if file_size <= chunk_size * 2:
                f.seek(0)
                data = f.read()
                mvhd_pos = data.find(b'mvhd')
            else:
                f.seek(0)
                data_start = f.read(chunk_size)
                mvhd_pos = data_start.find(b'mvhd')
                if mvhd_pos != -1:
                    data = data_start
                else:
                    f.seek(file_size - chunk_size)
                    data_end = f.read(chunk_size)
                    mvhd_pos = data_end.find(b'mvhd')
                    if mvhd_pos != -1:
                        data = data_end
            
            if mvhd_pos != -1:
                box_start = mvhd_pos - 4
                if box_start >= 0 and box_start + 40 <= len(data):
                    version = data[box_start + 8]
                    if version == 1:
                        timescale = int.from_bytes(data[box_start + 28 : box_start + 32], 'big')
                        duration = int.from_bytes(data[box_start + 32 : box_start + 40], 'big')
                    else:
                        timescale = int.from_bytes(data[box_start + 20 : box_start + 24], 'big')
                        duration = int.from_bytes(data[box_start + 24 : box_start + 28], 'big')
                    
                    if timescale > 0 and duration > 0:
                        return duration / timescale
    except Exception as e:
        print("Pure Python MP4 duration probe error:", e)
    return None

def get_video_duration(filepath):
    if not filepath or not os.path.exists(filepath):
        return None
    # 1. Try ffprobe if available
    try:
        import subprocess
        ffprobe_path = shutil.which("ffprobe")
        if not ffprobe_path:
            try:
                from com.chaquo.python import Python
                context = Python.getPlatform().getApplication()
                private_bin = os.path.join(context.getFilesDir().getAbsolutePath(), 'bin')
                candidate = os.path.join(private_bin, 'ffprobe')
                if os.path.exists(candidate):
                    ffprobe_path = candidate
            except Exception:
                pass
        
        if ffprobe_path:
            cmd = [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath
            ]
            startupinfo = None
            if platform.system() == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            stdout, _ = proc.communicate(timeout=3)
            if proc.returncode == 0:
                duration_seconds = float(stdout.strip())
                if duration_seconds > 0:
                    if duration_seconds > 3600:
                        return time.strftime('%H:%M:%S', time.gmtime(duration_seconds))
                    else:
                        return time.strftime('%M:%S', time.gmtime(duration_seconds))
    except Exception as e:
        print("Error getting duration via ffprobe:", e)
        
    # 2. Try pure Python MP4 metadata parser fallback
    try:
        duration_seconds = get_mp4_duration_pure(filepath)
        if duration_seconds and duration_seconds > 0:
            if duration_seconds > 3600:
                return time.strftime('%H:%M:%S', time.gmtime(duration_seconds))
            else:
                return time.strftime('%M:%S', time.gmtime(duration_seconds))
    except Exception as e:
        print("Error getting duration via pure python parser:", e)
    return None

def add_to_history(task):
    history = load_history()
    total_bytes = task.get("total_bytes") or 0
    size_str = "Unknown"
    if total_bytes > 0:
        if total_bytes > 1024*1024*1024:
            size_str = f"{round(total_bytes / (1024*1024*1024), 2)} GB"
        else:
            size_str = f"{round(total_bytes / (1024*1024), 1)} MB"
    elif task.get("size") and task.get("size") != "Unknown":
        size_str = task["size"]

    filepath = task.get("filepath", "")
    duration_str = task.get("duration", "Unknown")
    if duration_str == "Unknown" and filepath:
        probed = get_video_duration(filepath)
        if probed:
            duration_str = probed

    item = {
        "id": task["id"],
        "url": task["url"],
        "title": task["title"],
        "thumbnail": task["thumbnail"],
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "size": size_str,
        "platform": task.get("platform", "Unknown"),
        "duration": duration_str,
        "timestamp": time.time()
    }
    history = [h for h in history if h["id"] != task["id"]]
    history.insert(0, item)
    save_history(history[:50])

# Custom progress hook builder
def make_progress_hook(task_id):
    def progress_hook(d):
        with tasks_lock:
            if task_id not in download_tasks:
                raise Exception("Download cancelled by user")
            if download_tasks[task_id]['status'] == 'cancelled':
                raise Exception("Download cancelled by user")
            if download_tasks[task_id]['status'] == 'paused':
                raise Exception("Download paused by user")
            
        if d['status'] == 'downloading':
            percent = 0.0
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            if total > 0:
                percent = round((downloaded / total) * 100, 1)
            
            speed = d.get('speed')
            speed_str = "0 KB/s"
            if speed:
                if speed > 1024 * 1024:
                    speed_str = f"{round(speed / (1024*1024), 1)} MB/s"
                else:
                    speed_str = f"{round(speed / 1024, 1)} KB/s"
            
            eta = d.get('eta')
            eta_str = "Unknown"
            if eta is not None:
                eta_str = f"{eta}s"
                
            should_save = False
            with tasks_lock:
                if task_id in download_tasks:
                    last_percent = download_tasks[task_id].get("percent", 0.0)
                    download_tasks[task_id].update({
                        "percent": percent,
                        "speed": speed_str,
                        "eta": eta_str,
                        "downloaded_bytes": downloaded,
                        "total_bytes": total
                    })
                    should_save = (int(percent) > int(last_percent)) or (percent > 0 and last_percent == 0)
            if should_save:
                save_tasks_to_file()
        elif d['status'] == 'finished':
            # Do not perform final export/cleanup/history write here to avoid deleting raw chunks before FFmpeg merges them.
            # Instead, just update the percent state in memory.
            with tasks_lock:
                if task_id in download_tasks:
                    download_tasks[task_id].update({
                        "percent": 100.0
                    })
            save_tasks_to_file()
    return progress_hook

# Threaded downloader task
def execute_download(task_id, url, format_id, settings):
    dl_dir = settings.get("download_dir", DOWNLOADS_DIR)
    with tasks_lock:
        task = download_tasks.get(task_id)
        direct_url = task.get("direct_url") if task else None
        task_title = task.get("title", "video") if task else "video"
        task_thumbnail = task.get("thumbnail", "") if task else ""
        received_cookies = task.get("cookies", "") if task else ""
        received_user_agent = task.get("user_agent", "") if task else ""
        
    if "rou.video" in url:
        fresh_meta = check_and_parse_rou_video(url)
        if fresh_meta and fresh_meta.get("formats"):
            fresh_url = fresh_meta["formats"][0].get("direct_url")
            if fresh_url:
                direct_url = fresh_url
    
    download_url = direct_url if direct_url else url
    ffmpeg_available = is_ffmpeg_ready()
    safe_title = "".join(c if c.isalnum() or c in ' -_.' else '_' for c in task_title)[:80]

    # Download thumbnail locally with cookies/UA to bypass 403 hotlink blocks
    local_thumb_url = task_thumbnail
    if task_thumbnail and task_thumbnail.startswith('http'):
        try:
            import urllib.request
            thumb_headers = {
                'User-Agent': received_user_agent if received_user_agent else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': url
            }
            if received_cookies:
                thumb_headers['Cookie'] = received_cookies
                
            thumb_req = urllib.request.Request(task_thumbnail, headers=thumb_headers)
            thumb_ext = 'jpg'
            if '.png' in task_thumbnail:
                thumb_ext = 'png'
            elif '.webp' in task_thumbnail:
                thumb_ext = 'webp'
            
            # Save in private/temporary thumbnails cache directory instead of public downloads folder
            thumbnails_dir = os.path.join(app_dir, 'thumbnails_cache')
            os.makedirs(thumbnails_dir, exist_ok=True)
            local_thumb_path = os.path.join(thumbnails_dir, f"{task_id}.{thumb_ext}")
            with urllib.request.urlopen(thumb_req, timeout=10) as response:
                with open(local_thumb_path, 'wb') as f:
                    f.write(response.read())
            local_thumb_url = f"/api/thumbnail?path={local_thumb_path}"
        except Exception as e:
            print("Error downloading thumbnail:", e)

    # Sync local thumbnail url back to task state
    with tasks_lock:
        if task_id in download_tasks:
            download_tasks[task_id]["thumbnail"] = local_thumb_url

    ydl_opts = {
        'outtmpl': os.path.join(dl_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [make_progress_hook(task_id)],
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 5,
        'fragment_retries': 10,
        'hls_prefer_native': True,  # Force native HLS downloader for robust HTTPS compatibility via Python urllib
    }

    # Generate custom browser headers
    from urllib.parse import urlparse
    try:
        parsed_uri = urlparse(url)
        domain = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
        referer_url = url
    except Exception:
        domain = "https://91porn.com"
        referer_url = url if url else "https://91porn.com"
        
    headers = {
        'User-Agent': received_user_agent if received_user_agent else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': referer_url,
        'Origin': domain,
    }
    if received_cookies:
        headers['Cookie'] = received_cookies
    ydl_opts['http_headers'] = headers

    # Configure formats based on format_id
    if direct_url:
        ydl_opts['format'] = 'best'
        ydl_opts['hls_prefer_native'] = True
        ydl_opts['outtmpl'] = os.path.join(dl_dir, f'{safe_title}.mp4')
    elif format_id:
        if ffmpeg_available:
            ydl_opts['format'] = f"{format_id}+bestaudio/best"
        else:
            ydl_opts['format'] = format_id
    else:
        if ffmpeg_available:
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        else:
            ydl_opts['format'] = 'best[ext=mp4]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if direct_url:
                with tasks_lock:
                    download_tasks[task_id].update({"platform": "RouVideo"})
                ydl.download([download_url])
            else:
                info = ydl.extract_info(download_url, download=False)
                filename = ydl.prepare_filename(info)
                # Keep downloaded thumbnail if local cache download failed
                final_thumb = local_thumb_url if local_thumb_url else info.get('thumbnail', task_thumbnail)
                with tasks_lock:
                    download_tasks[task_id].update({
                        "title": info.get('title', task_title),
                        "thumbnail": final_thumb,
                        "platform": info.get('extractor_key', 'Unknown'),
                        "filepath": filename
                    })
                ydl.download([download_url])

        # === Post-Download File Cleanup & Android Export (Runs only AFTER successful completion of ydl.download) ===
        with tasks_lock:
            task_info = download_tasks.get(task_id)
            filepath = task_info.get("filepath") if task_info else ""
            if not filepath:
                # Fallback path if not set during extract_info
                filepath = os.path.join(dl_dir, f'{safe_title}.mp4')

        final_filepath = filepath
        if filepath and os.path.exists(filepath):
            try:
                base_path, _ = os.path.splitext(filepath)
                for ext in ['.jpg', '.jpeg', '.png', '.webp', '.jpg.temp', '.webp.temp']:
                    img_path = base_path + ext
                    if os.path.exists(img_path):
                        os.remove(img_path)
            except Exception as ce:
                print("[Cleanup] Error deleting cover image:", ce)

            try:
                from android.os import Environment
                public_dir = os.path.join(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).getAbsolutePath(), "VeloceDownloads")
                os.makedirs(public_dir, exist_ok=True)
                
                filename = os.path.basename(filepath)
                public_filepath = os.path.join(public_dir, filename)
                
                if os.path.exists(public_filepath):
                    base, ext = os.path.splitext(filename)
                    public_filepath = os.path.join(public_dir, f"{base}_{int(time.time())}{ext}")
                    
                shutil.copy2(filepath, public_filepath)
                try:
                    os.remove(filepath)
                except Exception:
                    pass
                final_filepath = public_filepath
                print(f"[Android Export] Successfully exported video to public storage: {public_filepath}")
            except Exception as e_export:
                print("[Android Export] Export skipped or failed:", e_export)

        with tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "percent": 100.0,
                    "status": "finished",
                    "filepath": final_filepath
                })
                add_to_history(download_tasks[task_id])
        save_tasks_to_file()

    except Exception as e:
        err_msg = str(e)
        with tasks_lock:
            if task_id in download_tasks and download_tasks[task_id]['status'] != 'cancelled':
                if download_tasks[task_id]['status'] == 'paused':
                    pass
                else:
                    download_tasks[task_id].update({
                        "status": "error",
                        "error_msg": err_msg
                    })
        save_tasks_to_file()

# Web Routes
@app.route('/')
def index():
    # Allow deep linking on start page
    initial_url = request.args.get('url', '')
    # Serve index.html and inject initial_url for fast download parsing
    return app.send_static_file('index.html')

@app.route('/app.js')
def serve_app_js():
    return app.send_static_file('app.js')

@app.route('/style.css')
def serve_style_css():
    return app.send_static_file('style.css')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(static_folder_path, path)

@app.route('/api/analyze', methods=['POST'])
def analyze_link():
    data = request.json
    url = data.get('url')
    cookies = data.get('cookies', '')
    user_agent = data.get('user_agent', '')
    
    if not url:
        return jsonify({"success": False, "error": "URL is required"}), 400
    try:
        rou_meta = check_and_parse_rou_video(url)
        if rou_meta:
            return jsonify({"success": True, "metadata": rou_meta})
    except Exception as e:
        print("Error in custom rou.video scraper:", e)
    try:
        ydl_opts = {
            'extract_flat': False,
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        # Build headers for parser session to prevent anti-hotlinking blocks
        headers = {
            'User-Agent': user_agent if user_agent else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        from urllib.parse import urlparse
        try:
            parsed_uri = urlparse(url)
            headers['Referer'] = url
            headers['Origin'] = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
        except Exception:
            pass
            
        if cookies:
            headers['Cookie'] = cookies
            
        ydl_opts['http_headers'] = headers
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        formats_list = []
        raw_formats = info.get('formats', [])
        for f in raw_formats:
            if f.get('acodec') == 'none' and f.get('vcodec') == 'none':
                continue
            fid = f.get('format_id')
            ext = f.get('ext', '')
            resolution = f.get('resolution') or f.get('format_note') or f"{f.get('width', 0)}x{f.get('height', 0)}"
            filesize = f.get('filesize') or f.get('filesize_approx')
            has_video = f.get('vcodec') != 'none'
            has_audio = f.get('acodec') != 'none'
            
            size_str = "Unknown"
            if filesize:
                if filesize > 1024*1024*1024:
                    size_str = f"{round(filesize / (1024*1024*1024), 2)} GB"
                else:
                    size_str = f"{round(filesize / (1024*1024), 1)} MB"
            
            quality_label = resolution
            if has_video and not has_audio:
                quality_label += " (Video-only)"
            elif not has_video and has_audio:
                quality_label = f"Audio ({f.get('acodec', 'mp3')})"
                
            formats_list.append({
                "format_id": fid,
                "ext": ext,
                "resolution": resolution,
                "label": quality_label,
                "size": size_str,
                "filesize": filesize or 0,
                "has_video": has_video,
                "has_audio": has_audio,
                "fps": f.get('fps', '')
            })
            
        formats_list.sort(key=lambda x: (x['has_video'], x['filesize']), reverse=True)
        duration_raw = info.get('duration')
        duration_str = "Unknown"
        if duration_raw:
            if duration_raw > 3600:
                duration_str = time.strftime('%H:%M:%S', time.gmtime(duration_raw))
            else:
                duration_str = time.strftime('%M:%S', time.gmtime(duration_raw))
                
        metadata = {
            "title": info.get('title', 'Unknown Video'),
            "duration": duration_str,
            "thumbnail": info.get('thumbnail', ''),
            "author": info.get('uploader') or info.get('channel') or "Unknown Author",
            "platform": info.get('extractor_key', 'Generic Web'),
            "formats": formats_list,
            "url": url
        }
        return jsonify({"success": True, "metadata": metadata})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    title = data.get('title', 'Video Downloader Task')
    thumbnail = data.get('thumbnail', '')
    platform_name = data.get('platform', 'Unknown')
    size_str = data.get('size', 'Unknown')
    direct_url = data.get('direct_url')
    cookies = data.get('cookies', '')
    user_agent = data.get('user_agent', '')
    
    if not url:
        return jsonify({"success": False, "error": "URL is required"}), 400
        
    task_id = str(uuid.uuid4())
    settings = load_settings()
    with tasks_lock:
        download_tasks[task_id] = {
            "id": task_id,
            "url": url,
            "title": title,
            "thumbnail": thumbnail,
            "status": "downloading",
            "percent": 0.0,
            "speed": "0 KB/s",
            "eta": "Waiting...",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "size": size_str,
            "platform": platform_name,
            "filepath": "",
            "direct_url": direct_url,
            "cookies": cookies,
            "user_agent": user_agent,
            "format_id": format_id,
            "error_msg": None
        }
    save_tasks_to_file()
        
    thread = threading.Thread(
        target=execute_download,
        args=(task_id, url, format_id, settings)
    )
    thread.daemon = True
    thread.start()
    return jsonify({"success": True, "task_id": task_id})

@app.route('/api/pause', methods=['POST'])
def pause_download_route():
    data = request.json
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({"success": False, "error": "Task ID is required"}), 400
        
    with tasks_lock:
        task = download_tasks.get(task_id)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404
        task['status'] = 'paused'
        task['speed'] = '已暂停'
        task['eta'] = '--'
        
    save_tasks_to_file()
    return jsonify({"success": True})

@app.route('/api/resume', methods=['POST'])
def resume_download_route():
    data = request.json
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({"success": False, "error": "Task ID is required"}), 400
        
    with tasks_lock:
        task = download_tasks.get(task_id)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404
        task['status'] = 'downloading'
        task['error_msg'] = None
        task['speed'] = '正在恢复...'
        task['eta'] = '等待中...'
        url = task['url']
        format_id = task.get('format_id', '')
        
    settings = load_settings()
    thread = threading.Thread(
        target=execute_download,
        args=(task_id, url, format_id, settings)
    )
    thread.daemon = True
    thread.start()
    save_tasks_to_file()
    return jsonify({"success": True})

@app.route('/api/cancel', methods=['POST'])
def cancel_download_route():
    data = request.json
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({"success": False, "error": "Task ID is required"}), 400
        
    with tasks_lock:
        if task_id in download_tasks:
            download_tasks.pop(task_id)
            
    save_tasks_to_file()
    return jsonify({"success": True})

@app.route('/api/thumbnail', methods=['GET'])
def get_local_thumbnail():
    filepath = request.args.get('path')
    if not filepath or not os.path.exists(filepath):
        return jsonify({"success": False, "error": "File not found"}), 404
    dir_name = os.path.dirname(filepath)
    file_name = os.path.basename(filepath)
    return send_from_directory(dir_name, file_name)

@app.route('/api/proxy_image', methods=['GET'])
def proxy_image():
    url = request.args.get('url')
    referer = request.args.get('referer', '')
    cookies = request.args.get('cookies', '')
    ua = request.args.get('ua', '')
    
    if not url:
        return "URL is required", 400
        
    try:
        import urllib.request
        import ssl
        from urllib.parse import urlparse
        
        # Deduce a valid Referer if none provided (very useful for bypassing anti-hotlink blocks)
        if not referer:
            try:
                parsed_img = urlparse(url)
                referer = f"{parsed_img.scheme}://{parsed_img.netloc}/"
            except Exception:
                pass

        headers = {
            'User-Agent': ua if ua else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        if referer:
            headers['Referer'] = referer
        if cookies:
            headers['Cookie'] = cookies
            
        req = urllib.request.Request(url, headers=headers)
        
        # Bypass SSL verification to avoid CERTIFICATE_VERIFY_FAILED error on devices with outdated CAs
        ssl_context = ssl._create_unverified_context()
        
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            data = response.read()
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            return data, 200, {'Content-Type': content_type}
    except Exception as e:
        print("Error proxying image:", e)
        # Fallback to direct redirect
        from flask import redirect
        return redirect(url)

@app.route('/api/progress', methods=['GET'])
def get_progress():
    with tasks_lock:
        tasks = {tid: task.copy() for tid, task in download_tasks.items()}
    return jsonify({"success": True, "tasks": list(tasks.values())})

@app.route('/api/history', methods=['GET'])
def get_history_route():
    history = load_history()
    updated = False
    for item in history:
        if "duration" not in item or item["duration"] == "Unknown":
            dur = get_video_duration(item.get("filepath"))
            if dur:
                item["duration"] = dur
                updated = True
    if updated:
        save_history(history)
    return jsonify({"success": True, "history": history})

@app.route('/api/delete_history', methods=['POST'])
def delete_history_route():
    data = request.json
    task_id = data.get('id')
    delete_file = data.get('delete_file', True)
    
    if not task_id:
        return jsonify({"success": False, "error": "ID is required"}), 400
        
    history = load_history()
    new_history = [item for item in history if item["id"] != task_id]
    target_item = next((item for item in history if item["id"] == task_id), None)
    
    if not target_item:
        return jsonify({"success": False, "error": "Item not found"}), 404
        
    save_history(new_history)
    
    if delete_file and target_item.get("filepath"):
        filepath = target_item["filepath"]
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"[Delete] Deleted physical file: {filepath}")
            except Exception as e:
                print(f"Error removing physical file {filepath}: {e}")
                
    return jsonify({"success": True})

@app.route('/api/open_folder', methods=['POST'])
def open_downloads_folder():
    return jsonify({"success": True, "folder": DOWNLOADS_DIR})

@app.route('/api/debug_ffmpeg', methods=['GET'])
def debug_ffmpeg():
    diagnostic = {}
    try:
        from com.chaquo.python import Python
        context = Python.getPlatform().getApplication()
        
        native_lib_dir = context.getApplicationInfo().nativeLibraryDir
        libffmpeg_path = os.path.join(native_lib_dir, 'libffmpeg.so')
        diagnostic["lib_so"] = os.path.exists(libffmpeg_path)
        if os.path.exists(libffmpeg_path):
            diagnostic["lib_so_size"] = os.path.getsize(libffmpeg_path)
            
        private_bin = os.path.join(context.getFilesDir().getAbsolutePath(), 'bin')
        ffmpeg_bin_path = os.path.join(private_bin, 'ffmpeg')
        diagnostic["bin_file"] = os.path.exists(ffmpeg_bin_path)
        if os.path.exists(ffmpeg_bin_path):
            diagnostic["bin_size"] = os.path.getsize(ffmpeg_bin_path)
            diagnostic["bin_exec"] = os.access(ffmpeg_bin_path, os.X_OK)
            
        asset_manager = context.getAssets()
        try:
            input_stream = asset_manager.open("bin/ffmpeg")
            diagnostic["asset_file"] = True
            input_stream.close()
        except Exception as e_asset:
            diagnostic["asset_file"] = False
            diagnostic["asset_err"] = str(e_asset)[:100]
            
        diagnostic["PATH"] = os.environ.get("PATH", "")[:100]
        diagnostic["arch"] = platform.machine()
        
    except Exception as e:
        diagnostic["err"] = str(e)[:150]
        
    return jsonify({"success": True, "diagnostic": diagnostic})

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'GET':
        settings = load_settings()
        settings["ffmpeg_installed"] = is_ffmpeg_ready()
        return jsonify({"success": True, "settings": settings})
    elif request.method == 'POST':
        new_data = request.json
        new_dir = new_data.get('download_dir')
        if new_dir:
            new_dir = os.path.abspath(new_dir)
            try:
                os.makedirs(new_dir, exist_ok=True)
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 400
        settings = load_settings()
        if new_dir:
            settings['download_dir'] = new_dir
        if 'max_concurrent' in new_data:
            try:
                settings['max_concurrent'] = int(new_data['max_concurrent'])
            except ValueError:
                pass
        save_settings(settings)
        return jsonify({"success": True, "settings": settings})

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

def run_server():
    global DOWNLOADS_DIR, download_tasks
    
    # Setup private FFmpeg binary on Android dynamically
    try:
        from com.chaquo.python import Python
        context = Python.getPlatform().getApplication()
        native_lib_dir = context.getApplicationInfo().nativeLibraryDir
        private_bin = os.path.join(context.getFilesDir().getAbsolutePath(), 'bin')
        os.makedirs(private_bin, exist_ok=True)
        
        ffmpeg_bin_path = os.path.join(private_bin, 'ffmpeg')
        libffmpeg_path = os.path.join(native_lib_dir, 'libffmpeg.so')
        
        # 1. Try unpacking precompiled ffmpeg packaged as libffmpeg.so inside native jniLibs
        if os.path.exists(libffmpeg_path):
            if not os.path.exists(ffmpeg_bin_path) or os.path.getsize(ffmpeg_bin_path) != os.path.getsize(libffmpeg_path):
                shutil.copy2(libffmpeg_path, ffmpeg_bin_path)
                os.chmod(ffmpeg_bin_path, 0o755)
                print("[Android FFmpeg] Successfully unpacked executable ffmpeg from native library directory.")
        else:
            # 2. Fallback: try unpacking from main assets/bin/ffmpeg if present
            asset_manager = context.getAssets()
            try:
                input_stream = asset_manager.open("bin/ffmpeg")
                with open(ffmpeg_bin_path, 'wb') as dest_file:
                    buffer = bytearray(1024 * 64)
                    while True:
                        bytes_read = input_stream.read(buffer)
                        if bytes_read == -1 or bytes_read == 0:
                            break
                        dest_file.write(buffer[:bytes_read])
                input_stream.close()
                os.chmod(ffmpeg_bin_path, 0o755)
                print("[Android FFmpeg] Successfully unpacked executable ffmpeg from assets.")
            except Exception as e_asset:
                print("[Android FFmpeg] Asset ffmpeg extraction skipped or not found:", e_asset)
                
        # 3. Dynamic PATH injection for the current running process
        if private_bin not in os.environ["PATH"]:
            os.environ["PATH"] = private_bin + os.pathsep + os.environ["PATH"]
            
        # 4. Setup writable temp directory environment variables for Android compatibility
        cache_dir = context.getCacheDir().getAbsolutePath()
        os.environ["TMPDIR"] = cache_dir
        os.environ["TEMP"] = cache_dir
        os.environ["TMP"] = cache_dir
        print(f"[Android Env] Configured TMPDIR to writable app cache: {cache_dir}")
    except Exception as ea:
        print("[Android FFmpeg] Auto initialization error:", ea)

    # To bypass Android 10+ SELinux execution blocks on native binaries (like ffmpeg)
    # attempting to write to external/shared storage, we perform ALL downloads and merging
    # inside the App's private sandboxed files directory, and then copy the merged product to public downloads.
    DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "VeloceDownloads")
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        print(f"[Android Workspace] Set private workspace directory: {DOWNLOADS_DIR}")
    except Exception as ex:
        print("Failed to create private downloads dir:", ex)
            
    # Load task queue state and reset any active downloading/waiting tasks to paused on startup
    try:
        loaded_tasks = load_tasks_from_file()
        for tid, task in loaded_tasks.items():
            if task.get('status') in ['downloading', 'waiting']:
                task['status'] = 'paused'
                task['speed'] = '断线挂起'
                task['eta'] = '可恢复'
                task['error_msg'] = None
        with tasks_lock:
            download_tasks.update(loaded_tasks)
        save_tasks_to_file()
    except Exception as e:
        print("Error restoring tasks from JSON at startup:", e)
        
    app.run(host='127.0.0.1', port=5000, debug=False)
