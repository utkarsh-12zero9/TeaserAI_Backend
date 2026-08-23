
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
    # Split audio into 5-minute chunks with a 10-second overlap
    chunks = split_audio_into_chunks(audio_path, chunk_duration_sec=300.0, overlap_sec=10.0)
    
    if not chunks:
        return {"segments": []}

    def transcribe_chunk(chunk: dict) -> list[dict]:
        # Upload chunk file
        audio_file = client.files.upload(
            file=chunk["path"]
        )

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
                model="gemini-3.5-flash",
                contents=[
                    prompt,
                    audio_file
                ],
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
                    detail="Google Gemini API quota exceeded (Resource Exhausted). Your API key has hit the free tier limit (20 requests per day). Please link a billing account in Google AI Studio to upgrade, wait for the quota window to reset, or use a different API key."
                ) from e
            elif "billing" in error_msg.lower() or "402" in error_msg.lower():
                raise HTTPException(
                    status_code=402,
                    detail="Google Gemini API billing issue (402 Payment Required). Please verify your Google Cloud / AI Studio billing account status or API key permissions."
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

                # Keep segment if it starts within this chunk's responsibility window
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
            # Delay 12 seconds between chunk requests (except the first) to stay under 5 requests/minute
            if idx > 0:
                time.sleep(12.0)
            
            try:
                chunk_segments = transcribe_chunk(chunk)
                all_segments.extend(chunk_segments)
            except Exception as exc:
                raise RuntimeError(f"Transcription failed for chunk starting at {chunk['start']}s: {exc}") from exc
    finally:
        # Clean up local chunk files
        for chunk in chunks:
            try:
                if os.path.exists(chunk["path"]):
                    os.remove(chunk["path"])
            except Exception:
                pass

    all_segments.sort(key=lambda s: s["start"])
    return {"segments": all_segments}


