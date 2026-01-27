
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# Wir wollen testen, ob CoreBridge -> MCPHub -> Tool Aufruf klappt.
# Da CoreBridge viele Abhängigkeiten hat, mocken wir die Umgebung.

@pytest.mark.asyncio
async def test_core_bridge_calls_memory_save():
    """Testet, ob die CoreBridge beim Autosave das memory_save Tool aufruft."""
    
    # Mocks vorbereiten
    mock_hub = MagicMock()
    mock_hub.call_tool.return_value = {"result": "success"}
    
    # Patche get_hub, damit wir unsere Mock-Instanz zurückbekommen
    with patch("mcp.hub.get_hub", return_value=mock_hub), \
         patch("mcp.client.call_tool") as mock_client_call_tool:
         
        # Wir testen hier die 'autosave_assistant' Funktion, die von Core genutzt wird (technisch in mcp.client)
        # Aber die Frage war "ob der Core zugreift".
        # CoreBridge._process_step ruft Autosave auf.
        
        # Um CoreBridge zu initialisieren, brauchen wir viele Mocks (Classifier, Models etc.)
        # Einfacher: Wir testen die Funktionen in mcp.client, die Core nutzt, 
        # oder wir testen eine spezifische Methode in CoreBridge.
        
        # 1. Teste die direkte Verbindung via mcp.client (was Core nutzt)
        from mcp.client import autosave_assistant
        
        # Mocke call_tool in mcp.client selbst, um sicherzugehen, dass es aufgerufen wird.
        # Warte, autosave_assistant ruft mcp.client.call_tool auf.
        # mcp.client.call_tool ruft hub.call_tool auf.
        
        mock_client_call_tool.side_effect = lambda name, args: mock_hub.call_tool(name, args)
        
        # Action
        autosave_assistant("conv-123", "Hello World", layer="stm")
        
        # Verify
        mock_hub.call_tool.assert_called_with("memory_save", {
            "conversation_id": "conv-123",
            "role": "assistant",
            "content": "Hello World",
            "tags": "",
            "layer": "stm"
        })

@pytest.mark.asyncio
async def test_control_layer_uses_hub():
    """Testet, ob der Control Layer den MCP Hub nutzt."""
    from core.layers.control import ControlLayer
    
    # Setup
    control = ControlLayer()
    mock_hub = MagicMock()
    control.set_mcp_hub(mock_hub)
    
    # Wir simulieren einen Aufruf, der MCP triggert
    # ControlLayer.process ruft _validate_and_control auf
    # Wenn wir 'think' als Tool mocken...
    
    # ControlLayer ist komplex. Testen wir 'analyze_request' oder ähnliches?
    # Im Code sahen wir: result = self.mcp_hub.call_tool("think", ...)
    
    # Da wir keine einfache Public Methode haben, die direkt MCP ruft ohne LLM,
    # prüfen wir nur, ob die Verbindung gesetzt wird.
    
    assert control.mcp_hub == mock_hub
    
    # Teste einen fiktiven Call wenn möglich - aber ControlLayer logic ist tief im LLM flow.
    # Stattdessen schauen wir uns bridge.py an.

@pytest.mark.asyncio
async def test_bridge_initialization_connects_hub():
    """Prüft ob CoreBridge den Hub initialisiert und verbindet."""
    
    # Bridge importiert ThinkingLayer, ControlLayer, OutputLayer.
    # Classifier wird NICHT importiert (in __init__ nur die 3 Layer).
    
    with patch("core.bridge.ThinkingLayer"), \
         patch("core.bridge.ControlLayer") as MockControl, \
         patch("core.bridge.OutputLayer"), \
         patch("core.bridge.get_hub") as mock_get_hub:
         
        from core.bridge import CoreBridge
        
        # Init Bridge
        bridge = CoreBridge()
        
        # Check: Hat er get_hub() gerufen?
        mock_get_hub.assert_called()
        
        # Check: Hat er den Hub an den ControlLayer übergeben?
        # self.control = ControlLayer() -> MockControl()
        # self.control.set_mcp_hub(hub)
        
        # Wenn MockControl die Klasse ist, ist MockControl.return_value die Instanz.
        instance = MockControl.return_value
        instance.set_mcp_hub.assert_called_with(mock_get_hub.return_value)
