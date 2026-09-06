from datetime import datetime, timezone
from typing import Optional
from app.auth import db

user_teasers_collection = db["user_recent_teasers"]


async def init_user_teasers_db():
    try:
        # Create a unique index on user_id to strictly enforce one recent teaser per user
        await user_teasers_collection.create_index("user_id", unique=True)
    except Exception as e:
        print(f"Error creating unique index on user_id in user_recent_teasers: {e}")


async def save_last_generated_teaser(user_id: str, teaser_data: dict) -> dict:
    """
    Stores or replaces the user's most recently generated teaser in MongoDB.
    Enforces strictly ONE teaser per user by updating/upserting based on user_id.
    """
    doc = {
        "user_id": user_id,
        "video_id": teaser_data.get("video_id"),
        "filename": teaser_data.get("filename"),
        "teaser_url": teaser_data.get("teaser_url"),
        "clips": teaser_data.get("clips", []),
        "updated_at": datetime.now(timezone.utc),
    }

    await user_teasers_collection.update_one(
        {"user_id": user_id},
        {"$set": doc},
        upsert=True,
    )
    return doc


async def get_last_generated_teaser(user_id: str) -> Optional[dict]:
    """
    Retrieves the user's most recently generated teaser from MongoDB.
    """
    doc = await user_teasers_collection.find_one({"user_id": user_id})
    if not doc:
        return None

    # Exclude MongoDB internal _id field from API response
    doc.pop("_id", None)
    if "updated_at" in doc and isinstance(doc["updated_at"], datetime):
        doc["updated_at"] = doc["updated_at"].isoformat()

    return doc
