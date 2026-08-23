import subprocess
import shutil
import os
from pathlib import Path


def get_ffmpeg_path() -> str:
    # Check if in PATH
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return ffmpeg_bin
        
    # Fallback to local winget packages path if on Windows
    if os.name == 'nt':
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if winget_packages.exists():
                for p in winget_packages.glob("**/ffmpeg.exe"):
                    if p.is_file():
                        return str(p)
    return "ffmpeg"


def get_ffprobe_path() -> str:
    # Check if in PATH
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        return ffprobe_bin
        
    # Fallback to local winget packages path if on Windows
    if os.name == 'nt':
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if winget_packages.exists():
                for p in winget_packages.glob("**/ffprobe.exe"):
                    if p.is_file():
                        return str(p)
    return "ffprobe"


def get_audio_duration(audio_path: str) -> float:
    command = [
        get_ffprobe_path(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fallback to parsing ffmpeg output if ffprobe fails or is missing
        ffmpeg_command = [
            get_ffmpeg_path(),
            "-i",
            audio_path
        ]
        ffmpeg_result = subprocess.run(
            ffmpeg_command,
            capture_output=True,
            text=True,
        )
        for line in ffmpeg_result.stderr.splitlines():
            if "Duration:" in line:
                try:
                    duration_str = line.split("Duration:")[1].split(",")[0].strip()
                    h, m, s = duration_str.split(":")
                    return float(h) * 3600 + float(m) * 60 + float(s)
                except Exception:
                    pass
        raise RuntimeError(
            f"Failed to get audio duration:\n{result.stderr}\nFFmpeg error:\n{ffmpeg_result.stderr}"
        )
    return float(result.stdout.strip())


def split_audio_into_chunks(
    audio_path: str,
    chunk_duration_sec: float = 300.0,
    overlap_sec: float = 10.0
) -> list[dict]:
    duration = get_audio_duration(audio_path)
    audio_path_obj = Path(audio_path)
    chunks = []
    
    start = 0.0
    chunk_idx = 0
    while start < duration:
        chunk_end = start + chunk_duration_sec
        actual_end = min(chunk_end + overlap_sec, duration)
        actual_duration = actual_end - start
        
        if actual_duration <= 0:
            break
            
        chunk_file = audio_path_obj.parent / f"{audio_path_obj.stem}_chunk_{chunk_idx}{audio_path_obj.suffix}"
        
        command = [
            get_ffmpeg_path(),
            "-y",
            "-ss", str(start),
            "-i", audio_path,
            "-t", str(actual_duration),
            "-c:a", "copy",
            str(chunk_file)
        ]
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to split audio chunk {chunk_idx}:\n{result.stderr}")
            
        chunks.append({
            "path": str(chunk_file),
            "start": start,
            "end": chunk_end,
            "actual_end": actual_end
        })
        
        start = chunk_end
        chunk_idx += 1
        
    return chunks


def extract_audio(
    video_path: str,
    audio_path: str
) -> None:

    command = [
        get_ffmpeg_path(),

        "-y",

        "-i",
        video_path,

        "-vn",

        "-acodec",
        "mp3",

        "-ar",
        "16000",

        "-ac",
        "1",

        audio_path,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

# returncode == 0 mtlb ki successfull
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed:\n{result.stderr}"
        )


    