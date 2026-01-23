FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastmcp httpx

# Copy application
COPY sequential_thinking.py /app/

# Environment
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8085

# Run server
CMD ["python", "sequential_thinking.py"]
