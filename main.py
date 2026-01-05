import os
import pandas as pd
import json
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
from openai import OpenAI
from io import BytesIO
from dotenv import load_dotenv
import requests
import firebase_admin
from firebase_admin import credentials, firestore

# 1. Setup Configuration
load_dotenv() # Loads OPENAI_API_KEY from .env file

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firebase (Check ensures we don't init twice if auto-reload runs)
if not firebase_admin._apps:
    # Make sure this filename matches what you downloaded!
    cred = credentials.Certificate("firebase_credentials.json") 
    firebase_admin.initialize_app(cred)

# Get DB Reference
db = firestore.client()

app = FastAPI()

# Enable CORS (Allows your future React frontend to talk to this backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with ["http://localhost:5173"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI Client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logger.warning("OPENAI_API_KEY not found in .env file. Please set it.")

client = OpenAI(api_key=api_key)

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

# --- SYSTEM PROMPT ---
# This is the "Brain" of your Director
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

# --- ENDPOINTS ---

@app.get("/")
def health_check():
    return {"status": "MotionX Director Backend is running"}

@app.post("/upload")
async def parse_excel(file: UploadFile = File(...)):
    """
    Receives the 'Final Merged Excel'.
    Parses 'merged_dialogues', 'action_description', etc.
    Returns a structured JSON list for the Frontend.
    """
    logger.info(f"Received file: {file.filename}")
    
    try:
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))
        
        # Validate Columns
        required_cols = ['panel_number', 'merged_dialogues', 'action_description', 'sfx_keywords', 'characters_included']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing columns: {missing}. Please upload the file from Step 3.")

        script_data = []

        for idx, row in df.iterrows():
            try:
                # 1. Parse JSON strings back to Python objects
                # Using simple checks to handle potential empty/nan values safely
                dialogues = json.loads(row['merged_dialogues']) if pd.notna(row['merged_dialogues']) else []
                chars = json.loads(row['characters_included']) if pd.notna(row['characters_included']) else []
                
                # Handle SFX/Action (ensure they are strings)
                action = str(row['action_description']) if pd.notna(row['action_description']) else ""
                sfx = str(row['sfx_keywords']) if pd.notna(row['sfx_keywords']) else ""
                
                # 2. Flatten: One row per Dialogue Line
                # This makes it easier for the Frontend to display a list
                for i, text in enumerate(dialogues):
                    script_data.append({
                        "id": f"{row['panel_number']}_{i}",  # Unique ID: PanelNum_Index
                        "panel_number": row['panel_number'],
                        "dialogue": text,
                        "action": action,
                        "sfx": sfx,
                        "characters": chars, # List of who is in the scene
                        "suggested_emotion": "" # Placeholder for AI result
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
    """
    Receives a batch of lines (e.g., 10 lines).
    Sends them to OpenAI GPT-4o.
    Returns the ID -> Emotion mapping.
    """
    try:
        lines = payload.lines
        if not lines:
            return {}

        # 1. Construct the User Prompt for OpenAI
        # We format it as a clear list for the model to read
        user_content = "Analyze these lines and provide the JSON mapping:\n\n"
        
        for line in lines:
            user_content += f"--- Line ID: {line.id} ---\n"
            user_content += f"Context: {line.action} | SFX: {line.sfx}\n"
            user_content += f"Characters Present: {', '.join(line.characters)}\n"
            user_content += f"Dialogue: \"{line.dialogue}\"\n\n"

        logger.info(f"Sending {len(lines)} lines to OpenAI...")

        # 2. Call OpenAI
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            response_format={ "type": "json_object" }, # Crucial: Forces valid JSON back
            temperature=0.7
        )

        # 3. Extract Result
        ai_content = response.choices[0].message.content
        result_map = json.loads(ai_content)
        
        return result_map

    except Exception as e:
        logger.error(f"OpenAI Error: {e}")
        raise HTTPException(status_code=500, detail=f"OpenAI processing failed: {str(e)}")


# --- 1. ADMIN ROUTE: Syncs ElevenLabs -> Firebase ---
# Run this manually via Swagger UI (http://localhost:8000/docs) whenever you add a new voice.
@app.post("/sync_voices")
async def sync_voices_to_db():
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {
        "xi-api-key": os.getenv("ELEVENLABS_API_KEY"), # Make sure to add this to .env
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return {"error": "Failed to fetch from ElevenLabs", "details": response.text}
    
    data = response.json()
    voices = data.get('voices', [])
    
    # Save to Firestore 'voices' collection
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
    return {"status": "success", "count": len(voices), "message": "Firebase updated with latest ElevenLabs voices"}

# --- 2. PUBLIC ROUTE: Frontend -> Firebase ---
# This is what your React App will call on load. Fast & Free.
@app.get("/voices")
async def get_voices_from_db():
    voices_ref = db.collection("voices")
    docs = voices_ref.stream()
    
    voice_list = []
    for doc in docs:
        voice_list.append(doc.to_dict())
        
    # Sort them alphabetically by name for the dropdown
    voice_list.sort(key=lambda x: x['name'])
    
    return {"voices": voice_list}


# Run command (for testing inside this file, though usually run via terminal)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)