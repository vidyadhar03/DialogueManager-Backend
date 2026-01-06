import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 1. Ensure all routers are imported
from app.routers import series, voices, generation, ingestion 

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MotionX Director Backend")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health Check
@app.get("/")
def health_check():
    return {"status": "MotionX Director Backend is running"}

# 2. Register Routers (UNCOMMENT THESE LINES)
app.include_router(ingestion.router, tags=["Ingestion"])
app.include_router(series.router, tags=["Series & Scripts"])
app.include_router(voices.router, tags=["Voices"])         # <--- UNCOMMENT THIS
app.include_router(generation.router, tags=["AI Generation"]) # <--- UNCOMMENT THIS

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)