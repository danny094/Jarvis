### 1. Code erkennungs heuristiken 

***✅ Code-Extraktion gehärtet!***
Der Code wird jetzt sauberer erkannt.

| Methode| Beispiel | status |
| :---         |     :---:      |          ---: |
| Markdown mit Sprache  | ```python\ndef foo():\n```   | ✅ War schon   |
| Markdown ohne Sprache    | ```\ndef foo():\n```   | ✅ War schon     |
|  Inline Code    | `print("hello")`    | ✅ War schon     |
| Code mit Zeilennummern   | def foo():2  while:3  try:      | ✅ NEU!    |
| Roher Python-Code    | def foo():\n  return 42    | ✅ NEU!    |

### ***Vorher ❌ → Nachher ✅:***

# Input vom User (Copy-Paste mit Zeilennummern):
"teste diesen code: def get_float(msg):2  while True:3    try:4      f = float(input(msg))5"

# Wird jetzt erkannt und bereinigt zu:
def get_float(msg):
  while True:
    try:
      f = float(input(msg))

***Roher Code ohne Formatierung:***
# Input:
"kannst du das ausführen? def hello(): print('world') hello()"

# Wird jetzt erkannt!

┌─────────────────────────────────────────────────────────────────┐
│  _extract_code_from_message(text)                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Suche ```python ... ```     → Gefunden? Return!            │
│  2. Suche ``` ... ```           → Gefunden? Return!            │
│  3. Suche `inline code`         → Gefunden? Return!            │
│  4. Erkenne Zeilennummern?      → Bereinigen, dann weiter      │
│     (Pattern: ":2 while")                                       │
│  5. Erkenne Python-Keywords?    → Extrahiere rohen Code        │
│     (def, class, import, for, while, if, try, with, async)     │
│                                                                 │
│  Nichts gefunden? → Return None                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