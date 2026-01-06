import requests
import logging
from io import BytesIO
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import StreamingResponse
from app.core.config import settings
from app.services.ai_service import analyze_lines
from app.models.schemas import TagRequest

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/analyze_emotions")
async def analyze_emotions_endpoint(payload: TagRequest):
    try:
        if not payload.lines:
            return {}
        return await analyze_lines(payload.lines)
    except Exception as e:
        logger.error(f"Analysis Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/generate_audio")
async def generate_audio(payload: dict = Body(...)):
    text = payload.get("text")
    voice_id = payload.get("voice_id")
    
    if not text or not voice_id:
        raise HTTPException(status_code=400, detail="Missing text or voice_id")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "model_id": "eleven_v3", 
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    
    try:
        # Added timeout=30 to prevent hanging
        response = requests.post(url, json=data, headers=headers, stream=True, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"ElevenLabs API Error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail=f"ElevenLabs Error: {response.text}")
            
        return StreamingResponse(BytesIO(response.content), media_type="audio/mpeg")

    except requests.exceptions.Timeout:
        logger.error("ElevenLabs Request Timed Out")
        raise HTTPException(status_code=504, detail="Connection to ElevenLabs timed out.")
    except Exception as e:
        logger.error(f"Generation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))