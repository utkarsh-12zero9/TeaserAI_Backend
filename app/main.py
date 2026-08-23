from pathlib import Path
from uuid import uuid4
from fastapi.staticfiles import StaticFiles
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware

from app.services.clipping import create_clips, merge_clips
from app.services.highlight import find_highlights
from app.services.video import extract_audio
from app.services.transcription import (
    transcribe_audio,
)
from app.services.youtube import download_youtube_video


app = FastAPI(
    title="GenTe",
)

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


@app.post("/videos/upload")
async def upload_video(
    file: UploadFile = File(...),
    prompt: str = Form("Summarize the video in 3 sentences."),
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
):
    video_id = uuid4().hex
    print(f"[STAGE: YouTube Download] Started for URL: {youtube_url}")
    try:
        downloaded_file_path = download_youtube_video(youtube_url, UPLOAD_DIR, video_id)
        video_path = Path(downloaded_file_path)
        extension = video_path.suffix.lower()
        filename_to_return = f"youtube_{video_id}{extension}"
        print(f"[STAGE: YouTube Download] SUCCESS. Video saved to {video_path}")
    except Exception as e:
        print(f"[STAGE: YouTube Download] FAILURE: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to download YouTube video: {str(e)}"
        )

    return await process_video_pipeline(video_id, video_path, filename_to_return, prompt)


async def process_video_pipeline(video_id: str, video_path: Path, filename_to_return: str, prompt: str):
    # extract audio
    audio_filename = f"{video_id}.mp3"
    audio_path = AUDIO_DIR / audio_filename

    print("[STAGE: Audio Extraction] Started")
    try:
        extract_audio(
            str(video_path),
            str(audio_path),
        )
        print("[STAGE: Audio Extraction] SUCCESS")
    except Exception as e:
        print(f"[STAGE: Audio Extraction] FAILURE: {str(e)}")
        raise e

    # transcript
    print("[STAGE: Transcription] Started")
    try:
        transcript = transcribe_audio(
            str(audio_path)
        )
        print("[STAGE: Transcription] SUCCESS")
    except Exception as e:
        print(f"[STAGE: Transcription] FAILURE: {str(e)}")
        raise e

    # highlight
    print("[STAGE: Highlights Analysis] Started")
    try:
        highlights = find_highlights(
            transcript,
            prompt
        )
        print("[STAGE: Highlights Analysis] SUCCESS")
    except Exception as e:
        print(f"[STAGE: Highlights Analysis] FAILURE: {str(e)}")
        raise e

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