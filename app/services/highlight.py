from google.genai import types
import json
from app.clients.gemini import client

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

