# Content worker: renders vertical videos (Pillow + numpy + ffmpeg). Chromium (Playwright) records public menu pages on a phone viewport (connectors/capture.py).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
COPY . .
# Secrets (ELEVENLABS_*, CLOUDINARY_*, CONTENT_INGEST_*) come ONLY from the host's environment variables, never from git.
# Hourly `auto` mode: renders queue/*.json jobs whose time window is open (cf/autoq.py); nothing due = exits in a second. Registered in the panel for approval, never published here.
# On Render: Cron Job with this image; the schedule lives in the dashboard.
CMD ["python3", "worker.py", "auto"]
