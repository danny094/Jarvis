FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y     build-essential     iproute2     net-tools     && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir     fastmcp     requests     psycopg2-binary     docker     aiohttp

# Copy application code
COPY network_mcp ./network_mcp

# Create data directory
RUN mkdir -p /app/data

# Environment variables
ENV DB_PATH=/app/data/network.db
ENV COLLECTION_INTERVAL=30
ENV LOG_LEVEL=INFO

EXPOSE 8083

CMD ["python", "-m", "network_mcp.server"]
