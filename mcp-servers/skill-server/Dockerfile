# Skill Server - TRION Extension Layer
# Base: Debian for stable apt-based dependency management

FROM debian:bookworm-slim

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -s /bin/bash skilluser

# Set up application directory
WORKDIR /app

# Create skills directory (will be mounted as volume)
RUN mkdir -p /skills /skills/_drafts /skills/_registry \
    && chown -R skilluser:skilluser /skills

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application code
COPY server.py .
COPY skill_manager.py .
COPY skill_cim_light.py .
COPY mini_control_layer.py .
COPY cim_rag.py .
COPY skill_memory.py .
COPY skill_knowledge.py .

# Copy CSV data for Skill-CIM-Light validation
COPY data/ ./data/

# Copy CIM-RAG knowledge base
COPY cim_data/ ./cim_data/

# Set ownership
RUN chown -R skilluser:skilluser /app

# Switch to non-root user
USER skilluser

# Environment
ENV PYTHONUNBUFFERED=1
ENV SKILLS_DIR=/skills
ENV REGISTRY_URL=https://raw.githubusercontent.com/trion-ai/skill-registry/main
ENV CIM_RAG_PATH=/app/cim_data

# Expose port
EXPOSE 8088

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8088/ || exit 1

# Run server
CMD ["python3", "server.py"]
