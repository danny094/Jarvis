FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py /app/
COPY tools.py /app/
COPY processors/ /app/processors/
COPY chunkers/ /app/chunkers/

# Environment
ENV WORKSPACE_ROOT=/tmp/trion/jarvis/workspace
ENV PYTHONUNBUFFERED=1

# Create workspace directory
RUN mkdir -p /tmp/trion/jarvis/workspace

# Expose port
EXPOSE 8087

# Run server
CMD ["python", "server.py"]
