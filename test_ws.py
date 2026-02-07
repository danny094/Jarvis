
import asyncio
import websockets

async def test():
    uri = "ws://localhost:8401"
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Successfully connected to {uri}")
            message = await websocket.recv()
            print(f"Received: {message}")
    except Exception as e:
        print(f"Connection failed: {e}")

asyncio.get_event_loop().run_until_complete(test())
