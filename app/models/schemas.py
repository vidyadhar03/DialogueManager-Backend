from pydantic import BaseModel
from typing import List, Optional, Any

class ScriptLine(BaseModel):
    id: str
    panel_number: int
    dialogue: str
    action: str
    sfx: str
    characters: List[str]

class TagRequest(BaseModel):
    lines: List[ScriptLine]

class SeriesModel(BaseModel):
    title: str
    description: Optional[str] = ""

class EpisodeModel(BaseModel):
    title: str
    status: Optional[str] = "Draft"