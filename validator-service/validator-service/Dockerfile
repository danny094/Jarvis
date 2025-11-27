FROM python:3.11-slim

WORKDIR /app

# System-Abhängigkeiten minimal halten
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV OLLAMA_BASE_URL=http://ollama:11434
ENV EMBEDDING_MODEL=nomic-embed-text

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]