from pathlib import Path
import subprocess
from app.services.video import get_ffmpeg_path


CLIPS_DIR = Path("clips")

CLIPS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


import concurrent.futures


def create_single_clip(index: int, highlight: dict, video_path: str, video_clips_dir: Path) -> dict:
    source_path = highlight.get("local_path") if highlight.get("local_path") else video_path
    start = highlight["start"]
    end = highlight["end"]
    duration = max(1.0, end - start)
    clip_filename = f"clip_{index}.mp4"
    clip_path = video_clips_dir / clip_filename

    # If this is a pre-clipped local segment from YouTube, we seek starting at 0
    seek_start = 0.0 if highlight.get("local_path") else start

    command = [
        get_ffmpeg_path(),
        "-y",
        "-ss", str(seek_start),
        "-i", source_path,
        "-t", str(duration),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(clip_path),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not clip_path.exists() or clip_path.stat().st_size == 0:
        # Fast encoding fallback if stream copy fails
        fallback_command = [
            get_ffmpeg_path(),
            "-y",
            "-ss", str(seek_start),
            "-i", source_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "22",
            "-c:a", "aac",
            str(clip_path),
        ]
        subprocess.run(fallback_command, check=True)

    return {
        "clip_id": f"clip_{index}",
        "start": start,
        "end": end,
        "duration": duration,
        "reason": highlight.get("text", ""),
        "clip_url": f"/clips/{video_clips_dir.name}/{clip_filename}",
        "index": index,
    }


def create_clips(
    video_path: str,
    highlights: dict,
):
    video_id = Path(video_path).stem
    video_clips_dir = CLIPS_DIR / video_id
    video_clips_dir.mkdir(parents=True, exist_ok=True)

    clip_items = list(enumerate(highlights.get("clips", []), start=1))
    if not clip_items:
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(clip_items))) as executor:
        futures = [
            executor.submit(create_single_clip, index, highlight, video_path, video_clips_dir)
            for index, highlight in clip_items
        ]
        clips = [f.result() for f in concurrent.futures.as_completed(futures)]

    clips.sort(key=lambda x: x["index"])
    for clip in clips:
        del clip["index"]

    return clips


def merge_clips(
    video_id: str,
    clips: list[dict],
):
    video_clips_dir = CLIPS_DIR / video_id
    concat_file = video_clips_dir / "concat.txt"
    teaser_path = video_clips_dir / "teaser.mp4"

    total_duration = sum(float(clip.get("duration", 0)) for clip in clips)
    fade_duration = min(0.5, total_duration / 2)
    fade_out_start = max(0, total_duration - fade_duration)

    concat_file.write_text(
        "\n".join(
            f"file '{Path(clip['clip_url']).name}'"
            for clip in clips
        ),
        encoding="utf-8",
    )

    command = [
        get_ffmpeg_path(),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        f"fade=t=in:st=0:d={fade_duration},fade=t=out:st={fade_out_start}:d={fade_duration}",
        "-af",
        f"afade=t=in:st=0:d={fade_duration},afade=t=out:st={fade_out_start}:d={fade_duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "22",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(teaser_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not teaser_path.exists() or teaser_path.stat().st_size == 0:
        raise RuntimeError(f"FFmpeg merge failed:\n{result.stderr}")

    return f"/clips/{video_id}/teaser.mp4"