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
        # Select best mp4 video or merge streams into mp4
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'ffmpeg_location': ffmpeg_location,
        'quiet': True,
        'no_warnings': True,
        'logger': QuietLogger(),
        'updatetime': False,
        'restrictfilenames': True,
        'windowsfilenames': True,
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
    
    # Try different browser cookie sources to bypass bot checks, falling back to no cookies if they fail
    browsers_to_try = ['chrome', 'brave', 'edge', 'firefox', 'opera', 'safari']
    last_exception = None
    
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
            
    # Final fallback if all cookie providers fail
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get('ext', 'mp4')
            final_path = output_dir / f"{video_id}.{ext}"
            if not final_path.exists():
                for file_path in output_dir.glob(f"{video_id}.*"):
                    if file_path.is_file() and file_path.suffix.lower() in {'.mp4', '.mkv', '.webm', '.mov'}:
                        return str(file_path)
            return str(final_path)
    except Exception as e:
        # Re-raise the original or final exception
        raise last_exception or e
