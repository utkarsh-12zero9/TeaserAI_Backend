from pathlib import Path
from uuid import uuid4
from fastapi.staticfiles import StaticFiles
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Form,
    Depends,
)
from fastapi.middleware.cors import CORSMiddleware

import os
from app.services.clipping import create_clips, merge_clips
from app.services.highlight import find_highlights, extract_highlights_from_audio
from app.services.video import extract_audio, get_audio_duration
from app.services.transcription import (
    transcribe_audio,
)
from app.services.youtube import download_youtube_video
from app.auth import router as auth_router, get_current_user


app = FastAPI(
    title="TeaserAI",
)

app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/clips",
    StaticFiles(directory="clips"),
    name="clips",
)

UPLOAD_DIR = Path("uploads")
AUDIO_DIR = Path("audio")


UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

AUDIO_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


@app.get("/health")
def health():
    return {
        "status": "ok"
    }



PIPELINE_STATUS = {}

@app.get("/videos/{video_id}/status")
async def get_pipeline_status(video_id: str):
    return PIPELINE_STATUS.get(video_id, {"step": "idle", "percent": 0})

@app.post("/videos/upload")
async def upload_video(
    file: UploadFile = File(...),
    prompt: str = Form("Summarize the video in 3 sentences."),
    video_id: str = Form(None),
    current_user: str = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is missing",
        )

    extension = Path(file.filename).suffix.lower()
    allowed_extensions = {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
    }

    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Unsupported video format",
        )

    if not video_id:
        video_id = uuid4().hex
    video_filename = f"{video_id}{extension}"
    video_path = UPLOAD_DIR / video_filename
    filename_to_return = file.filename

    print(f"[STAGE: File Upload] Started saving file: {filename_to_return}")
    try:
        with open(video_path, "wb") as output:
            while chunk := await file.read(1024 * 1024):
                output.write(chunk)
        print(f"[STAGE: File Upload] SUCCESS. Saved to {video_path}")
    except Exception as e:
        print(f"[STAGE: File Upload] FAILURE: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save uploaded file: {str(e)}"
        )

    return await process_video_pipeline(video_id, video_path, filename_to_return, prompt)


