from google.genai import types
import json
from app.clients.gemini import client

def extract_highlights_from_audio(audio_path: str, user_prompt: str):
    """
    Directly extracts highlight clips from an audio file in a single 1-pass LLM call.
    Uses inline bytes for files under 15MB to avoid Google Files API processing delays.
    """
    import os
    from app.services.video import get_audio_duration
    try:
        duration = get_audio_duration(audio_path)
    except Exception:
        duration = 0.0

    prompt = f"""
    You are an AI video editor.
    Listen to the audio content in this file. The total duration of this audio file is {duration:.1f} seconds.

    User's requirement:
    {user_prompt}

    Your task:
    1. Listen to the entire audio content (total length: {duration:.1f} seconds).
    2. Identify the 3 to 5 most engaging, insightful, or interesting moments.
    3. Select complete, meaningful timestamp intervals (start and end in seconds).
    4. Each selected section must make sense when watched as a standalone video clip.
    5. Each highlight clip MUST have a duration of 30 to 60 seconds (duration = end - start). Do NOT select clips shorter than 15 seconds. For long videos, select longer clips (e.g. 45 to 60 seconds).
    6. Return the exact start and end timestamps in seconds. Timestamps MUST be absolute seconds from the start of the audio (ranging from 0.0 to {duration:.1f}). Do NOT use minutes or other units.
    7. Return a short text summary/reason for why each clip was selected.
    """

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024) if os.path.exists(audio_path) else 0

    if file_size_mb < 15.0:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        audio_content = types.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3")
        
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[prompt, audio_content],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "clips": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "start": {"type": "number"},
                                    "end": {"type": "number"},
                                    "text": {"type": "string"}
                                },
                                "required": ["start", "end", "text"]
                            }
                        }
                    },
                    "required": ["clips"]
                }
            )
        )
    else:
        import time
        print("[STAGE: Gemini Upload] Uploading large audio file...")
        audio_file = client.files.upload(file=audio_path)
        print(f"[STAGE: Gemini Upload] File uploaded. Polling processing state (Current state: {audio_file.state})...")
        while audio_file.state.name == "PROCESSING":
            time.sleep(1.0)
            audio_file = client.files.get(name=audio_file.name)
        if audio_file.state.name == "FAILED":
            raise RuntimeError("Gemini File API processing failed.")
        print(f"[STAGE: Gemini Upload] File is now {audio_file.state.name}. Sending generate_content request...")
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, audio_file],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "clips": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "start": {"type": "number"},
                                        "end": {"type": "number"},
                                        "text": {"type": "string"}
                                    },
                                    "required": ["start", "end", "text"]
                                }
                            }
                        },
                        "required": ["clips"]
                    }
                )
            )
        finally:
            try:
                client.files.delete(name=audio_file.name)
            except Exception:
                pass

    try:
        response_text = response.text
        if not response_text:
            raise ValueError("Empty or blocked response text")
        highlights = json.loads(response_text)
    except Exception as error:
        raise RuntimeError(
            f"Gemini failed to return valid highlight selection from audio: {str(error)}"
        ) from error

    return highlights


def find_highlights(transcript : dict, user_prompt : str):

    transcript_text = json.dumps(
        transcript,
        indent=2
    )
    
    prompt = f"""
        You are an AI video editor.

        The user wants to create short video teasers from the transcript.

        User's requirements:
        {user_prompt}

        Here is the timestamped transcript:
        {transcript_text}

        Your task:

        1. Analyze the transcript.
        2. Find the most interesting and engaging moments.
        3. Follow the user's requirements when selecting the moments.
        4. Select complete, meaningful sections rather than isolated sentences.
        5. The selected section must make sense when watched as a standalone video clip.
        6. Prefer strong hooks, surprising information, useful insights,
        emotional moments, curiosity, humor, or memorable statements.
        7. Avoid sections that require too much context from earlier parts.
        8. Do not modify or rewrite the spoken text.
        9. Use the timestamps from the transcript.
        10. Return the start and end timestamps of each selected clip.
        11. Return a short reason explaining why each clip was selected.

        Do NOT transcribe anything.
        Do NOT create new timestamps.
        Use only timestamps that exist in the provided transcript.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            prompt
        ],
        config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "clips": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {
                                "type": "number"
                            },
                            "end": {
                                "type": "number"
                            },
                            "text": {
                                "type": "string"
                            }
                        },
                        "required": [
                            "start",
                            "end",
                            "text"
                        ]
                    }
                }
            },
            "required": [
                "clips"
            ]
        }
    )
    )

    try:
        response_text = response.text
        if not response_text:
            raise ValueError("Empty or blocked response text")
        highlights = json.loads(response_text)
    except Exception as error:
        # Diagnostic logging
        print("[DIAGNOSTIC] Highlight analysis failed to return valid text.")
        candidate = response.candidates[0] if response.candidates else None
        if candidate:
            print(f"[DIAGNOSTIC] Candidate Finish Reason: {candidate.finish_reason}")
            print(f"[DIAGNOSTIC] Safety Ratings: {candidate.safety_ratings}")
        else:
            print("[DIAGNOSTIC] No response candidates were returned by the model.")
        print(f"[DIAGNOSTIC] Raw Response Structure: {response}")
        
        # Raise descriptive error
        if candidate and str(candidate.finish_reason) == "SAFETY":
            raise RuntimeError(
                "Gemini blocked the highlight selection because the transcript triggered safety filters."
            ) from error
        elif candidate and str(candidate.finish_reason) == "RECITATION":
            raise RuntimeError(
                "Gemini blocked the highlight selection because the transcript triggered copyright/recitation filters."
            ) from error
        raise RuntimeError(
            f"Gemini failed to return valid highlight selection: {str(error)}"
        ) from error

    return highlights

