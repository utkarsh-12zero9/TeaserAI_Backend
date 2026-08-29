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

    # Calculate dynamic fade duration (max 0.5s, adjusted for very short clips)
    fade_dur = min(0.5, duration / 2.0)
    video_filter = f"fade=t=in:st=0:d={fade_dur:.3f},fade=t=out:st={duration - fade_dur:.3f}:d={fade_dur:.3f}"
    audio_filter = f"afade=t=in:ss=0:d={fade_dur:.3f},afade=t=out:st={duration - fade_dur:.3f}:d={fade_dur:.3f}"

    command = [
        get_ffmpeg_path(),
        "-y",
        "-ss", str(seek_start),
        "-i", source_path,
        "-t", str(duration),
        "-vf", video_filter,
        "-af", audio_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "22",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        str(clip_path),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        # Fallback if audio filter fails (e.g. video has no audio track)
        fallback_command = [
            get_ffmpeg_path(),
            "-y",
            "-ss", str(seek_start),
            "-i", source_path,
            "-t", str(duration),
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "22",
            "-an",
            "-avoid_negative_ts", "make_zero",
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
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(teaser_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Fallback to ultrafast merge if copy concat fails
        fallback_command = [
            get_ffmpeg_path(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(teaser_path),
        ]
        fallback_result = subprocess.run(fallback_command, capture_output=True, text=True)
        if fallback_result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg merge failed:\n{fallback_result.stderr}"
            )

    return f"/clips/{video_id}/teaser.mp4"