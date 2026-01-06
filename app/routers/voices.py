import requests
from fastapi import APIRouter
from app.core.database import db
from app.core.config import settings

router = APIRouter()

@router.post("/sync_voices")
async def sync_voices_to_db():
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return {"error": "Failed to fetch from ElevenLabs", "details": response.text}
    
    data = response.json()
    voices = data.get('voices', [])
    
    batch = db.batch()
    for voice in voices:
        doc_ref = db.collection("voices").document(voice["voice_id"])
        batch.set(doc_ref, {
            "name": voice["name"],
            "voice_id": voice["voice_id"],
            "category": voice.get("category", "generated"),
            "preview_url": voice.get("preview_url", "")
        })
    
    batch.commit()
    return {"status": "success", "count": len(voices), "message": "Firebase updated"}

@router.get("/voices")
async def get_voices_from_db():
    voices_ref = db.collection("voices")
    docs = voices_ref.stream()
    voice_list = []
    for doc in docs:
        voice_list.append(doc.to_dict())
    voice_list.sort(key=lambda x: x['name'])
    return {"voices": voice_list}