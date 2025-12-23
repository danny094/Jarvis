# Container-Manager Problem-Report

## 🔴 Kritische Probleme

### 1. Duplizierte `ResourceLimits` Klasse
**Dateien:** `security/limits.py` (Zeile 22) vs `containers/executor.py` (Zeile 98)

Beide Dateien definieren eine eigene `ResourceLimits` Klasse:
- `security/limits.py`: Vollständige Version mit `disk`, `to_docker_options()`, `get_tmpfs_config()`
- `containers/executor.py`: Einfachere Version ohne diese Features

**Problem:** Import-Konflikte, welche Version wird wo genutzt?

---

### 2. Duplizierter Docker-Client
**Dateien:** `containers/lifecycle.py` (Zeile 47-70) vs `utils/docker_client.py`

`lifecycle.py` hat eine eigene `get_docker_client()` Funktion statt `utils/docker_client.py` zu nutzen.

---

### 3. Security-Module werden NICHT genutzt
**Dateien:** `security/validator.py`, `security/limits.py`, `security/sandbox.py`

Die `main.py` und `containers/` Module nutzen **NICHT** die Security-Module:
- `executor.py` hat eigene `simple_validate()` Funktion statt `security/validator.py`
- `lifecycle.py` hat eigene `get_security_options()` statt `security/sandbox.py`
- `executor.py` hat eigene `ResourceLimits` statt `security/limits.py`

---

## 🟠 Mittlere Probleme

### 4. Duplizierte Logging-Funktionen (7x!)
Jedes Modul definiert eigene `log_info()`, `log_error()`, `log_warning()`:

| Datei | Zeile |
|-------|-------|
| `config.py` | 85-96 |
| `containers/lifecycle.py` | 29-36 |
| `containers/executor.py` | 25-32 |
| `containers/tracking.py` | 23-27 |
| `containers/registry.py` | 22-26 |

**Lösung:** `config.py` hat zentrale Logging → alle anderen sollten das importieren.

---

### 5. Duplizierte Konstanten
**REGISTRY_PATH / CONTAINERS_PATH:**
- `config.py` Zeile 15-16
- `containers/registry.py` Zeile 17-18

**DEFAULT_SESSION_TTL / MAX_SESSION_TTL:**
- `config.py` Zeile 29-30
- `containers/tracking.py` Zeile 18-19

**MAX_OUTPUT_LENGTH / MAX_CODE_LENGTH:**
- `config.py` Zeile 22-23
- `containers/executor.py` Zeile 19-20
- `security/validator.py` Zeile 14

---

### 6. Fehlende Exception-Handling
**`containers/tracking.py` Zeile 71-72:**
```python
last = datetime.fromisoformat(self.last_activity)
```
Kein try/except - kann crashen bei ungültigem Format.

---

### 7. Leere `except:` Blocks
**`containers/lifecycle.py`:**
- Zeile 262-263: `except: pass`
- Zeile 343-344: `except: pass`

**`containers/registry.py`:**
- Zeile 66-67: `except: pass`
- Zeile 78-79: `except: pass`

---

## 🟡 Geringe Probleme

### 8. Inkonsistente Docstrings
Manche Funktionen haben ausführliche Docstrings, andere gar keine.

### 9. Hardcoded Werte
- `lifecycle.py`: `TTYD_COMMAND = "ttyd -W -p 7681 bash"` → sollte aus `config.py`
- `executor.py`: `LANGUAGE_CONFIG` → `languages/config.py` existiert aber wird nicht genutzt

### 10. Thread-Safety Bedenken
`lifecycle.py` Zeile 43-44: Globale Variablen ohne Lock.

### 11. Fehlende Type Hints
Inkonsistent zwischen Modulen.

---

## 📋 Zusammenfassung

| Kategorie | Anzahl |
|-----------|--------|
| 🔴 Kritisch | 3 |
| 🟠 Mittel | 4 |
| 🟡 Gering | 4 |
| **Total** | **11** |

---

## ✅ Empfohlene Reihenfolge zur Behebung

1. **Security-Module integrieren** (Kritisch)
2. **Duplizierte Klassen entfernen** (Kritisch)
3. **Docker-Client vereinheitlichen** (Kritisch)
4. **Logging zentralisieren** (Mittel)
5. **Konstanten aus config.py importieren** (Mittel)
6. **Exception-Handling verbessern** (Mittel)
7. **Leere except-Blocks fixen** (Gering)
