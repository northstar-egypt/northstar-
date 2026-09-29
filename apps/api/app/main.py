"""NorthStar API entry point.

Creates the FastAPI app, wires CORS for the web frontend, and mounts routers. Keep this file
thin: feature logic belongs in routers and services, not here.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import concepts
from app.config import get_settings
from app.routers import (
    auth,
    comparison,
    dev,
    health,
    integrity,
    oversight,
    players,
    search,
    sports,
)
from app.services import forecast

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The profile's height forecast takes seconds to build, and the search's embedding model
    # a second or two to load; start both now, in the background, so the first request does
    # not wait. See app/services/forecast.py and app/concepts.py.
    forecast.warm_up()
    concepts.warm_up()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(players.router)
app.include_router(search.router)
app.include_router(comparison.router)
app.include_router(oversight.router)
app.include_router(integrity.router)
app.include_router(sports.router)
# Development only, refused unless environment=development: the demo accounts the login
# screen offers. See app/routers/dev.py.
app.include_router(dev.router)


@app.get("/")
def root() -> dict[str, str]:
    """Tiny landing payload so hitting the API root is not a 404."""
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}

