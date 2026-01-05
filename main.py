import os
import pandas as pd
import json
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional # <--- ADDED Optional HERE
from openai import OpenAI
from io import BytesIO
from dotenv import load_dotenv
import requests
import firebase_admin
from firebase_admin import credentials, firestore

# 1. Setup Configuration
load_dotenv() 

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_credentials.json") 
    firebase_admin.initialize_app(cred)

db = firestore.client()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI Client
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# --- DIRECTORY SYSTEM PROMPT ---
DIRECTOR_SYSTEM_PROMPT = """
You are an expert Voice Director for an anime series.
Your goal is to assign a specific [Emotion Tag] to dialogue lines based on the physical action and audio context.

INPUT DATA:
- Action: Physical movement (e.g., "clenches fist", "looks away").
- SFX: Audio atmosphere (e.g., "HEARTBEAT", "EXPLOSION").
- Characters: Who is in the scene.
- Dialogue: The spoken line.

INSTRUCTIONS:
1. Analyze the 'Action' and 'SFX' to determine the intensity and mood.
2. Assign ONE emotion tag to the dialogue from this list (or similar):
   [Neutral], [Angry], [Shouting], [Whispering], [Sad], [Weeping], [Terrified], [Sarcastic], [Happy], [Surprised], [Strained], [Breathless].
3. Return the output as a JSON Object where the key is the 'id' of the line and the value is the emotion tag.

EXAMPLE INPUT:
ID: "1_0", Action: "Morgan stomps on the bag", Dialogue: "You're asking for it!"

EXAMPLE OUTPUT:
{
  "1_0": "[Aggressive]"
}
"""

# --- DATA MODELS ---

class ScriptLine(BaseModel):
    id: str
    panel_number: int
    dialogue: str
    action: str
    sfx: str
    characters: List[str]

class TagRequest(BaseModel):
    lines: List[ScriptLine]

class SeriesModel(BaseModel):     # <--- ADDED THIS
    title: str
    description: Optional[str] = ""

class EpisodeModel(BaseModel):
    title: str
    status: Optional[str] = "Draft"


# --- ENDPOINTS ---

@app.get("/")
def health_check():
    return {"status": "MotionX Director Backend is running"}

@app.post("/upload")
async def parse_excel(file: UploadFile = File(...)):
    logger.info(f"Received file: {file.filename}")
    try:
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))
        
        required_cols = ['panel_number', 'merged_dialogues', 'action_description', 'sfx_keywords', 'characters_included']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing columns: {missing}")

        script_data = []
        for idx, row in df.iterrows():
            try:
                dialogues = json.loads(row['merged_dialogues']) if pd.notna(row['merged_dialogues']) else []
                chars = json.loads(row['characters_included']) if pd.notna(row['characters_included']) else []
                action = str(row['action_description']) if pd.notna(row['action_description']) else ""
                sfx = str(row['sfx_keywords']) if pd.notna(row['sfx_keywords']) else ""
                
                for i, text in enumerate(dialogues):
                    script_data.append({
                        "id": f"{row['panel_number']}_{i}",
                        "panel_number": row['panel_number'],
                        "dialogue": text,
                        "action": action,
                        "sfx": sfx,
                        "characters": chars,
                        "suggested_emotion": ""
                    })
            except Exception as e:
                logger.error(f"Error parsing row {idx}: {e}")
                continue

        return {"filename": file.filename, "total_lines": len(script_data), "data": script_data}

    except Exception as e:
        logger.error(f"File processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze_emotions")
async def analyze_emotions_batch(payload: TagRequest):
    try:
        lines = payload.lines
        if not lines:
            return {}

        user_content = "Analyze these lines and provide the JSON mapping:\n\n"
        for line in lines:
            user_content += f"--- Line ID: {line.id} ---\n"
            user_content += f"Context: {line.action} | SFX: {line.sfx}\n"
            user_content += f"Characters Present: {', '.join(line.characters)}\n"
            user_content += f"Dialogue: \"{line.dialogue}\"\n\n"

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            response_format={ "type": "json_object" },
            temperature=0.7
        )
        return json.loads(response.choices[0].message.content)

    except Exception as e:
        logger.error(f"OpenAI Error: {e}")
        raise HTTPException(status_code=500, detail=f"OpenAI processing failed: {str(e)}")


# --- VOICE ENDPOINTS ---

@app.post("/sync_voices")
async def sync_voices_to_db():
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {
        "xi-api-key": os.getenv("ELEVENLABS_API_KEY"),
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

@app.get("/voices")
async def get_voices_from_db():
    voices_ref = db.collection("voices")
    docs = voices_ref.stream()
    voice_list = []
    for doc in docs:
        voice_list.append(doc.to_dict())
    voice_list.sort(key=lambda x: x['name'])
    return {"voices": voice_list}


# --- SERIES & EPISODE ENDPOINTS ---

# 1. CREATE SERIES
@app.post("/series")
async def create_series(series: SeriesModel):
    doc_ref = db.collection("series").document()
    series_data = {
        "id": doc_ref.id,
        "title": series.title,
        "description": series.description,
        "created_at": firestore.SERVER_TIMESTAMP,
        "character_map": {}
    }
    doc_ref.set(series_data)
    return {"status": "success", "id": doc_ref.id, "data": series_data}

# 2. GET ALL SERIES
@app.get("/series")
async def get_all_series():
    docs = db.collection("series").stream()
    series_list = []
    for doc in docs:
        data = doc.to_dict()
        if "created_at" in data:
            data["created_at"] = str(data["created_at"])
        series_list.append(data)
    return {"series": series_list}

# 3. GET SINGLE SERIES
@app.get("/series/{series_id}")
async def get_series_details(series_id: str):
    doc = db.collection("series").document(series_id).get()
    if not doc.exists:
        return {"error": "Series not found"}
    return doc.to_dict()

# 4. CREATE EPISODE
@app.post("/series/{series_id}/episodes")
async def create_episode(series_id: str, episode: EpisodeModel):
    ep_ref = db.collection("series").document(series_id).collection("episodes").document()
    episode_data = {
        "id": ep_ref.id,
        "title": episode.title,
        "status": episode.status,
        "created_at": firestore.SERVER_TIMESTAMP,
        "series_id": series_id
    }
    ep_ref.set(episode_data)
    return {"status": "success", "id": ep_ref.id, "data": episode_data}

# 5. LIST EPISODES
@app.get("/series/{series_id}/episodes")
async def get_episodes(series_id: str):
    docs = db.collection("series").document(series_id).collection("episodes").stream()
    episodes = []
    for doc in docs:
        data = doc.to_dict()
        if "created_at" in data:
            data["created_at"] = str(data["created_at"])
        episodes.append(data)
    return {"episodes": episodes}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)