# server.py - Network Telemetry MCP Server (Jarvis Style)

import asyncio
import signal
from fastmcp import FastMCP

from .config import Config
from .database import init_db, migrate_db
from .tools import register_tools
from .recorder import NetworkRecorder
from .analyst import NetworkAnalyst


# Background tasks
recorder = None
analyst = None


def handle_shutdown(signum, frame):
    """Graceful shutdown handler"""
    print("\n→ Shutdown signal received...")
    if recorder:
        recorder.stop()
    if analyst:
        analyst.stop()


def main():
    global recorder, analyst
    
    print("\n" + "="*40)
    print("📡 NETWORK TELEMETRY MCP SERVER – START")
    print("="*40)
    
    # -------------------------------------------
    # 1. Configuration
    # -------------------------------------------
    print("→ Validating configuration…")
    Config.validate()
    print("✓ Config OK\n")
    
    # -------------------------------------------
    # 2. Database
    # -------------------------------------------
    print("→ Initializing database…")
    init_db()
    print("✓ DB: init")
    
    print("→ Checking database migrations…")
    migrate_db()
    print("✓ DB: migrations complete\n")
    
    # -------------------------------------------
    # 3. MCP Server
    # -------------------------------------------
    print("→ Creating MCP server…")
    mcp = FastMCP("network_telemetry", stateless_http=True)
    print("✓ MCP instance active")
    
    # -------------------------------------------
    # 4. Tools Registration
    # -------------------------------------------
    print("→ Registering MCP tools…")
    register_tools(mcp)
    print("✓ Tools loaded!\n")
    
    # List loaded tools
    try:
        tool_names = [t.name for t in mcp.tools]
        print("🔧 Available Tools:")
        for name in tool_names:
            print(f"   • {name}")
        print()
    except:
        print("⚠ Could not list tools\n")
    
    # -------------------------------------------
    # 5. Background Services
    # -------------------------------------------
    print("→ Starting background services…")
    
    # Create recorder and analyst
    recorder = NetworkRecorder()
    analyst = NetworkAnalyst()
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    # Start background tasks
    loop = asyncio.get_event_loop()
    loop.create_task(recorder.run())
    loop.create_task(analyst.run())
    
    print("✓ Background services started\n")
    
    # -------------------------------------------
    # 6. Run Server
    # -------------------------------------------
    print("="*40)
    print("🚀 SERVER READY - Listening for MCP calls")
    print("="*40 + "\n")
    
    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\n→ Shutdown requested")
    finally:
        if recorder:
            recorder.stop()
        if analyst:
            analyst.stop()
        print("✓ Server stopped cleanly\n")


if __name__ == "__main__":
    main()
