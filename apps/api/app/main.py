"""NorthStar API entry point.

Creates the FastAPI app, wires CORS for the web frontend, and mounts routers. Keep this file
thin: feature logic belongs in routers and services, not here.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import health

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)


@app.get("/")
def root() -> dict[str, str]:
    """Tiny landing payload so hitting the API root is not a 404."""
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}


# TODO: mount feature routers here as workstreams add them
#   (players, search, ingestion, auth, ...).
