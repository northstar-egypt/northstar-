# NorthStar API image. Python 3.11 slim, pip + requirements.txt, uvicorn.
#
# Built from the repository root (see docker/docker-compose.yml), not from apps/api, because
# the API reads the sport modules in packages/shared/sports, and runs the graded height
# forecaster in ml/forecasting for the player profile (app/services/forecast.py). Both are
# shared with the generator and the ML evaluation, so the image uses the same files.
FROM python:3.11-slim

# Keep Python output unbuffered and skip .pyc files in the container.
ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     SPORT_MODULES_DIR=/shared/sports     PYTHONPATH=/opt/northstar

WORKDIR /app

# Install dependencies first so Docker caches this layer across code changes.
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The sport modules, the ML package (for the profile's height forecast, XGBoost; its
# dependency is in requirements.txt above), then the application code.
COPY packages/shared/sports /shared/sports
COPY ml /opt/northstar/ml
COPY apps/api .

EXPOSE 8000

# --reload is convenient for local dev. Remove it (or override the command) for production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
