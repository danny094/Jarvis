# mcp/transports/http.py
"""
Smart HTTP Transport für MCPs.

Erkennt automatisch:
- Simple JSON-RPC
- Streamable HTTP (mit Session)
- Streamable HTTP (stateless)

Handhabt Sessions automatisch wenn nötig.
"""

import requests
import json
import uuid
from typing import Dict, Any, List, Optional
from utils.logger import log_info, log_error, log_debug, log_warning


class HTTPTransport:
    """
    Smart HTTP Transport - erkennt Format automatisch.
    
    Unterstützte Formate:
    - json: Einfaches JSON-RPC
    - streamable: Streamable HTTP mit Session-Management
    - streamable-stateless: Streamable HTTP ohne Session
    """
    
    # Format-Konstanten
    FORMAT_UNKNOWN = "unknown"
    FORMAT_JSON = "json"
    FORMAT_STREAMABLE = "streamable"
    FORMAT_STREAMABLE_STATELESS = "streamable-stateless"
    
    def __init__(self, url: str, api_key: str = None, timeout: int = 30):
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        
        # Auto-Detection State
        self._format: Optional[str] = None
        self._session_id: Optional[str] = None
        self._format_detected = False
    
    # ═══════════════════════════════════════════════════════════════
    # HEADER BUILDERS
    # ═══════════════════════════════════════════════════════════════
    
    def _get_base_headers(self) -> Dict[str, str]:
        """Basis-Headers für alle Requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    def _get_headers_with_session(self) -> Dict[str, str]:
        """Headers mit Session-ID (wenn vorhanden)."""
        headers = self._get_base_headers()
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers
    
    # ═══════════════════════════════════════════════════════════════
    # FORMAT DETECTION
    # ═══════════════════════════════════════════════════════════════
    
    def _detect_format(self) -> str:
        """
        Erkennt automatisch welches Format das MCP braucht.
        
        Strategie:
        1. Sende tools/list ohne Session
        2. Analysiere Response/Error
        3. Setze Format entsprechend
        """
        if self._format_detected:
            return self._format
        
        log_debug(f"[HTTP] Auto-detecting format for {self.url}")
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        
        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers=self._get_base_headers(),
                timeout=self.timeout,
                stream=True
            )
            
            content_type = resp.headers.get("Content-Type", "")
            
            # Check für Session-Fehler
            if resp.status_code == 400:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("error", {}).get("message", "")
                    
                    if "session" in error_msg.lower() or "Missing session ID" in error_msg:
                        log_info(f"[HTTP] Detected: Streamable HTTP (needs session)")
                        self._format = self.FORMAT_STREAMABLE
                        self._format_detected = True
                        return self._format
                except:
                    pass
            
            # Erfolgreiche Response analysieren
            if resp.status_code == 200:
                if "text/event-stream" in content_type:
                    log_info(f"[HTTP] Detected: Streamable HTTP (stateless)")
                    self._format = self.FORMAT_STREAMABLE_STATELESS
                else:
                    log_info(f"[HTTP] Detected: Simple JSON-RPC")
                    self._format = self.FORMAT_JSON
                
                self._format_detected = True
                return self._format
            
            # 406 Not Acceptable = braucht SSE Headers (schon gesendet, also stateless)
            if resp.status_code == 406:
                log_info(f"[HTTP] Detected: Streamable HTTP (stateless, needs Accept header)")
                self._format = self.FORMAT_STREAMABLE_STATELESS
                self._format_detected = True
                return self._format
            
            log_warning(f"[HTTP] Could not detect format, status={resp.status_code}")
            self._format = self.FORMAT_UNKNOWN
            self._format_detected = True
            return self._format
            
        except Exception as e:
            log_error(f"[HTTP] Format detection failed: {e}")
            self._format = self.FORMAT_UNKNOWN
            self._format_detected = True
            return self._format
    
    # ═══════════════════════════════════════════════════════════════
    # SESSION MANAGEMENT
    # ═══════════════════════════════════════════════════════════════
    
    def _initialize_session(self) -> bool:
        """
        Initialisiert eine Session für Streamable HTTP.
        
        Sendet 'initialize' Request und speichert Session-ID.
        """
        if self._session_id:
            return True
        
        log_debug(f"[HTTP] Initializing session for {self.url}")
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp-hub",
                    "version": "1.0.0"
                }
            }
        }
        
        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers=self._get_base_headers(),
                timeout=self.timeout,
                stream=True
            )
            
            # Session-ID aus Response-Header
            session_id = resp.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id
                log_info(f"[HTTP] Session initialized: {session_id[:8]}...")
                return True
            
            # Manche MCPs geben Session-ID im Body zurück
            content_type = resp.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                result = self._parse_sse_response(resp)
                if isinstance(result, dict):
                    # Generiere eigene Session-ID wenn Server keine gibt
                    self._session_id = str(uuid.uuid4())
                    log_info(f"[HTTP] Session initialized (client-generated): {self._session_id[:8]}...")
                    return True
            
            log_warning(f"[HTTP] No session ID received")
            return False
            
        except Exception as e:
            log_error(f"[HTTP] Session initialization failed: {e}")
            return False
    
    def _ensure_session(self) -> bool:
        """Stellt sicher dass eine Session existiert (wenn nötig)."""
        if self._format == self.FORMAT_STREAMABLE:
            if not self._session_id:
                return self._initialize_session()
        return True
    
    # ═══════════════════════════════════════════════════════════════
    # RESPONSE PARSING
    # ═══════════════════════════════════════════════════════════════
    
    def _parse_sse_response(self, response: requests.Response) -> Any:
        """Parst SSE-Response und extrahiert das Result."""
        result = None
        
        for line in response.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                
                # SSE Format: "data: {...}"
                if decoded.startswith("data: "):
                    try:
                        data = json.loads(decoded[6:])
                        
                        if "result" in data:
                            result = data["result"]
                        elif "error" in data:
                            return {"error": data["error"]}
                    except json.JSONDecodeError:
                        continue
                
                # Manchmal direkt JSON ohne "data: " Prefix
                elif decoded.startswith("{"):
                    try:
                        data = json.loads(decoded)
                        if "result" in data:
                            result = data["result"]
                        elif "error" in data:
                            return {"error": data["error"]}
                    except json.JSONDecodeError:
                        continue
        
        return result
    
    def _parse_response(self, response: requests.Response) -> Any:
        """Parst Response basierend auf Content-Type."""
        content_type = response.headers.get("Content-Type", "")
        
        if "text/event-stream" in content_type:
            return self._parse_sse_response(response)
        
        # JSON Response
        try:
            data = response.json()
            if "error" in data:
                return {"error": data["error"]}
            return data.get("result", data)
        except:
            return None
    
    # ═══════════════════════════════════════════════════════════════
    # SMART REQUEST (with auto-retry)
    # ═══════════════════════════════════════════════════════════════
    
    def _smart_request(self, payload: Dict[str, Any], retry_count: int = 0) -> Any:
        """
        Sendet Request mit automatischem Format-Handling.
        
        - Erkennt Format beim ersten Call
        - Initialisiert Session wenn nötig
        - Retry bei Session-Fehlern
        """
        # Format erkennen
        if not self._format_detected:
            self._detect_format()
        
        # Session sicherstellen
        if not self._ensure_session():
            log_error(f"[HTTP] Could not establish session")
            return {"error": "Session initialization failed"}
        
        # Request senden
        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers=self._get_headers_with_session(),
                timeout=self.timeout,
                stream=True
            )
            
            # Session-Fehler → Retry mit neuer Session
            if resp.status_code == 400 and retry_count < 2:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("error", {}).get("message", "")
                    
                    if "session" in error_msg.lower():
                        log_warning(f"[HTTP] Session error, reinitializing...")
                        self._session_id = None
                        self._format = self.FORMAT_STREAMABLE
                        return self._smart_request(payload, retry_count + 1)
                except:
                    pass
            
            resp.raise_for_status()
            return self._parse_response(resp)
            
        except requests.exceptions.HTTPError as e:
            log_error(f"[HTTP] HTTP error: {e}")
            return {"error": str(e)}
        except Exception as e:
            log_error(f"[HTTP] Request failed: {e}")
            return {"error": str(e)}
    
    # ═══════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """Holt Tool-Liste vom MCP."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        
        log_debug(f"[HTTP] tools/list → {self.url}")
        
        result = self._smart_request(payload)
        
        if isinstance(result, dict):
            if "error" in result:
                log_error(f"[HTTP] tools/list error: {result['error']}")
                return []
            if "tools" in result:
                return result["tools"]
        
        if isinstance(result, list):
            return result
        
        return []
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Ruft ein Tool auf."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        log_debug(f"[HTTP] tools/call {tool_name} → {self.url}")
        
        result = self._smart_request(payload)
        
        if isinstance(result, dict) and "error" in result:
            log_error(f"[HTTP] Tool error: {result['error']}")
        
        return result
    
    def health_check(self) -> bool:
        """Prüft ob MCP erreichbar ist."""
        try:
            tools = self.list_tools()
            return isinstance(tools, list)
        except:
            return False
    
    def get_format(self) -> str:
        """Gibt erkanntes Format zurück."""
        if not self._format_detected:
            self._detect_format()
        return self._format or self.FORMAT_UNKNOWN
    
    def reset(self):
        """Reset für neuen Detection-Versuch."""
        self._format = None
        self._session_id = None
        self._format_detected = False
