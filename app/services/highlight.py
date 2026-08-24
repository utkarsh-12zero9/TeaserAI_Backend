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
        You are an expert short-form video editor.

        Listen to the ENTIRE audio and identify the strongest moments that could be used as teaser clips.

        AUDIO DURATION:
        {duration:.1f} seconds

        USER REQUIREMENTS:
        {user_prompt}

        The goal is NOT to summarize the audio.

        Find moments that would make someone want to watch the full video.

        Prioritize:
        - strong hooks
        - surprising statements
        - emotional moments
        - humor or punchlines
        - controversial or bold opinions
        - important revelations
        - memorable statements
        - curiosity
        - unexpected information
        - high-energy moments

        RULES:

        1. Select 4–7 strong moments when the content supports it.
        Do not force the number if there are fewer genuinely strong moments.

        2. Keep clips SHORT and impactful.
        Prefer approximately 2–10 seconds per clip.
        Use a longer clip only when necessary to preserve the meaning of the moment.

        3. Select the MINIMUM amount of speech necessary to deliver the impact.
        Do not select long continuous sections just because they contain interesting information.

        4. A clip should contain a meaningful thought, but it does NOT need to explain everything.
        Leaving some information unanswered is desirable.

        5. Avoid:
        - introductions
        - greetings
        - filler
        - slow explanations
        - repetitive statements
        - generic information
        - unnecessary context
        - moments that completely reveal the story

        6. Start and end clips at natural speech boundaries.
        Never cut in the middle of a word, phrase, or meaningful thought.

        7. Use ABSOLUTE timestamps in seconds from the beginning of the audio.

        8. Timestamps must be between 0.0 and {duration:.1f}.

        9. The selected moments do NOT have to be chronological.
        Arrange them in the strongest teaser order.

        10. The first selected moment should be the strongest hook.
            The final moment should preferably create curiosity, suspense, or an open loop.

        11. Follow the user's requirements above all default rules.

        Before returning the result, mentally review the selected moments as a teaser.
        Remove weak, repetitive, or unnecessarily long clips.

        RETURN ONLY VALID JSON:

        {{
        "clips": [
            {{
            "start": 12.4,
            "end": 17.8,
            "role": "hook"
            }}
        ]
        }}

        Allowed roles:
        "hook", "context", "escalation", "revelation", "emotional_peak", "punchline", "open_loop"

        Do not return explanations, summaries, or transcript text.
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
                model="gemini-3.6-flash",
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
        You are an expert short-form video editor.

        Your task is to select and ORDER the best moments from this long-form video to create a highly engaging teaser.

        USER REQUIREMENTS:
        {user_prompt}

        TIMESTAMPED TRANSCRIPT:
        {transcript_text}

        IMPORTANT:
        The teaser is NOT a summary of the video.
        It is an advertisement for the video.

        Optimize for:
        - immediate attention
        - curiosity
        - emotional impact
        - surprise
        - humor
        - tension
        - strong opinions
        - memorable statements
        - unanswered questions
        - viewer retention

        FIRST, analyze the ENTIRE transcript before selecting clips.

        Then create the strongest possible teaser sequence.

        RULES:

        1. Select 4-8 distinct clips from different parts of the video when possible.

        2. DO NOT select long continuous sections.
        Most clips should be approximately 3–12 seconds.
        Use longer clips only when necessary to preserve meaning.

        3. Select the MINIMUM amount of speech necessary to deliver the impact.
        Never extend a clip just to reach a duration target.

        4. Prefer:
        - shocking statements
        - intriguing questions
        - unexpected revelations
        - emotional reactions
        - funny/punchy moments
        - controversial opinions
        - strong conclusions
        - statements that create curiosity

        5. Avoid:
        - slow explanations
        - repetitive information
        - introductions
        - greetings
        - filler
        - excessive context
        - generic statements
        - clips that completely reveal the story

        6. A clip should communicate a meaningful thought, but it does NOT need to explain everything.
        Creating an information gap is desirable.

        7. Think like a trailer editor:
        
        HOOK → CURIOSITY → ESCALATION → PEAK → OPEN LOOP

        However, choose the structure that best fits the actual video.
        Do NOT force this structure if another sequence is stronger.

        8. The clips do NOT have to be in chronological order.
        Arrange them in the order that creates the strongest teaser.

        9. The FIRST clip must immediately capture attention.

        10. The FINAL clip should preferably leave an unanswered question,
            reveal something intriguing, or end on a memorable/punchy statement.
            Do NOT unnecessarily resolve the entire story.

        11. Avoid selecting multiple clips that communicate the same idea.

        12. Start and end clips at natural speech boundaries.
            NEVER cut:
            - in the middle of a word
            - in the middle of a meaningful phrase
            - before a thought is complete

        13. Use ONLY timestamps that exist in the transcript.
            NEVER invent timestamps.

        14. Do NOT rewrite or modify spoken words.

        Before returning the answer, mentally watch the selected clips in the exact order.
        Remove any clip that makes the teaser slower, repetitive, confusing, or less interesting.
        If a clip can be shortened without losing its impact, shorten it.

        RETURN ONLY JSON:

        {{
        "clips": [
            {{
            "start": 12.4,
            "end": 17.8,
            "role": "hook",
            "reason": "Creates immediate curiosity through a surprising statement."
            }}
        ]
        }}

        Do not return the transcript.
        Do not return analysis.
        Do not return additional text.
    """

    response = client.models.generate_content(
        model="gemini-3.6-flash",
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

