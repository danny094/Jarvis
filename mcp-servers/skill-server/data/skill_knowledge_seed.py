"""
SkillKnowledgeBase — Starter-Daten

Ausführen: python3 data/skill_knowledge_seed.py
Idempotent: UPSERT, kann beliebig oft ausgeführt werden.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_knowledge import add_entry, count

ENTRIES = [
    # ─── Netzwerk ─────────────────────────────────────────────────────────────
    {
        "category": "Netzwerk",
        "subcategory": "Status",
        "name": "ping_check",
        "description": "Prüft ob ein Host erreichbar ist via ICMP Ping",
        "packages": [],
        "triggers": ["ping", "host", "erreichbar", "netzwerk", "verbindung"],
        "complexity": "simple",
        "code_snippet": (
            "import subprocess\n"
            "def run(host='8.8.8.8', count=3):\n"
            "    r = subprocess.run(['ping','-c',str(count),host],\n"
            "                       capture_output=True, text=True, timeout=10)\n"
            "    return {'reachable': r.returncode == 0, 'output': r.stdout[-500:]}"
        ),
    },
    {
        "category": "Netzwerk",
        "subcategory": "Status",
        "name": "port_scan",
        "description": "Prüft ob bestimmte Ports auf einem Host offen sind",
        "packages": [],
        "triggers": ["port", "offen", "scan", "tcp", "firewall"],
        "complexity": "simple",
        "code_snippet": (
            "import socket\n"
            "def run(host='localhost', ports=[80, 443, 8080, 22]):\n"
            "    results = {}\n"
            "    for p in ports:\n"
            "        s = socket.socket()\n"
            "        s.settimeout(1)\n"
            "        results[p] = s.connect_ex((host, p)) == 0\n"
            "        s.close()\n"
            "    return results"
        ),
    },
    {
        "category": "Netzwerk",
        "subcategory": "HTTP",
        "name": "http_check",
        "description": "Prüft den HTTP-Status einer URL und misst Antwortzeit",
        "packages": ["requests"],
        "triggers": ["http", "status", "webseite", "url", "response", "latenz"],
        "complexity": "simple",
        "code_snippet": (
            "import requests, time\n"
            "def run(url='https://example.com', timeout=10):\n"
            "    t0 = time.time()\n"
            "    r = requests.get(url, timeout=timeout)\n"
            "    return {'status': r.status_code, 'ms': round((time.time()-t0)*1000)}"
        ),
    },
    {
        "category": "Netzwerk",
        "subcategory": "DNS",
        "name": "dns_lookup",
        "description": "Löst einen Hostnamen in IP-Adressen auf",
        "packages": [],
        "triggers": ["dns", "hostname", "ip", "auflösung", "nslookup"],
        "complexity": "simple",
        "code_snippet": (
            "import socket\n"
            "def run(host='google.com'):\n"
            "    ips = socket.getaddrinfo(host, None)\n"
            "    return {'host': host, 'ips': list({i[4][0] for i in ips})}"
        ),
    },

    # ─── System ───────────────────────────────────────────────────────────────
    {
        "category": "System",
        "subcategory": "Monitoring",
        "name": "cpu_watch",
        "description": "Liest CPU-Auslastung aus /proc/stat",
        "packages": [],
        "triggers": ["cpu", "auslastung", "last", "prozessor", "kern"],
        "complexity": "simple",
        "code_snippet": (
            "import time\n"
            "def _read(): return [int(x) for x in open('/proc/stat').readline().split()[1:]]\n"
            "def run():\n"
            "    a = _read(); time.sleep(0.5); b = _read()\n"
            "    idle = b[3]-a[3]; total = sum(b)-sum(a)\n"
            "    return {'cpu_percent': round(100*(1-idle/total),1)}"
        ),
    },
    {
        "category": "System",
        "subcategory": "Monitoring",
        "name": "ram_watch",
        "description": "Liest RAM-Verbrauch aus /proc/meminfo",
        "packages": [],
        "triggers": ["ram", "speicher", "memory", "arbeitsspeicher"],
        "complexity": "simple",
        "code_snippet": (
            "def run():\n"
            "    info = {}\n"
            "    for line in open('/proc/meminfo'):\n"
            "        k,v = line.split(':'); info[k.strip()] = int(v.split()[0])\n"
            "    total = info['MemTotal']; free = info['MemAvailable']\n"
            "    return {'total_mb': total//1024, 'free_mb': free//1024,\n"
            "            'used_pct': round(100*(1-free/total),1)}"
        ),
    },
    {
        "category": "System",
        "subcategory": "Prozesse",
        "name": "proc_list",
        "description": "Listet laufende Prozesse mit PID und Name",
        "packages": [],
        "triggers": ["prozesse", "laufend", "ps", "pid", "tasks"],
        "complexity": "simple",
        "code_snippet": (
            "import os\n"
            "def run(top=20):\n"
            "    procs = []\n"
            "    for pid in sorted(os.listdir('/proc')):\n"
            "        if not pid.isdigit(): continue\n"
            "        try:\n"
            "            name = open(f'/proc/{pid}/comm').read().strip()\n"
            "            procs.append({'pid': int(pid), 'name': name})\n"
            "        except: pass\n"
            "    return procs[:top]"
        ),
    },
    {
        "category": "System",
        "subcategory": "Disk",
        "name": "disk_usage",
        "description": "Prüft Festplattennutzung eines Pfads",
        "packages": [],
        "triggers": ["disk", "festplatte", "speicherplatz", "df", "partition"],
        "complexity": "simple",
        "code_snippet": (
            "import shutil\n"
            "def run(path='/'):\n"
            "    total, used, free = shutil.disk_usage(path)\n"
            "    return {'path': path, 'total_gb': round(total/1e9,1),\n"
            "            'used_gb': round(used/1e9,1), 'free_gb': round(free/1e9,1),\n"
            "            'used_pct': round(used/total*100,1)}"
        ),
    },

    # ─── API ──────────────────────────────────────────────────────────────────
    {
        "category": "API",
        "subcategory": "Wetter",
        "name": "weather_api",
        "description": "Aktuelles Wetter via Open-Meteo (kostenlos, kein API-Key)",
        "packages": ["requests"],
        "triggers": ["wetter", "temperatur", "forecast", "regen", "wind"],
        "complexity": "simple",
        "code_snippet": (
            "import requests\n"
            "def run(lat=52.5, lon=13.4, city='Berlin'):\n"
            "    url = 'https://api.open-meteo.com/v1/forecast'\n"
            "    r = requests.get(url, params={'latitude':lat,'longitude':lon,\n"
            "        'current_weather':True}, timeout=10)\n"
            "    w = r.json()['current_weather']\n"
            "    return {'city': city, 'temp_c': w['temperature'],\n"
            "            'wind_kmh': w['windspeed']}"
        ),
    },
    {
        "category": "API",
        "subcategory": "Finanzen",
        "name": "crypto_price",
        "description": "Aktueller Krypto-Kurs via CoinGecko (kostenlos)",
        "packages": ["requests"],
        "triggers": ["bitcoin", "kurs", "crypto", "ethereum", "kryptowährung", "coin"],
        "complexity": "simple",
        "code_snippet": (
            "import requests\n"
            "def run(coins=['bitcoin','ethereum','solana'], currency='eur'):\n"
            "    ids = ','.join(coins)\n"
            "    r = requests.get('https://api.coingecko.com/api/v3/simple/price',\n"
            "        params={'ids': ids, 'vs_currencies': currency}, timeout=10)\n"
            "    return r.json()"
        ),
    },
    {
        "category": "API",
        "subcategory": "Finanzen",
        "name": "stock_price",
        "description": "Aktienkurs via Yahoo Finance (yfinance Paket benötigt)",
        "packages": ["yfinance"],
        "triggers": ["aktie", "kurs", "börse", "stock", "dax", "nasdaq"],
        "complexity": "medium",
        "code_snippet": (
            "import yfinance as yf\n"
            "def run(ticker='AAPL'):\n"
            "    t = yf.Ticker(ticker)\n"
            "    info = t.fast_info\n"
            "    return {'ticker': ticker, 'price': info.last_price,\n"
            "            'currency': info.currency}"
        ),
    },

    # ─── Daten ────────────────────────────────────────────────────────────────
    {
        "category": "Daten",
        "subcategory": "Analyse",
        "name": "csv_reader",
        "description": "Liest eine CSV-Datei und gibt Statistiken zurück",
        "packages": [],
        "triggers": ["csv", "tabelle", "daten", "excel", "spalten"],
        "complexity": "simple",
        "code_snippet": (
            "import csv\n"
            "def run(path, delimiter=','):\n"
            "    with open(path) as f:\n"
            "        reader = csv.DictReader(f, delimiter=delimiter)\n"
            "        rows = list(reader)\n"
            "    return {'rows': len(rows), 'columns': list(rows[0].keys()) if rows else [],\n"
            "            'preview': rows[:3]}"
        ),
    },
    {
        "category": "Daten",
        "subcategory": "Analyse",
        "name": "json_parse",
        "description": "Lädt und analysiert eine JSON-Datei oder URL",
        "packages": ["requests"],
        "triggers": ["json", "parsen", "struktur", "api response", "daten"],
        "complexity": "simple",
        "code_snippet": (
            "import json, requests\n"
            "def run(source, is_url=False):\n"
            "    if is_url:\n"
            "        data = requests.get(source, timeout=10).json()\n"
            "    else:\n"
            "        with open(source) as f: data = json.load(f)\n"
            "    keys = list(data.keys()) if isinstance(data, dict) else f'list[{len(data)}]'\n"
            "    return {'type': type(data).__name__, 'keys_or_length': keys}"
        ),
    },

    # ─── Berechnung ───────────────────────────────────────────────────────────
    {
        "category": "Berechnung",
        "subcategory": "Mathematik",
        "name": "fibonacci",
        "description": "Berechnet die Fibonacci-Folge bis n",
        "packages": [],
        "triggers": ["fibonacci", "folge", "berechne", "zahlen", "mathematik"],
        "complexity": "simple",
        "code_snippet": (
            "def run(n=10):\n"
            "    a, b, seq = 0, 1, []\n"
            "    while len(seq) < n:\n"
            "        seq.append(a); a, b = b, a+b\n"
            "    return {'n': n, 'sequence': seq}"
        ),
    },
    {
        "category": "Berechnung",
        "subcategory": "Statistik",
        "name": "statistics_calc",
        "description": "Berechnet Mittelwert, Median und Standardabweichung",
        "packages": [],
        "triggers": ["mittelwert", "median", "stats", "statistik", "durchschnitt"],
        "complexity": "simple",
        "code_snippet": (
            "import statistics\n"
            "def run(numbers=[1,2,3,4,5,6,7,8,9,10]):\n"
            "    return {'mean': statistics.mean(numbers),\n"
            "            'median': statistics.median(numbers),\n"
            "            'stdev': round(statistics.stdev(numbers),3),\n"
            "            'min': min(numbers), 'max': max(numbers)}"
        ),
    },

    # ─── Datei ────────────────────────────────────────────────────────────────
    {
        "category": "Datei",
        "subcategory": "Lesen",
        "name": "file_reader",
        "description": "Liest eine Textdatei und gibt Inhalt + Metadaten zurück",
        "packages": [],
        "triggers": ["datei", "lesen", "inhalt", "text", "file"],
        "complexity": "simple",
        "code_snippet": (
            "import os\n"
            "def run(path, max_chars=2000):\n"
            "    stat = os.stat(path)\n"
            "    with open(path, errors='replace') as f:\n"
            "        content = f.read(max_chars)\n"
            "    return {'path': path, 'size_kb': round(stat.st_size/1024,1),\n"
            "            'content': content, 'truncated': stat.st_size > max_chars}"
        ),
    },
    {
        "category": "Datei",
        "subcategory": "Suchen",
        "name": "file_search",
        "description": "Sucht rekursiv nach Dateien die ein Muster enthalten",
        "packages": [],
        "triggers": ["suchen", "finden", "grep", "muster", "durchsuchen"],
        "complexity": "simple",
        "code_snippet": (
            "import os\n"
            "def run(directory='.', pattern='', extension=''):\n"
            "    matches = []\n"
            "    for root, _, files in os.walk(directory):\n"
            "        for f in files:\n"
            "            if extension and not f.endswith(extension): continue\n"
            "            path = os.path.join(root, f)\n"
            "            try:\n"
            "                if pattern in open(path, errors='replace').read():\n"
            "                    matches.append(path)\n"
            "            except: pass\n"
            "    return {'matches': matches[:50], 'total': len(matches)}"
        ),
    },
]


def seed():
    inserted = 0
    for entry in ENTRIES:
        ok = add_entry(**entry)
        if ok:
            inserted += 1
    total = count()
    print(f"[Seed] {inserted}/{len(ENTRIES)} Einträge eingefügt/aktualisiert. Gesamt in DB: {total}")


if __name__ == "__main__":
    seed()
