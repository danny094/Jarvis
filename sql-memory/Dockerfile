FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

RUN pip install fastmcp

COPY memory_mcp ./memory_mcp

RUN mkdir -p /app/data

ENV DB_PATH=/app/data/memory.db

EXPOSE 8081

CMD ["python", "-m", "memory_mcp.server"]
