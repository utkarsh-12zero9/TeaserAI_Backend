import yt_dlp
from pathlib import Path
from app.services.video import get_ffmpeg_path

class QuietLogger:
    def debug(self, msg):
        pass
    def info(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        pass


def download_youtube_video(url: str, output_dir: Path, video_id: str) -> str:
    """
    Downloads the best quality video + audio and merges them into an MP4 file.
    Returns the absolute path of the downloaded file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # We define the output template path with %(ext)s extension so yt-dlp always appends the correct extension.
    output_template = str((output_dir / f"{video_id}.%(ext)s").resolve())
    
    ffmpeg_path = get_ffmpeg_path()
    if Path(ffmpeg_path).is_absolute() or Path(ffmpeg_path).exists():
        ffmpeg_location = str(Path(ffmpeg_path).resolve())
    else:
        ffmpeg_location = ffmpeg_path

    ydl_opts = {
        # High quality 1080p Full HD video + audio stream selection
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[ext=mp4]/best',
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'ffmpeg_location': ffmpeg_location,
        'quiet': True,
        'no_warnings': True,
        'logger': QuietLogger(),
        'updatetime': False,
        'restrictfilenames': True,
        'windowsfilenames': True,
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
        # Anti-bot bypass configurations
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        }
    }

    # 1. Try direct fast download first (instant for 95% of public YouTube videos)
    try:
        cookie_file = Path("cookies.txt")
        if cookie_file.exists():
            ydl_opts['cookiefile'] = str(cookie_file.resolve())
        cookie_file = Path("cookies.txt")
        if cookie_file.exists():
            ydl_opts['cookiefile'] = str(cookie_file.resolve())
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get('ext', 'mp4')
            final_path = output_dir / f"{video_id}.{ext}"
            if not final_path.exists():
                for file_path in output_dir.glob(f"{video_id}.*"):
                    if file_path.is_file() and file_path.suffix.lower() in {'.mp4', '.mkv', '.webm', '.mov'}:
                        return str(file_path)
            return str(final_path)
    except Exception as direct_err:
        last_exception = direct_err

    # 2. Fallback to browser cookies if direct download fails due to anti-bot checks
    browsers_to_try = ['chrome', 'brave', 'edge', 'firefox', 'opera']
    for browser in browsers_to_try:
        current_opts = ydl_opts.copy()
        current_opts['cookiesfrombrowser'] = (browser,)
        try:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info.get('ext', 'mp4')
                final_path = output_dir / f"{video_id}.{ext}"
                if not final_path.exists():
                    for file_path in output_dir.glob(f"{video_id}.*"):
                        if file_path.is_file() and file_path.suffix.lower() in {'.mp4', '.mkv', '.webm', '.mov'}:
                            return str(file_path)
                return str(final_path)
        except Exception as e:
            last_exception = e
            continue

    raise last_exception or RuntimeError("Failed to download YouTube video")

def download_youtube_audio_only(url: str, output_dir: Path, video_id: str, audio_dir: Path) -> str:
    """
    Downloads only the audio stream from a YouTube URL.
    """
    import yt_dlp
    
    # We define the output template path with %(ext)s extension so yt-dlp always appends the correct extension.
    output_template = str((output_dir / f"{video_id}_audio.%(ext)s").resolve())
    
    ffmpeg_path = get_ffmpeg_path()
    if Path(ffmpeg_path).is_absolute() or Path(ffmpeg_path).exists():
        ffmpeg_location = str(Path(ffmpeg_path).resolve())
    else:
        ffmpeg_location = ffmpeg_path

    cookie_file = None
    for p in [Path(__file__).parent.parent.parent / "cookies.txt", Path("cookies.txt"), Path.cwd() / "cookies.txt"]:
        if p.exists():
            cookie_file = str(p.resolve())
            break

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio[abr<=64]/bestaudio/best',
        'outtmpl': output_template,
        'ffmpeg_location': ffmpeg_location,
        'quiet': True,
        'no_warnings': True,
        'logger': QuietLogger(),
        'updatetime': False,
        'restrictfilenames': True,
        'windowsfilenames': True,
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
    }
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        cookie_file = Path("cookies.txt")
        if cookie_file.exists():
            ydl_opts['cookiefile'] = str(cookie_file.resolve())
        cookie_file = Path("cookies.txt")
        if cookie_file.exists():
            ydl_opts['cookiefile'] = str(cookie_file.resolve())
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get('ext', 'mp3')
            final_path = output_dir / f"{video_id}_audio.{ext}"
            if not final_path.exists():
                for file_path in output_dir.glob(f"{video_id}_audio.*"):
                    if file_path.is_file():
                        return str(file_path)
            # Re-encode downloaded audio to MP3 using ffmpeg if it's not mp3
            if ext != 'mp3':
                duration = info.get('duration', 0)
                bitrate = "16k" if duration > 1800 else "32k"
                extracted_mp3 = audio_dir / f"{video_id}.mp3"
                cmd = [ffmpeg_location, "-y", "-i", str(final_path), "-vn", "-acodec", "mp3", "-ar", "16000", "-ac", "1", "-b:a", bitrate, str(extracted_mp3)]
                import subprocess
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return str(extracted_mp3)
            return str(final_path)
    except Exception as direct_err:
        last_exception = direct_err

    # Try fallback browsers
    browsers_to_try = ['chrome', 'brave', 'edge', 'firefox', 'opera']
    for browser in browsers_to_try:
        current_opts = ydl_opts.copy()
        current_opts['cookiesfrombrowser'] = (browser,)
        try:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info.get('ext', 'mp3')
                final_path = output_dir / f"{video_id}_audio.{ext}"
                if not final_path.exists():
                    for file_path in output_dir.glob(f"{video_id}_audio.*"):
                        if file_path.is_file():
                            return str(file_path)
                # Re-encode downloaded audio to MP3
                if ext != 'mp3':
                    duration = info.get('duration', 0)
                    bitrate = "16k" if duration > 1800 else "32k"
                    extracted_mp3 = audio_dir / f"{video_id}.mp3"
                    cmd = [ffmpeg_location, "-y", "-i", str(final_path), "-vn", "-acodec", "mp3", "-ar", "16000", "-ac", "1", "-b:a", bitrate, str(extracted_mp3)]
                    import subprocess
                    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    
                    # Clean up intermediate raw audio (.m4a) from uploads/
                    try:
                        final_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                        
                    return str(extracted_mp3)
                return str(final_path)
        except Exception as e:
            last_exception = e
            continue

    raise last_exception or RuntimeError("Failed to download YouTube audio")

def download_youtube_sections(url: str, output_dir: Path, video_id: str, highlights: list) -> list[dict]:
    """
    Downloads only the specified sections of a YouTube video in parallel.
    Returns the list of downloaded file paths mapped to start/end relative offsets.
    """
    import yt_dlp
    from concurrent.futures import ThreadPoolExecutor
    from yt_dlp.utils import download_range_func

    ffmpeg_path = get_ffmpeg_path()
    if Path(ffmpeg_path).is_absolute() or Path(ffmpeg_path).exists():
        ffmpeg_location = str(Path(ffmpeg_path).resolve())
    else:
        ffmpeg_location = ffmpeg_path

    # Merge overlapping or close ranges (2.0s gap tolerance)
    clips = highlights.get("clips", [])
    ranges = []
    for idx, clip in enumerate(clips):
        ranges.append((float(clip["start"]), float(clip["end"]), idx))

    # Sort ranges
    sorted_ranges = sorted(ranges, key=lambda r: r[0])
    merged_ranges = []
    if sorted_ranges:
        merged_ranges = [[sorted_ranges[0]]]
        for current in sorted_ranges[1:]:
            prev_group = merged_ranges[-1]
            prev_start = min(r[0] for r in prev_group)
            prev_end = max(r[1] for r in prev_group)
            curr_start = current[0]
            if curr_start <= prev_end + 2.0:
                prev_group.append(current)
            else:
                merged_ranges.append([current])

    # Download each merged group to its own file
    results = {}
    
    def download_range(group_idx, group_ranges):
        start = min(r[0] for r in group_ranges)
        end = max(r[1] for r in group_ranges)
        
        output_template = str((output_dir / f"{video_id}_sec_{group_idx}.%(ext)s").resolve())
        
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[ext=mp4]/best',
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'ffmpeg_location': ffmpeg_location,
            'quiet': True,
            'no_warnings': True,
            'logger': QuietLogger(),
            'updatetime': False,
            'restrictfilenames': True,
            'windowsfilenames': True,
            'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
            'download_ranges': download_range_func(None, [(start, end)]),
            'force_keyframes_at_cuts': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web']
                }
            },
            'geo_bypass': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            }
        }
        
        cookie_file = Path("cookies.txt")
        if cookie_file.exists():
            ydl_opts['cookiefile'] = str(cookie_file.resolve())
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get('ext', 'mp4')
            final_path = output_dir / f"{video_id}_sec_{group_idx}.{ext}"
            if not final_path.exists():
                for file_path in output_dir.glob(f"{video_id}_sec_{group_idx}.*"):
                    if file_path.is_file() and file_path.suffix.lower() in {'.mp4', '.mkv', '.webm', '.mov'}:
                        return str(file_path), start
            return str(final_path), start

    # Run downloads in parallel (max 3 workers)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(download_range, idx, group)
            for idx, group in enumerate(merged_ranges)
        ]
        results_list = [f.result() for f in futures]

    # Map original highlights to local_path and offsets
    mapped_clips = []
    for idx, group in enumerate(merged_ranges):
        sec_path, sec_start = results_list[idx]
        for r_start, r_end, clip_idx in group:
            mapped_clips.append({
                "clip_id": f"clip_{clip_idx + 1}",
                "start": r_start - sec_start,
                "end": r_end - sec_start,
                "duration": r_end - r_start,
                "text": clips[clip_idx].get("text", ""),
                "local_path": sec_path,
                "orig_idx": clip_idx
            })

    mapped_clips.sort(key=lambda x: x["orig_idx"])
    return mapped_clips
