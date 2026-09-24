"""NorthStar API entry point.

Creates the FastAPI app, wires CORS for the web frontend, and mounts routers. Keep this file
thin: feature logic belongs in routers and services, not here.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import comparison, dev, health, integrity, oversight, players, search

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
app.include_router(players.router)
app.include_router(search.router)
app.include_router(comparison.router)
app.include_router(oversight.router)
app.include_router(integrity.router)
# Development only, refused unless environment=development. Delete with the auth work.
app.include_router(dev.router)


@app.get("/")
def root() -> dict[str, str]:
    """Tiny landing payload so hitting the API root is not a 404."""
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}


# TODO: mount write endpoints as they land: POST /players, POST /players/{id}/measurements,
#   and the integrity board, which is blocked on a Flag table (see app/services/flags.py).
#   Authentication is not implemented; app/deps.py resolves a caller from a development
#   header and refuses outside environment=development.
