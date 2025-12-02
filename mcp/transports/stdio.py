# mcp/transports/stdio.py
"""
STDIO Transport für lokale MCP-Prozesse.
Kommuniziert via stdin/stdout mit einem Subprocess.
"""

import subprocess
import json
import threading
import queue
from typing import Dict, Any, List, Optional
from utils.logger import log_info, log_error, log_debug


class STDIOTransport:
    """STDIO Transport für lokale MCP-Prozesse."""
    
    def __init__(self, command: str, timeout: int = 30):
        self.command = command
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self._response_queue = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
    
    def _start_process(self):
        """Startet den MCP-Prozess."""
        if self.process is not None:
            return
        
        try:
            log_debug(f"[STDIO] Starting: {self.command}")
            
            self.process = subprocess.Popen(
                self.command.split(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            self._running = True
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()
            
            log_info(f"[STDIO] Process started: PID {self.process.pid}")
            
        except Exception as e:
            log_error(f"[STDIO] Failed to start: {e}")
            raise
    
    def _read_output(self):
        """Liest stdout in separatem Thread."""
        while self._running and self.process:
            try:
                line = self.process.stdout.readline()
                if line:
                    try:
                        data = json.loads(line.strip())
                        self._response_queue.put(data)
                    except json.JSONDecodeError:
                        pass
                elif self.process.poll() is not None:
                    break
            except Exception as e:
                log_error(f"[STDIO] Read error: {e}")
                break
    
    def _send_request(self, payload: Dict) -> Dict:
        """Sendet Request und wartet auf Response."""
        self._start_process()
        
        try:
            # Request senden
            request_str = json.dumps(payload) + "\n"
            self.process.stdin.write(request_str)
            self.process.stdin.flush()
            
            # Auf Response warten
            response = self._response_queue.get(timeout=self.timeout)
            return response
            
        except queue.Empty:
            log_error(f"[STDIO] Timeout waiting for response")
            return {"error": "Timeout"}
        except Exception as e:
            log_error(f"[STDIO] Request failed: {e}")
            return {"error": str(e)}
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """Holt Tool-Liste vom MCP."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }
            
            log_debug(f"[STDIO] tools/list")
            
            response = self._send_request(payload)
            
            if "result" in response:
                result = response["result"]
                if isinstance(result, dict) and "tools" in result:
                    return result["tools"]
                elif isinstance(result, list):
                    return result
            
            return []
            
        except Exception as e:
            log_error(f"[STDIO] tools/list failed: {e}")
            return []
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Ruft ein Tool auf."""
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
            
            log_debug(f"[STDIO] tools/call {tool_name}")
            
            response = self._send_request(payload)
            
            if "error" in response:
                return {"error": response["error"]}
            
            return response.get("result", {})
            
        except Exception as e:
            log_error(f"[STDIO] call_tool failed: {e}")
            return {"error": str(e)}
    
    def health_check(self) -> bool:
        """Prüft ob MCP läuft."""
        try:
            if self.process is None:
                self._start_process()
            return self.process is not None and self.process.poll() is None
        except:
            return False
    
    def shutdown(self):
        """Beendet den Prozess."""
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            log_info("[STDIO] Process terminated")
