# NorthStar API image. Python 3.11 slim, pip + requirements.txt, uvicorn.
FROM python:3.11-slim

# Keep Python output unbuffered and skip .pyc files in the container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first so Docker caches this layer across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY . .

EXPOSE 8000

# --reload is convenient for local dev. Remove it (or override the command) for production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