@app.post("/videos/youtube")
async def youtube_video(
    youtube_url: str = Form(...),
    prompt: str = Form("Summarize the video in 3 sentences."),
    video_id: str = Form(None),
    current_user: str = Depends(get_current_user),
):
    from app.services.youtube import download_youtube_audio_only, download_youtube_sections
    import time
    
    if not video_id:
        video_id = uuid4().hex
    t_start = time.perf_counter()
    print(f"[STAGE: YouTube Audio Ingestion] Started for URL: {youtube_url}")
    
    # 1. Download audio-only
    audio_filename = f"{video_id}.mp3"
    audio_path = AUDIO_DIR / audio_filename
    
    try:
        PIPELINE_STATUS[video_id] = {"step": "uploading", "percent": 30}
        download_youtube_audio_only(youtube_url, UPLOAD_DIR, video_id, AUDIO_DIR)
        PIPELINE_STATUS[video_id] = {"step": "extracting_audio", "percent": 100}
        print(f"[STAGE: YouTube Audio Ingestion] SUCCESS. Audio saved to {audio_path}")
    except Exception as e:
        print(f"[STAGE: YouTube Audio Ingestion] FAILURE: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to download YouTube audio: {str(e)}"
        )
        
    # 2. 1-pass direct audio highlight analysis
    PIPELINE_STATUS[video_id] = {"step": "analyzing_moments", "percent": 30}
    print("[STAGE: 1-Pass Direct Audio Highlight Extraction] Started")
    try:
        highlights = extract_highlights_from_audio(
            str(audio_path),
            prompt
        )
        PIPELINE_STATUS[video_id] = {"step": "analyzing_moments", "percent": 100}
        print("[STAGE: 1-Pass Direct Audio Highlight Extraction] SUCCESS")
    except Exception as e:
        PIPELINE_STATUS[video_id] = {"step": "speech_to_text", "percent": 45}
        print(f"[STAGE: 1-Pass Direct Audio Highlight Extraction] FAILURE: {str(e)}. Falling back to transcription pipeline...")
        try:
            transcript = transcribe_audio(str(audio_path))
            PIPELINE_STATUS[video_id] = {"step": "analyzing_moments", "percent": 70}
            highlights = find_highlights(transcript, prompt)
            PIPELINE_STATUS[video_id] = {"step": "analyzing_moments", "percent": 100}
        except Exception as fallback_err:
            PIPELINE_STATUS.pop(video_id, None)
            print(f"[STAGE: Fallback] FAILURE: {str(fallback_err)}")
            raise HTTPException(status_code=500, detail=str(fallback_err))

    print("Highlights found:", highlights)

    # 3. Download ONLY the required video sections corresponding to highlights in parallel
    PIPELINE_STATUS[video_id] = {"step": "clipping_teaser", "percent": 30}
    print("[STAGE: YouTube Section Download] Started")
    try:
        mapped_clips_data = download_youtube_sections(youtube_url, UPLOAD_DIR, video_id, highlights)
        PIPELINE_STATUS[video_id] = {"step": "clipping_teaser", "percent": 55}
        print("[STAGE: YouTube Section Download] SUCCESS")
        # Save a concatenated full MP4 video in uploads/ using stream copy (no re-encoding)
        try:
            section_paths = [c["local_path"] for c in mapped_clips_data if c.get("local_path") and os.path.exists(c["local_path"])]
            if section_paths:
                from app.services.youtube import get_ffmpeg_path
                ffmpeg_path = get_ffmpeg_path()
                upload_video_path = UPLOAD_DIR / f"{video_id}.mp4"
                if len(section_paths) == 1:
                    import shutil
                    shutil.copy2(section_paths[0], str(upload_video_path))
                else:
                    concat_list = UPLOAD_DIR / f"{video_id}_concat.txt"
                    with open(concat_list, "w") as cf:
                        for sp in section_paths:
                            print("file '" + sp.replace("\\", "\\\\") + "'", file=cf)
                    import subprocess
                    subprocess.run(
                        [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(upload_video_path)],
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    try:
                        os.remove(str(concat_list))
                    except Exception:
                        pass
                print(f"[STAGE: MP4 Save] Saved full video to {upload_video_path}")
        except Exception as mp4_err:
            print(f"[STAGE: MP4 Save] Non-critical failure (video still processes): {mp4_err}")
    except Exception as e:
        PIPELINE_STATUS.pop(video_id, None)
        print(f"[STAGE: YouTube Section Download] FAILURE: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to download video sections: {str(e)}"
        )

    # 4. Generate/prepare clips using downloaded sections
    PIPELINE_STATUS[video_id] = {"step": "clipping_teaser", "percent": 70}
    print("[STAGE: Video Clipping] Started")
    try:
        clips = create_clips(
            video_id,
            {"clips": mapped_clips_data}
        )
        PIPELINE_STATUS[video_id] = {"step": "clipping_teaser", "percent": 85}
        print("[STAGE: Video Clipping] SUCCESS")
    except Exception as e:
        PIPELINE_STATUS.pop(video_id, None)
        print(f"[STAGE: Video Clipping] FAILURE: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    # 5. Merge clips
    PIPELINE_STATUS[video_id] = {"step": "clipping_teaser", "percent": 90}
    print("[STAGE: Teaser Generation/Merge] Started")
    try:
        teaser_url = merge_clips(
            video_id,
            clips,
        )
        PIPELINE_STATUS[video_id] = {"step": "clipping_teaser", "percent": 100}
        print("[STAGE: Teaser Generation/Merge] SUCCESS")
    except Exception as e:
        PIPELINE_STATUS.pop(video_id, None)
        print(f"[STAGE: Teaser Generation/Merge] FAILURE: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    # Cleanup downloaded sections
    for clip in mapped_clips_data:
        lp = clip.get("local_path")
        if lp and os.path.exists(lp):
            try:
                os.remove(lp)
            except Exception:
                pass
                
    print(f"[PERF] YouTube flow completed in {time.perf_counter() - t_start:.2f}s")

    return {
        "video_id": video_id,
        "filename": f"youtube_{video_id}.mp4",
        "clips": clips,
        "teaser_url": teaser_url,
    }


async def process_video_pipeline(video_id: str, video_path: Path, filename_to_return: str, prompt: str):
    # extract audio
    audio_filename = f"{video_id}.mp3"
    audio_path = AUDIO_DIR / audio_filename

    print("[STAGE: Audio Extraction] Started")
    try:
        try:
            duration = get_audio_duration(str(video_path))
            bitrate = "16k" if duration > 1800 else "32k"
        except Exception:
            bitrate = "32k"
        extract_audio(
            str(video_path),
            str(audio_path),
            bitrate=bitrate
        )
        print("[STAGE: Audio Extraction] SUCCESS")
    except Exception as e:
        print(f"[STAGE: Audio Extraction] FAILURE: {str(e)}")
        raise e

    # 1-pass direct audio highlight analysis
    print("[STAGE: 1-Pass Direct Audio Highlight Extraction] Started")
    try:
        highlights = extract_highlights_from_audio(
            str(audio_path),
            prompt
        )
        print("[STAGE: 1-Pass Direct Audio Highlight Extraction] SUCCESS")
    except Exception as e:
        print(f"[STAGE: 1-Pass Direct Audio Highlight Extraction] FAILURE: {str(e)}. Falling back to transcription pipeline...")
        try:
            transcript = transcribe_audio(str(audio_path))
            highlights = find_highlights(transcript, prompt)
        except Exception as fallback_err:
            print(f"[STAGE: Fallback] FAILURE: {str(fallback_err)}")
            raise fallback_err

    print("Highlights found:", highlights)

    # clip
    print("[STAGE: Video Clipping] Started")
    try:
        clips = create_clips(
            str(video_path),
            highlights
        )
        print("[STAGE: Video Clipping] SUCCESS")
    except Exception as e:
        print(f"[STAGE: Video Clipping] FAILURE: {str(e)}")
        raise e

    # merge clips
    print("[STAGE: Teaser Generation/Merge] Started")
    try:
        teaser_url = merge_clips(
            video_id,
            clips,
        )
        print("[STAGE: Teaser Generation/Merge] SUCCESS")
    except Exception as e:
        print(f"[STAGE: Teaser Generation/Merge] FAILURE: {str(e)}")
        raise e

    return {
        "video_id": video_id,
        "filename": filename_to_return,
        "clips": clips,
        "teaser_url": teaser_url,
    }