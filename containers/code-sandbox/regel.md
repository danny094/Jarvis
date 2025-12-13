# Container: code-sandbox

## ZWECK
Dieser Container ist ausschließlich für sichere Code-Tests und Analyse.
Er läuft OHNE Netzwerkzugriff in einer isolierten Umgebung.

---

## ✅ ERLAUBT

### Code-Ausführung
- Python-Scripts ausführen
- Node.js-Scripts ausführen
- Bash-Scripts ausführen
- Unit-Tests mit pytest
- TypeScript kompilieren

### Code-Analyse
- Syntax-Checks (pylint, eslint)
- Code formatieren (black, prettier)
- Type-Checking (mypy)
- Security-Scan (bandit)
- Dependency-Check (safety)

### Datei-Operationen
- Dateien in /workspace erstellen
- Dateien in /workspace lesen
- Dateien in /workspace bearbeiten
- Temporäre Dateien in /tmp

---

## ❌ VERBOTEN

### Netzwerk
- KEIN Internetzugriff (network_mode: none)
- KEINE API-Calls
- KEINE Downloads
- KEINE Package-Installation zur Laufzeit

### System
- KEIN Zugriff auf Host-Dateien
- KEIN Docker-Socket Zugriff
- KEINE Privilege Escalation
- KEINE System-Modifikationen

### Gefährliche Befehle
- rm -rf / (oder ähnliche)
- fork bombs
- Endlosschleifen ohne Timeout
- Crypto-Mining
- Malware-Ausführung

---

## ⚠️ LIMITS

| Resource | Limit |
|----------|-------|
| RAM | 512 MB |
| CPU | 1 Core |
| Laufzeit | 5 Minuten max |
| Disk | /workspace nur |

---

## 📦 VORINSTALLIERTE PACKAGES

### Python
- pytest, pylint, black, flake8
- mypy, bandit, safety
- ipython, numpy, pandas

### Node.js
- eslint, prettier, typescript

### System
- bash, curl, git

---

## 🔧 NUTZUNG

```bash
# Code testen
python /workspace/script.py

# Linting
pylint /workspace/script.py
eslint /workspace/script.js

# Formatieren
black /workspace/script.py
prettier --write /workspace/script.js

# Tests
pytest /workspace/tests/

# Security Check
bandit -r /workspace/
```

---

## 📝 BEISPIEL-WORKFLOW

1. User: "Kannst du diesen Code überprüfen?"
2. Code wird nach /workspace/code.py geschrieben
3. Container führt aus:
   - `python -m py_compile /workspace/code.py` (Syntax)
   - `pylint /workspace/code.py` (Style)
   - `bandit /workspace/code.py` (Security)
   - `python /workspace/code.py` (Ausführung)
4. Ergebnisse werden zurückgegeben
5. Container wird gestoppt und gelöscht
