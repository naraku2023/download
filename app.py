import os
import sys
import uuid
import json
import time
import shutil
import threading
import platform
from flask import Flask, request, jsonify, send_from_directory

# Ensure Flask and yt-dlp are installed.
try:
    import flask
    import yt_dlp
except ImportError:
    print("Error: Required dependencies not found. Please install flask and yt-dlp first.")
    # Exit with code 2 to indicate missing dependencies to the launcher script
    sys.exit(2)

app = Flask(__name__, static_folder='static')

@app.before_request
def handle_options_preflight():
    if request.method == 'OPTIONS':
        response = app.make_response('')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
        return response

# Add local bin directory to system PATH so yt-dlp and shutil.which can find ffmpeg
local_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin')
if os.path.isdir(local_bin):
    os.environ["PATH"] = local_bin + os.pathsep + os.environ["PATH"]


# Configurations
DOWNLOADS_DIR = os.path.join(os.getcwd(), 'downloads')
HISTORY_FILE = os.path.join(os.getcwd(), 'history.json')
SETTINGS_FILE = os.path.join(os.getcwd(), 'settings.json')
TASKS_FILE = os.path.join(os.getcwd(), 'tasks.json')
THUMBNAILS_DIR = os.path.join(os.getcwd(), 'thumbnails_cache')
if not os.path.exists(THUMBNAILS_DIR):
    os.makedirs(THUMBNAILS_DIR)

# Create necessary folders
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

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
            
        # Create metadata payload
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
        "max_concurrent": 3,
        "adblock_enabled": True,
        "popup_block_enabled": True,
        "picker_block_enabled": True
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                if "popup_block_enabled" not in settings:
                    settings["popup_block_enabled"] = True
                if "picker_block_enabled" not in settings:
                    settings["picker_block_enabled"] = True
                # Keep absolute path and fallback if folder is deleted
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

