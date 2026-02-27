FROM python:3.12-slim

WORKDIR /app

# Copy requirements first (Docker layer caching)
COPY adapters/admin-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared code from project root
COPY core /app/core
COPY maintenance /app/maintenance
COPY utils /app/utils
COPY mcp /app/mcp
COPY config.py /app/config.py

# Copy lobechat adapter (needed for chat endpoint)
COPY adapters/lobechat /app/adapters/lobechat
COPY adapters/base.py /app/adapters/base.py
COPY adapters/__init__.py /app/adapters/__init__.py

# Copy application last
# Container Commander module
COPY container_commander /app/container_commander
COPY adapters/admin-api/*.py ./

RUN mkdir -p /app/data && chown 1000:1000 /app/data

EXPOSE 8200

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200", "--log-level", "info"]
