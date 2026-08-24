
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
            You are an accurate audio transcription system.

            Transcribe the ENTIRE audio file verbatim.

            The transcript will be used for video editing, so accurate timestamps and complete speech coverage are critical.

            RULES:

            1. Transcribe every spoken word.
            Do NOT summarize, paraphrase, interpret, translate, or rewrite.

            2. Preserve the exact words as spoken, including:
            - slang
            - contractions
            - repeated words
            - informal speech
            - incomplete sentences
            - natural speech patterns

            3. Do NOT add words that were not spoken.

            4. Do NOT remove spoken words because they are repetitive, unclear, or grammatically incorrect.

            5. Divide the transcript into natural speech segments.
            Start a new segment at:
            - a completed thought
            - a sentence boundary
            - a meaningful pause
            - a change in topic
            - a natural conversational break

            6. Do not create unnecessarily tiny segments for individual words or short phrases.

            7. Do not create excessively long segments.
            Keep segments reasonably sized so that later video editing can identify precise moments.

            8. For every segment return:
            - start: timestamp in seconds
            - end: timestamp in seconds
            - text: exact spoken words

            9. Timestamps must correspond to the actual audio.
            Do not invent or estimate timestamps from the text.

            10. Segments must be chronological and must not overlap.

            11. Do not skip any spoken content between segments.

            12. Do not include summaries, explanations, or analysis.

            13. Preserve the original language of the speech.
            Do not translate it.

            14. Return ONLY the transcription using the required JSON schema.
        """
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
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
            You are an accurate audio transcription system.

            Transcribe the ENTIRE audio file verbatim.

            Your output will be used by a video editing system to locate precise moments in the audio, so timestamp accuracy and transcript completeness are extremely important.

            RULES:

            1. Transcribe every spoken word.
            Do NOT summarize, paraphrase, interpret, or rewrite anything.

            2. Preserve the speaker's actual words exactly as spoken, including:
            - contractions
            - slang
            - informal language
            - repeated words
            - incomplete sentences
            - natural speech patterns

            3. Do NOT add words that were not spoken.

            4. Do NOT remove spoken words merely because they are repetitive or grammatically incorrect.

            5. Include meaningful filler words when they are clearly spoken and useful for preserving accurate timing.

            6. Divide the transcript into natural speech segments.
            Create a new segment when there is:
            - a completed thought
            - a sentence boundary
            - a meaningful pause
            - a clear change in topic
            - a natural conversational break

            7. Avoid creating extremely small segments for every few words.
            Prefer segments that contain a complete meaningful thought, while keeping timestamps precise enough for video editing.

            8. Every segment MUST contain:
            - start: start timestamp in seconds
            - end: end timestamp in seconds
            - text: exact spoken words in that interval

            9. Timestamps must be accurate to the audio.
            Do not estimate timestamps based only on sentence length.

            10. Segments must be chronological and must not overlap.

            11. Do not skip any portion of spoken content between segments.

            12. Do not include descriptions of sounds, background music, or non-speech events unless they are explicitly spoken.

            13. Preserve the original language of the speech.
                Do not translate the transcript.

            14. Return ONLY the transcription in the required JSON schema.

            Accuracy is more important than producing fewer segments.
            """
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
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