def add_to_history(task):
    history = load_history()
    # Format size to human-readable
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
    # Avoid duplicate titles if downloaded multiple times
    history = [h for h in history if h["id"] != task["id"]]
    history.insert(0, item)
    save_history(history[:50]) # limit to 50 items

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
            
            # Format speed
            speed = d.get('speed')
            speed_str = "0 KB/s"
            if speed:
                if speed > 1024 * 1024:
                    speed_str = f"{round(speed / (1024*1024), 1)} MB/s"
                else:
                    speed_str = f"{round(speed / 1024, 1)} KB/s"
            
            # Format ETA
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
            # Do not perform final cleanup or history write here to avoid deleting/handling files before FFmpeg merges them.
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
    
    # Read task metadata
    with tasks_lock:
        task = download_tasks.get(task_id)
        direct_url = task.get("direct_url") if task else None
        task_title = task.get("title", "video") if task else "video"
        task_thumbnail = task.get("thumbnail", "") if task else ""
        
    # === For rou.video: always re-fetch a fresh signed URL at download time ===
    # Cached signed URLs may expire or get throttled; re-decrypt from the original page
    if "rou.video" in url:
        print(f"[RouVideo] Re-fetching fresh signed URL from: {url}")
        fresh_meta = check_and_parse_rou_video(url)
        if fresh_meta and fresh_meta.get("formats"):
            fresh_url = fresh_meta["formats"][0].get("direct_url")
            if fresh_url:
                direct_url = fresh_url
                print(f"[RouVideo] Got fresh URL (first 80 chars): {fresh_url[:80]}...")
            else:
                print("[RouVideo] WARNING: Could not extract fresh direct_url from page")
        else:
            print("[RouVideo] WARNING: Re-parse failed, using cached URL")
    
    download_url = direct_url if direct_url else url
    
    # Check if ffmpeg is available
    ffmpeg_available = shutil.which("ffmpeg") is not None
    
    # Safe filename from task title
    safe_title = "".join(c if c.isalnum() or c in ' -_.' else '_' for c in task_title)[:80]

    # yt-dlp configurations
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

    # Special handling for direct_url (scraped streams like rou.video disguised as .jpg)
    if direct_url:
        ydl_opts['format'] = 'best'
        ydl_opts['hls_prefer_native'] = True
        ydl_opts['outtmpl'] = os.path.join(dl_dir, f'{safe_title}.mp4')
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://rou.video/',
            'Origin': 'https://rou.video',
        }
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
                with tasks_lock:
                    download_tasks[task_id].update({
                        "title": info.get('title', task_title),
                        "thumbnail": info.get('thumbnail', task_thumbnail),
                        "platform": info.get('extractor_key', 'Unknown'),
                        "filepath": filename
                    })
                ydl.download([download_url])

        # === Post-Download File Cleanup & History Addition ===
        # Determine the final downloaded filepath
        with tasks_lock:
            task_info = download_tasks.get(task_id)
            filepath = task_info.get("filepath") if task_info else ""
            if not filepath:
                filepath = os.path.join(dl_dir, f'{safe_title}.mp4')

        # Try to extract keyframe from the completed video if thumbnail is missing/fallback
        final_thumb = task_thumbnail
        if filepath and os.path.exists(filepath):
            if not final_thumb or final_thumb == "Unknown" or not (final_thumb.startswith("http") or final_thumb.startswith("/api/")):
                try:
                    local_thumb_path = os.path.join(THUMBNAILS_DIR, f"{task_id}.jpg")
                    if extract_video_keyframe(filepath, local_thumb_path):
                        final_thumb = f"/api/thumbnail?path={local_thumb_path}"
                except Exception as e_thumb:
                    print("[Keyframe] Error setting up keyframe cache:", e_thumb)

        if filepath and os.path.exists(filepath):
            try:
                base_path, _ = os.path.splitext(filepath)
                for ext in ['.jpg', '.jpeg', '.png', '.webp', '.jpg.temp', '.webp.temp']:
                    img_path = base_path + ext
                    if os.path.exists(img_path):
                        os.remove(img_path)
            except Exception as ce:
                print("[Cleanup] Error deleting cover image:", ce)

        with tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "percent": 100.0,
                    "status": "finished",
                    "filepath": filepath,
                    "thumbnail": final_thumb
                })
                add_to_history(download_tasks[task_id])
        save_tasks_to_file()

    except Exception as e:
        err_msg = str(e)
        print(f"[Download Error] task_id={task_id}: {err_msg}")
        
        # === Fallback: use ffmpeg directly for HLS streams if yt-dlp fails ===
        if direct_url and ffmpeg_available and "timed out" in err_msg.lower():
            print("[Fallback] yt-dlp timed out on HLS stream, trying ffmpeg directly...")
            try:
                output_path = os.path.join(dl_dir, f'{safe_title}.mp4')
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-headers", "Referer: https://rou.video/\r\nOrigin: https://rou.video\r\n",
                    "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "-i", download_url,
                    "-c", "copy",
                    "-bsf:a", "aac_adtstoasc",
                    output_path
                ]
                import subprocess
                proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                stdout, stderr = proc.communicate(timeout=3600)
                if proc.returncode == 0 and os.path.exists(output_path):
                    print(f"[Fallback] ffmpeg succeeded: {output_path}")
                    with tasks_lock:
                        if task_id in download_tasks:
                            download_tasks[task_id].update({
                                "status": "finished",
                                "percent": 100.0,
                                "filepath": output_path
                            })
                            add_to_history(download_tasks[task_id])
                    return
                else:
                    err_msg = f"ffmpeg fallback failed: {stderr.decode('utf-8', errors='ignore')[-300:]}"
                    print(f"[Fallback] {err_msg}")
            except Exception as fe:
                err_msg = f"ffmpeg fallback exception: {str(fe)}"
                print(f"[Fallback] {err_msg}")

        # Mark task as error
        with tasks_lock:
            if task_id in download_tasks and download_tasks[task_id]['status'] != 'cancelled':
                download_tasks[task_id].update({
                    "status": "error",
                    "error_msg": err_msg
                })






