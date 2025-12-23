# Container Manager MCP Server
FROM python:3.11-slim

WORKDIR /app

# PYTHONPATH setzen für korrekte Imports
ENV PYTHONPATH=/app

# Docker CLI installieren (für docker commands falls nötig)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App Code
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8400/health || exit 1

EXPOSE 8400

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8400"]
