# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Install ffmpeg + libmagic
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create temp dir
RUN mkdir -p /tmp/clips

# Expose port (Railway auto-sets $PORT)
EXPOSE 5000

# Run with gunicorn (production WSGI)
CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT:-5000} \
    --workers 2 \
    --threads 4 \
    --timeout 600 \
    --keep-alive 5 \
    --log-level info
