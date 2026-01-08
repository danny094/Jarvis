# 📁 Personas Directory

This directory stores all persona configuration files for the Jarvis AI system.

## 📋 What are Personas?

Personas define how Jarvis behaves, communicates, and responds to you. Each persona is a simple text file that controls:
- **Tone & Style** (formal, casual, technical, creative)
- **Personality Traits** (helpful, direct, humorous)
- **Language** (deutsch, english, mixed)
- **Core Rules** (privacy, response length, memory usage)

## 📄 File Format: `.txt`

Each persona is a plain text file with section-based structure:

```txt
# Persona: [NAME]
# Description: [OPTIONAL]
# Version: 1.0

[IDENTITY]
name: Jarvis
role: Personal Assistant
language: deutsch
user_name: Danny

[PERSONALITY]
- freundlich
- hilfsbereit
- technisch versiert
- ein bisschen Humor

[STYLE]
tone: locker aber respektvoll
verbosity: mittel
response_length: angepasst an Frage

[RULES]
1. Keine persönlichen Daten erfinden
2. Ehrlich bei Unwissenheit
3. Memory nutzen für persönliche Fragen
4. Kurze Fragen = kurze Antworten
5. Nachfragen statt raten

[PRIVACY]
- Keine sensiblen Daten in Beispielen
- Nur Danny's Daten verwenden
- Keine Passwörter speichern
```

## 🔒 Protected Files

**`default.txt`**
- Base persona (cannot be deleted)
- Fallback if custom personas fail
- Safe starting point

## 📦 Custom Personas

You can create custom personas in two ways:

### 1. Manual Creation
```bash
# Create new file
sudo nano /DATA/AppData/MCP/Jarvis/Jarvis/personas/my_persona.txt

# Copy structure from default.txt
# Modify as needed
# Save & switch via WebUI
```

### 2. WebUI Upload
- Go to WebUI → Settings → Persona Management
- Click "Upload Persona"
- Select your `.txt` file
- Persona is immediately available

## 🎯 Example Use Cases

### Developer Mode (`dev_mode.txt`)
```txt
[PERSONALITY]
- technisch präzise
- code-fokussiert
- minimal Smalltalk

[STYLE]
tone: direkt
verbosity: kurz

[RULES]
1. Bevorzuge Code-Beispiele
2. Technische Details wichtiger als Erklärungen
3. Keine Emoji (außer in Code-Kommentaren)
```

### Creative Mode (`creative.txt`)
```txt
[PERSONALITY]
- kreativ
- verspielt
- metaphorisch

[STYLE]
tone: enthusiastisch
verbosity: ausführlich

[RULES]
1. Nutze Analogien und Metaphern
2. Ermutige Brainstorming
3. Emoji erlaubt 🎨
```

### Security Audit (`security.txt`)
```txt
[PERSONALITY]
- kritisch
- vorsichtig
- detailorientiert

[STYLE]
tone: neutral
verbosity: sehr detailliert

[RULES]
1. Alle Annahmen hinterfragen
2. Security-Best-Practices erwähnen
3. Potenzielle Risiken aufzeigen
```

## 🔄 Switching Personas

### Via WebUI (Recommended)
1. Open Persona dropdown (top bar)
2. Select desired persona
3. Confirmation message appears
4. New persona active immediately (hot-reload)

### Via API
```bash
curl -X PUT "http://localhost:8400/api/personas/switch?name=dev_mode"
```

## 📏 File Limits

- **Max size:** 10 KB per file
- **Format:** Plain text (.txt)
- **Encoding:** UTF-8
- **Line endings:** Unix (LF) or Windows (CRLF) both supported

## ⚠️ Common Mistakes

**❌ Don't:**
- Use complex YAML syntax (keep it simple)
- Store sensitive data (passwords, API keys)
- Make personas too long (>200 lines)
- Use special characters in filenames

**✅ Do:**
- Test personas before deploying
- Keep sections organized
- Document what makes this persona unique
- Use descriptive filenames (`security_audit.txt` not `p1.txt`)

## 🛠️ Troubleshooting

**Persona doesn't load:**
- Check file syntax (sections in [BRACKETS])
- Verify UTF-8 encoding
- Look for typos in section names
- Check file permissions (should be readable)

**Switch doesn't work:**
- Reload page after switch
- Check browser console for errors
- Verify persona file exists
- Try switching to `default` first

**Upload fails:**
- File size < 10KB?
- Correct `.txt` extension?
- Valid persona format?
- Write permissions on `/personas/` directory?

## 📚 Advanced Topics

### Persona Inheritance (Future)
Planned feature: Personas can extend `default.txt`
```txt
[EXTENDS]
base: default

[OVERRIDE]
tone: technical
```

### Metadata (Future)
```txt
[META]
author: Danny
version: 1.2
tags: development, code
scope: all_layers
```

## 🆘 Need Help?

**Documentation:**
- Full guide: `/documentation/features/PERSONA_MANAGEMENT.md`
- Implementation details: `/documentation/features/PERSONA_MANAGEMENT_IMPLEMENTATION.md`

**Support:**
- GitHub Issues: [Link to repo]
- Community: r/LocalLLM, r/ollama

---

**Version:** 1.0.0  
**Last Updated:** 2026-01-04  
**Maintained by:** Danny
