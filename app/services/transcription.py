
import concurrent.futures
import os
from pydantic import BaseModel
from google.genai import types
import json
from app.clients.gemini import client
from fastapi import HTTPException
from app.services.video import split_audio_into_chunks


class SegmentSchema(BaseModel):
    start: float
    end: float
    text: str


class TranscriptSchema(BaseModel):
    segments: list[SegmentSchema]


def transcribe_audio(audio_path: str):
    # For compressed audio (16kHz 32kbps mono), a 1-hour file is only ~14MB.
    # If the audio file is under 25MB, transcribe it directly in one call to avoid multi-chunk delay.
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024) if os.path.exists(audio_path) else 0

    def transcribe_single_file(path: str) -> list[dict]:
        import time
        print("[STAGE: Fallback Ingestion] Uploading audio for transcription...")
        audio_file = client.files.upload(file=path)
        while audio_file.state.name == "PROCESSING":
            time.sleep(1.0)
            audio_file = client.files.get(name=audio_file.name)
        if audio_file.state.name == "FAILED":
            raise RuntimeError("Gemini File API processing failed.")
        print("[STAGE: Fallback Ingestion] Audio is active. Starting transcription...")
        prompt = """
        Transcribe the entire audio file.
        Create a segment whenever there is a natural change in speech.
        For every segment:
        - start = timestamp in seconds
        - end = timestamp in seconds
        - text = exact spoken words
        Avoid using double quotes inside the text field; use single quotes instead to keep JSON clean.
        Do not summarize.
        Do not skip spoken words.
        """
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, audio_file],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=8192,
                    response_schema=TranscriptSchema
                )
            )
        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower() or "limit" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                raise HTTPException(
                    status_code=429,
                    detail="Google Gemini API quota exceeded. Please link a billing account or wait for quota reset."
                ) from e
            raise e
        finally:
            try:
                client.files.delete(name=audio_file.name)
            except Exception:
                pass

        processed_segments = []
        if response.parsed and response.parsed.segments:
            for segment in response.parsed.segments:
                processed_segments.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text
                })
        return processed_segments

    if file_size_mb < 25.0:
        segments = transcribe_single_file(audio_path)
        return {"segments": segments}

    # Fallback to chunking for extremely large files (>25MB)
    chunks = split_audio_into_chunks(audio_path, chunk_duration_sec=300.0, overlap_sec=10.0)
    if not chunks:
        return {"segments": []}

    def transcribe_chunk(chunk: dict) -> list[dict]:
        import time
        audio_file = client.files.upload(file=chunk["path"])
        while audio_file.state.name == "PROCESSING":
            time.sleep(1.0)
            audio_file = client.files.get(name=audio_file.name)
        if audio_file.state.name == "FAILED":
            raise RuntimeError("Gemini File API processing failed.")
        prompt = """
        Transcribe the entire audio file.
        Create a segment whenever there is a natural change in speech.
        For every segment:
        - start = timestamp in seconds
        - end = timestamp in seconds
        - text = exact spoken words
        Avoid using double quotes inside the text field; use single quotes instead to keep JSON clean.
        Do not summarize.
        Do not skip spoken words.
        """
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, audio_file],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=8192,
                    response_schema=TranscriptSchema
                )
            )
        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower() or "limit" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                raise HTTPException(
                    status_code=429,
                    detail="Google Gemini API quota exceeded."
                ) from e
            raise e
        finally:
            try:
                client.files.delete(name=audio_file.name)
            except Exception:
                pass

        processed_segments = []
        chunk_start = chunk["start"]
        chunk_end = chunk["end"]
        if response.parsed and response.parsed.segments:
            for segment in response.parsed.segments:
                global_start = segment.start + chunk_start
                global_end = segment.end + chunk_start
                if chunk_start <= global_start < chunk_end:
                    processed_segments.append({
                        "start": round(global_start, 2),
                        "end": round(global_end, 2),
                        "text": segment.text
                    })
        return processed_segments

    import time
    all_segments = []
    try:
        for idx, chunk in enumerate(chunks):
            if idx > 0:
                time.sleep(12.0)
            try:
                chunk_segments = transcribe_chunk(chunk)
                all_segments.extend(chunk_segments)
            except Exception as exc:
                raise RuntimeError(f"Transcription failed for chunk starting at {chunk['start']}s: {exc}") from exc
    finally:
        for chunk in chunks:
            try:
                if os.path.exists(chunk["path"]):
                    os.remove(chunk["path"])
            except Exception:
                pass

    all_segments.sort(key=lambda s: s["start"])
    return {"segments": all_segments}


