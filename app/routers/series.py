from fastapi import APIRouter, Body, HTTPException  # <--- Added HTTPException
from typing import Dict, Any
from datetime import datetime
from firebase_admin import firestore
from app.core.database import db
from app.models.schemas import SeriesModel, EpisodeModel

router = APIRouter()

# --- SERIES ---

@router.post("/series")
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
    response_data = series_data.copy()
    response_data["created_at"] = datetime.now().isoformat()
    return {"status": "success", "id": doc_ref.id, "data": response_data}

@router.get("/series")
async def get_all_series():
    docs = db.collection("series").stream()
    # Handle older records that might not have created_at
    series_list = []
    for doc in docs:
        data = doc.to_dict()
        if "created_at" in data:
            data["created_at"] = str(data["created_at"])
        series_list.append(data)
    return {"series": series_list}

# --- [MISSING ENDPOINT ADDED HERE] ---
@router.get("/series/{series_id}")
async def get_single_series(series_id: str):
    doc = db.collection("series").document(series_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Series not found")
    return doc.to_dict()
# -------------------------------------


# --- EPISODES ---

@router.post("/series/{series_id}/episodes")
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
    response_data = episode_data.copy()
    response_data["created_at"] = datetime.now().isoformat()
    return {"status": "success", "id": ep_ref.id, "data": response_data}

@router.get("/series/{series_id}/episodes")
async def get_episodes(series_id: str):
    docs = db.collection("series").document(series_id).collection("episodes").stream()
    episodes = []
    for doc in docs:
        data = doc.to_dict()
        if "created_at" in data:
            data["created_at"] = str(data["created_at"])
        episodes.append(data)
    return {"episodes": episodes}

@router.delete("/series/{series_id}/episodes/{episode_id}")
async def delete_episode(series_id: str, episode_id: str):
    db.collection("series").document(series_id).collection("episodes").document(episode_id).delete()
    return {"status": "success", "message": f"Episode {episode_id} deleted"}

@router.delete("/series/{series_id}")
async def delete_series(series_id: str):
    db.collection("series").document(series_id).delete()
    return {"status": "success", "message": f"Series {series_id} deleted"}


# --- SCRIPTS ---

@router.post("/series/{series_id}/episodes/{episode_id}/script")
async def save_script(series_id: str, episode_id: str, payload: Dict[str, Any] = Body(...)):
    script_data = payload.get("data", [])
    batch = db.batch()
    for i, line in enumerate(script_data):
        doc_ref = db.collection("series").document(series_id)\
                    .collection("episodes").document(episode_id)\
                    .collection("script_lines").document(line["id"])
        batch.set(doc_ref, line)
        if (i + 1) % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    return {"status": "success", "count": len(script_data)}

@router.get("/series/{series_id}/episodes/{episode_id}/script")
async def get_script(series_id: str, episode_id: str):
    docs = db.collection("series").document(series_id)\
             .collection("episodes").document(episode_id)\
             .collection("script_lines").stream()
    script = [doc.to_dict() for doc in docs]
    script.sort(key=lambda x: x.get("panel_number", 0))
    return {"script": script}

@router.patch("/series/{series_id}/episodes/{episode_id}/script/{line_id}")
async def update_line(series_id: str, episode_id: str, line_id: str, payload: Dict[str, Any] = Body(...)):
    doc_ref = db.collection("series").document(series_id)\
                .collection("episodes").document(episode_id)\
                .collection("script_lines").document(line_id)
    doc_ref.update(payload)
    return {"status": "updated", "id": line_id}