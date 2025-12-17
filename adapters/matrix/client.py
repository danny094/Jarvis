# adapters/matrix/client.py

import asyncio
from nio import AsyncClient, RoomMessageText

from .adapter import MatrixAdapter
from .config import MATRIX_HOMESERVER, BOT_USER_ID, ACCESS_TOKEN
from assistant_proxy.core.bridge import AssistantBridge

async def main():
    bridge = AssistantBridge()
    adapter = MatrixAdapter(bridge)

    client = AsyncClient(
        homeserver=MATRIX_HOMESERVER,
        user=BOT_USER_ID,
        device_id="assistant-proxy"
    )

    client.access_token = ACCESS_TOKEN
    client.user_id = BOT_USER_ID

    async def on_message(room, event: RoomMessageText):
        # Eigene Nachrichten ignorieren
        if event.sender == BOT_USER_ID:
            return

        reply = await adapter.handle_message(
            room.room_id,
            event.sender,
            event.body
        )

        if reply:
            await client.room_send(
                room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": reply
                }
            )

    client.add_event_callback(on_message, RoomMessageText)

    await client.sync_forever(timeout=30000)

if __name__ == "__main__":
    asyncio.run(main())