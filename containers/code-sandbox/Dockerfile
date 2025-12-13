# Code-Sandbox Container
# Sichere, isolierte Umgebung für Code-Ausführung

FROM python:3.11-slim

# System-Tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    bash \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python Packages für Code-Analyse
RUN pip install --no-cache-dir \
    pytest \
    pylint \
    black \
    flake8 \
    mypy \
    bandit \
    safety \
    ipython \
    numpy \
    pandas

# Node.js Tools
RUN npm install -g \
    eslint \
    prettier \
    typescript

# Arbeitsverzeichnis
WORKDIR /workspace

# Nicht-Root User für Sicherheit
RUN useradd -m -s /bin/bash sandbox
RUN chown -R sandbox:sandbox /workspace

# Regel-Datei kopieren (für Kontext)
COPY regel.md /app/regel.md

USER sandbox

# Default: Bash Shell
CMD ["/bin/bash"]
