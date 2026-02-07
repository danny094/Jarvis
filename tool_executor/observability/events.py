
import json
import logging
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# Configure basic logging to stderr (for debug)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)

class EventLogger:
    """
    Emits structured JSON events to stdout.
    These are picked up by the TRION observability layer (e.g. Fluentd/Vector).
    """
    
    @staticmethod
    def emit(event_type: str, payload: Dict[str, Any], status: str = "info"):
        event = {
            "timestamp": datetime.now().isoformat(),
            "service": "tool-executor",
            "layer": 4,
            "type": event_type,
            "status": status,
            "payload": payload
        }
        # Print JSON to stdout for log collectors
        print(json.dumps(event), file=sys.stdout, flush=True)

    @staticmethod
    def log(message: str, level: str = "info"):
        """Human readable log to stderr"""
        if level == "error":
            logging.error(message)
        else:
            logging.info(message)
