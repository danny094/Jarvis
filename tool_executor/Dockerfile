# Tool Executor - Layer 4 Runtime
# Strict Security Boundary

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install core dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash executor

WORKDIR /app

# Folders for mounting
RUN mkdir -p /skills /trion/plugins \
    && chown -R executor:executor /skills /trion/plugins

# Install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy Code
COPY . .

# Set ownership
RUN chown -R executor:executor /app

USER executor

ENV PYTHONUNBUFFERED=1
ENV SKILLS_DIR=/skills
ENV PLUGINS_DIR=/trion/plugins

EXPOSE 8000

# Strict entrypoint
CMD ["python3", "api.py"]
