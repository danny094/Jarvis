# adapters/lobechat/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# System-Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Requirements kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Gesamtes Projekt kopieren
COPY . .

# PYTHONPATH setzen damit alle Imports funktionieren
ENV PYTHONPATH=/app

# Port
EXPOSE 8100

# Start vom Projekt-Root aus
CMD ["python", "-m", "adapters.lobechat.main", "--host", "0.0.0.0", "--port", "8100"]