# Routes
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/app.js')
def serve_app_js():
    return app.send_static_file('app.js')

@app.route('/style.css')
def serve_style_css():
    return app.send_static_file('style.css')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/api/analyze', methods=['POST'])
def analyze_link():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"success": False, "error": "URL is required"}), 400
    
    # 1. Try our custom site scrapers first (e.g. rou.video)
    try:
        rou_meta = check_and_parse_rou_video(url)
        if rou_meta:
            return jsonify({"success": True, "metadata": rou_meta})
    except Exception as e:
        print("Error in custom rou.video scraper:", e)
    
    # 2. Standard yt-dlp analysis
    try:
        ydl_opts = {
            'extract_flat': False,
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        # Parse formats
        formats_list = []
        raw_formats = info.get('formats', [])
        
        # Format list parsing
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
            
            # Labeling details
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
            
        # Re-sort formats (highest resolution first)
        formats_list.sort(key=lambda x: (x['has_video'], x['filesize']), reverse=True)
        
        # Format duration to MM:SS or HH:MM:SS
        duration_raw = info.get('duration')
        duration_str = "Unknown"
        if duration_raw:
            if duration_raw > 3600:
                duration_str = time.strftime('%H:%M:%S', time.gmtime(duration_raw))
            else:
                duration_str = time.strftime('%M:%S', time.gmtime(duration_raw))
                
        # Format return payload
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
    duration_str = data.get('duration', 'Unknown')
    direct_url = data.get('direct_url')
    
    if not url:
        return jsonify({"success": False, "error": "URL is required"}), 400
        
    task_id = str(uuid.uuid4())
    settings = load_settings()
    
    # Initialize task metadata
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
            "duration": duration_str,
            "filepath": "",
            "direct_url": direct_url,
            "error_msg": None
        }
        
    # Launch backend downloading thread
    thread = threading.Thread(
        target=execute_download,
        args=(task_id, url, format_id, settings)
    )
    thread.daemon = True
    thread.start()
    save_tasks_to_file()
    
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

@app.route('/api/progress', methods=['GET'])
def get_progress():
    with tasks_lock:
        # Filter and send copy of current task states
        tasks = {tid: task.copy() for tid, task in download_tasks.items()}
    return jsonify({"success": True, "tasks": list(tasks.values())})

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

def extract_video_keyframe(video_path, output_image_path):
    if not video_path or not os.path.exists(video_path):
        return False
    try:
        import subprocess
        ffmpeg_path = shutil.which("ffmpeg") or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin', 'ffmpeg.exe')
        if not ffmpeg_path or not os.path.exists(ffmpeg_path) and not shutil.which("ffmpeg"):
            print("[Keyframe] ffmpeg not found, skipping frame extraction.")
            return False

        # Extract frame at 2 seconds
        cmd = [
            ffmpeg_path,
            "-y",
            "-ss", "00:00:02",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            output_image_path
        ]
        
        startupinfo = None
        if platform.system() == 'Windows':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        stdout, stderr = proc.communicate(timeout=8)
        if proc.returncode == 0 and os.path.exists(output_image_path):
            print(f"[Keyframe] Successfully extracted video frame: {output_image_path}")
            return True
        else:
            cmd[4] = "00:00:00"
            proc2 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            proc2.communicate(timeout=5)
            if proc2.returncode == 0 and os.path.exists(output_image_path):
                print(f"[Keyframe] Successfully extracted video frame at 0s: {output_image_path}")
                return True
            print(f"[Keyframe] ffmpeg failed to extract frame: {stderr.decode('utf-8', errors='ignore')}")
    except Exception as e:
        print("[Keyframe] Exception during frame extraction:", e)
    return False

def get_video_duration(filepath):
    if not filepath or not os.path.exists(filepath):
        return None
    # 1. Try ffprobe first
    try:
        import subprocess
        ffprobe_path = shutil.which("ffprobe") or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin', 'ffprobe.exe')
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

@app.route('/api/open_folder', methods=['POST'])
def open_downloads_folder():
    settings = load_settings()
    dl_dir = settings.get("download_dir", DOWNLOADS_DIR)
    
    try:
        if not os.path.exists(dl_dir):
            os.makedirs(dl_dir, exist_ok=True)
            
        if platform.system() == 'Windows':
            os.startfile(dl_dir)
        elif platform.system() == 'Darwin': # macOS
            subprocess.Popen(['open', dl_dir])
        else: # Linux
            subprocess.Popen(['xdg-open', dl_dir])
            
        return jsonify({"success": True, "folder": dl_dir})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/play_video', methods=['POST'])
def play_downloaded_video():
    filepath = request.json.get('filepath')
    if not filepath or not os.path.exists(filepath):
        return jsonify({"success": False, "error": "File does not exist"}), 400
        
    try:
        if platform.system() == 'Windows':
            os.startfile(filepath)
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', filepath])
        else:
            subprocess.Popen(['xdg-open', filepath])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/cancel', methods=['POST'])
def cancel_task():
    task_id = request.json.get('task_id')
    if not task_id:
        return jsonify({"success": False, "error": "Task ID is required"}), 400
        
    with tasks_lock:
        if task_id in download_tasks:
            download_tasks.pop(task_id)
            
    save_tasks_to_file()
    return jsonify({"success": True})

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'GET':
        settings = load_settings()
        # Add support info
        settings["ffmpeg_installed"] = shutil.which("ffmpeg") is not None
        return jsonify({"success": True, "settings": settings})
        
    elif request.method == 'POST':
        new_data = request.json
        new_dir = new_data.get('download_dir')
        
        if new_dir:
            # Standardize path
            new_dir = os.path.abspath(new_dir)
            try:
                if not os.path.exists(new_dir):
                    os.makedirs(new_dir, exist_ok=True)
            except Exception as e:
                return jsonify({"success": False, "error": f"Invalid or non-writable directory path: {str(e)}"}), 400
                
        settings = load_settings()
        if new_dir:
            settings['download_dir'] = new_dir
        if 'max_concurrent' in new_data:
            try:
                settings['max_concurrent'] = int(new_data['max_concurrent'])
            except ValueError:
                pass
        if 'adblock_enabled' in new_data:
            settings['adblock_enabled'] = bool(new_data['adblock_enabled'])
        if 'popup_block_enabled' in new_data:
            settings['popup_block_enabled'] = bool(new_data['popup_block_enabled'])
        if 'picker_block_enabled' in new_data:
            settings['picker_block_enabled'] = bool(new_data['picker_block_enabled'])
                
        save_settings(settings)
        return jsonify({"success": True, "settings": settings})

# FFmpeg Auto Installer State
ffmpeg_install_state = {
    "status": "idle",       # "idle", "downloading", "extracting", "success", "error"
    "progress": 0,          # percentage
    "message": ""           # text
}
ffmpeg_install_lock = threading.Lock()

def download_ffmpeg_thread():
    global ffmpeg_install_state
    import urllib.request
    import zipfile
    
    zip_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    local_zip = os.path.join(os.getcwd(), 'ffmpeg_temp.zip')
    bin_dir = os.path.join(os.getcwd(), 'bin')
    
    try:
        with ffmpeg_install_lock:
            ffmpeg_install_state.update({
                "status": "downloading",
                "progress": 0,
                "message": "正在连接 FFmpeg 官方高速下载源..."
            })
        
        req = urllib.request.Request(
            zip_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            total_size = int(response.info().get('Content-Length', 0))
            downloaded = 0
            block_size = 1024 * 64  # 64KB chunks
            
            with open(local_zip, 'wb') as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    downloaded += len(buffer)
                    if total_size > 0:
                        pct = int((downloaded / total_size) * 100)
                        # Cap at 95% during download to leave room for extraction
                        pct = min(pct, 95)
                        with ffmpeg_install_lock:
                            ffmpeg_install_state.update({
                                "progress": pct,
                                "message": f"正在下载 FFmpeg... {pct}%"
                            })
                    else:
                        mb = downloaded // (1024 * 1024)
                        with ffmpeg_install_lock:
                            ffmpeg_install_state.update({
                                "message": f"正在下载 FFmpeg... 已下载 {mb} MB"
                            })
        
        # Extract files
        with ffmpeg_install_lock:
            ffmpeg_install_state.update({
                "status": "extracting",
                "progress": 96,
                "message": "下载完成，正在解压部署二进制文件..."
            })
            
        if not os.path.exists(bin_dir):
            os.makedirs(bin_dir)
            
        extracted_count = 0
        with zipfile.ZipFile(local_zip, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                filename = os.path.basename(file_info.filename)
                if filename in ['ffmpeg.exe', 'ffprobe.exe']:
                    # Extract directly to bin_dir/filename
                    with zip_ref.open(file_info) as source, open(os.path.join(bin_dir, filename), 'wb') as target:
                        shutil.copyfileobj(source, target)
                    extracted_count += 1
        
        # Clean up zip
        if os.path.exists(local_zip):
            os.remove(local_zip)
            
        if extracted_count < 2:
            raise Exception("解压错误：未能从下载的 essentials 包中提取到 ffmpeg.exe 或 ffprobe.exe")
            
        # Add to PATH dynamically for current process
        if bin_dir not in os.environ["PATH"]:
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
            
        with ffmpeg_install_lock:
            ffmpeg_install_state.update({
                "status": "success",
                "progress": 100,
                "message": "FFmpeg 便携包部署成功！环境已就绪。"
            })
            
    except Exception as e:
        if os.path.exists(local_zip):
            try:
                os.remove(local_zip)
            except Exception:
                pass
        with ffmpeg_install_lock:
            ffmpeg_install_state.update({
                "status": "error",
                "progress": 0,
                "message": f"安装失败：{str(e)}"
            })

@app.route('/api/install_ffmpeg', methods=['POST'])
def trigger_install_ffmpeg():
    # Only allow for Windows OS in this endpoint, others should have pre-bundled/pre-installed binaries
    if platform.system() != 'Windows':
        return jsonify({"success": False, "error": "本自动安装仅适用于 Windows 系统，其他系统请预先安装 FFmpeg"}), 400
        
    with ffmpeg_install_lock:
        if ffmpeg_install_state["status"] in ["downloading", "extracting"]:
            return jsonify({"success": True, "message": "已有正在进行的安装任务"})
            
        ffmpeg_install_state.update({
            "status": "downloading",
            "progress": 0,
            "message": "准备下载..."
        })
        
    thread = threading.Thread(target=download_ffmpeg_thread)
    thread.daemon = True
    thread.start()
    return jsonify({"success": True})

@app.route('/api/install_status', methods=['GET'])
def get_install_ffmpeg_status():
    with ffmpeg_install_lock:
        state = ffmpeg_install_state.copy()
    return jsonify({"success": True, "state": state})

if __name__ == '__main__':
    # Restore tasks queue from tasks.json on startup
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

    # Try opening the browser automatically on port 5000
    print("--------------------------------------------------")
    print("Veloce Downloader Backend is starting...")
    print("Default download directory: ", DOWNLOADS_DIR)
    print("Go to http://127.0.0.1:5000 to use the application")
    print("--------------------------------------------------")
    app.run(host='127.0.0.1', port=5000, debug=False)
