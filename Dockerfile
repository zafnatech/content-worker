# Content worker: renders vertical videos (Pillow + numpy + ffmpeg). No browser needed (Chromium is only for connectors/capture.py).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Secrets (ELEVENLABS_*, CLOUDINARY_*, CONTENT_INGEST_*) come ONLY from the host's environment variables, never from git.
# Until worker.py exists (next step) the container just proves the renderer works:
CMD ["python3", "factory.py", "--help"]
