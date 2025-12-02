# mcp/transports/sse.py
"""
SSE (Server-Sent Events) Transport für MCPs.
Für Streaming/Realtime MCPs.
"""

import requests
import json
from typing import Dict, Any, List, Generator
from utils.logger import log_info, log_error, log_debug


class SSETransport:
    """SSE Transport für Streaming MCPs."""
    
    def __init__(self, url: str, api_key: str = None, timeout: int = 60):
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
    
    def _get_headers(self) -> Dict[str, str]:
        """Baut HTTP Headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """Holt Tool-Liste vom MCP."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }
            
            log_debug(f"[SSE] tools/list → {self.url}")
            
            # Für list_tools nutzen wir normales HTTP
            resp = requests.post(
                self.url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout
            )
            resp.raise_for_status()
            
            data = resp.json()
            
            if "result" in data:
                result = data["result"]
                if isinstance(result, dict) and "tools" in result:
                    return result["tools"]
                elif isinstance(result, list):
                    return result
            
            return []
            
        except Exception as e:
            log_error(f"[SSE] tools/list failed: {e}")
            return []
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Ruft ein Tool auf (sammelt alle SSE Events)."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            log_debug(f"[SSE] tools/call {tool_name} → {self.url}")
            
            result_data = None
            
            with requests.post(
                self.url,
                json=payload,
                headers=self._get_headers(),
                stream=True,
                timeout=self.timeout
            ) as resp:
                resp.raise_for_status()
                
                for line in resp.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix
                            try:
                                data = json.loads(data_str)
                                
                                # Letztes Event mit result speichern
                                if "result" in data:
                                    result_data = data["result"]
                                elif "error" in data:
                                    return {"error": data["error"]}
                                    
                            except json.JSONDecodeError:
                                continue
            
            return result_data or {}
            
        except Exception as e:
            log_error(f"[SSE] call_tool failed: {e}")
            return {"error": str(e)}
    
    def call_tool_stream(self, tool_name: str, arguments: Dict[str, Any]) -> Generator[Dict, None, None]:
        """Ruft ein Tool auf und streamt Events."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            log_debug(f"[SSE] tools/call (stream) {tool_name} → {self.url}")
            
            with requests.post(
                self.url,
                json=payload,
                headers=self._get_headers(),
                stream=True,
                timeout=self.timeout
            ) as resp:
                resp.raise_for_status()
                
                for line in resp.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                yield data
                            except json.JSONDecodeError:
                                continue
                                
        except Exception as e:
            log_error(f"[SSE] call_tool_stream failed: {e}")
            yield {"error": str(e)}
    
    def health_check(self) -> bool:
        """Prüft ob MCP erreichbar ist."""
        try:
            tools = self.list_tools()
            return True
        except:
            return False
