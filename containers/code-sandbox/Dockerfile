# Code-Sandbox Container
# Sichere, isolierte Umgebung für Code-Ausführung
# Mit ttyd für Live-Terminal-Streaming

FROM python:3.11-slim

# System-Tools + ttyd
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    bash \
    curl \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/*

# ttyd installieren (Web-Terminal)
RUN wget -O /usr/local/bin/ttyd https://github.com/tsl0922/ttyd/releases/download/1.7.4/ttyd.x86_64 \
    && chmod +x /usr/local/bin/ttyd

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
    pandas \
    matplotlib

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

# ttyd Port
EXPOSE 7681

USER sandbox

# Default: Bash Shell (ttyd wird bei Bedarf separat gestartet)
CMD ["/bin/bash"]
