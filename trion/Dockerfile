FROM denoland/deno:2.1.4

# Install Python and UV (System Tier Tools)
RUN apt-get update && apt-get install -y python3 python3-pip python3-venv curl \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.cargo/bin/uv /usr/local/bin/uv
WORKDIR /app

# Copy dependency files first for caching
# Since we don't have a specific deps.ts or deno.json with dependencies clearly separated,
# and it's a small project, we copy everything.
# If there are specific config files, we could copy them first.
COPY . .

# Cache dependencies
RUN deno cache main.ts

# Permissions:
# --allow-net: for WebSocket server
# --allow-read: to read plugins/manifests
# --allow-write: to write plugin data/logs
# --allow-env: for environment variables (if any)
CMD ["run", "--allow-net", "--allow-read", "--allow-write", "--allow-env", "--allow-run", "main.ts"]
