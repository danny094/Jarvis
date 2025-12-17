# adapters/matrix/adapter.py
# adapters/matrix/adapter.py

from assistant_proxy.core.bridge import AssistantBridge
from assistant_proxy.models import CoreChatRequest

class MatrixAdapter:
    def __init__(self, bridge: AssistantBridge):
        self.bridge = bridge

    async def handle_message(
        self,
        room_id: str,
        sender: str,
        body: str
    ) -> str | None:
        # Nur reagieren, wenn explizit erwähnt
        if "@ki" not in body:
            return None

        clean_text = body.replace("@ki", "").strip()
        if not clean_text:
            return None

        request = CoreChatRequest(
            conversation_id=f"matrix:{room_id}",
            user_id=sender,
            content=clean_text,
            source="matrix",
            stream=False
        )

        response = await self.bridge.process(request)
        return response.final_response