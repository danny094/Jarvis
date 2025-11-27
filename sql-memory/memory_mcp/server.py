# server.py (Deluxe Edition)

import json
import time
from fastmcp import FastMCP

from .database import init_db, migrate_db
from .tools import register_tools


def main():
    print("\n==============================")
    print("🧠 SQL MEMORY MCP SERVER – START")
    print("==============================")

    # -------------------------------------------
    # 1. Datenbank initialisieren
    # -------------------------------------------
    print("→ Initialisiere Datenbank…")
    init_db()
    print("✓ DB: init")

    print("→ Prüfe / migriere Datenbankstruktur…")
    migrate_db()
    print("✓ DB: migration abgeschlossen\n")

    # -------------------------------------------
    # 2. MCP Server erzeugen
    # -------------------------------------------
    print("→ MCP Server wird erstellt…")
    mcp = FastMCP("sql_memory", stateless_http=True)
    print("✓ MCP Instanz aktiv")

    # -------------------------------------------
    # 3. Tools registrieren
    # -------------------------------------------
    print("→ Lese und registriere Tools…")
    register_tools(mcp)
    print("✓ Tools geladen!\n")

    # Tool-Listing
    try:
        tool_names = [t.name for t in mcp.tools]
        print("🔧 Geladene Tools:")
        for name in tool_names:
            print("   •", name)
        print()
    except:
        print("⚠ Konnte Tool-Liste nicht anzeigen\n")

    # -------------------------------------------
    # 4. Healthcheck Endpoint (NEU)
    # -------------------------------------------
    @mcp.tool
    def memory_healthcheck() -> str:
        """Einfach prüfen, ob der MCP-Server lebt."""
        return json.dumps({
            "status": "ok",
            "server": "sql_memory",
            "timestamp": time.time()
        })

    print("✓ Healthcheck aktiviert (/tools/call memory_healthcheck)\n")

    # -------------------------------------------
    # 5. START
    # -------------------------------------------
    print("🚀 Starte SQL Memory MCP Server:")
    print("   → Host: 0.0.0.0")
    print("   → Port: 8081")
    print("   → Pfad: /mcp\n")
    print("==============================\n")

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8081,
        path="/mcp",
    )


if __name__ == "__main__":
    main()