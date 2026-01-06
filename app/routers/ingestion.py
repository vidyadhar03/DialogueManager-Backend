import pandas as pd
import json
import logging
from io import BytesIO
from fastapi import APIRouter, UploadFile, File, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload")
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