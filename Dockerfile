# Content worker: renders vertical videos (Pillow + numpy + ffmpeg). No browser needed (Chromium is only for connectors/capture.py).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Secrets (ELEVENLABS_*, CLOUDINARY_*, CONTENT_INGEST_*) come ONLY from the host's environment variables, never from git.
# Daily mode v0: one menu video per client in WORKER_CLIENTS, registered in the panel for approval (never published here).
# On Render: Cron Job with this image; the schedule lives in the dashboard.
CMD ["python3", "worker.py", "run"]
