#!/usr/bin/env bash
# Instalación única (Mac o Linux). Después: cp .env.example .env y llena los valores.
set -e
command -v ffmpeg >/dev/null || { echo "Falta ffmpeg (Mac: brew install ffmpeg)"; exit 1; }
python3 -m pip install --user pillow numpy playwright
python3 -m playwright install chromium
echo "Listo. Siguiente: cp .env.example .env  y llena los valores."
