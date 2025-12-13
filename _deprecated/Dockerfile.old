FROM python:3.11

# ---------------------------------------------------------
# System-Packages
# ---------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# Arbeitsverzeichnis
# ---------------------------------------------------------
WORKDIR /app

# ---------------------------------------------------------
# Dependencies
# ---------------------------------------------------------
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------
# App Dateien kopieren
# (Wir kopieren ALLES, weil wir jetzt Module haben)
# ---------------------------------------------------------
COPY . .

# ---------------------------------------------------------
# Uvicorn Start
# ---------------------------------------------------------
EXPOSE 8000

CMD ["python", "main.py"]