# tests/debug_thinking.py
import asyncio
import logging
import sys
import os

# Configure logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

async def main():
    print("🚀 Debugging ThinkingLayer...")
    
    try:
        from core.layers.thinking import ThinkingLayer
        layer = ThinkingLayer()
        print(f"Model: {layer.model}")
        print(f"Base: {layer.ollama_base}")
        
        query = "What time is it?"
        print(f"\nAnalyzing: '{query}'...")
        
        result = await layer.analyze(query, memory_context="")
        
        print("\n--- RESULT ---")
        import json
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
