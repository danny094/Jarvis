FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY cim_server.py /app/

# Environment
ENV CIM_ROOT=/app/intelligence_modules
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8086

# Run server
CMD ["python", "cim_server.py"]
