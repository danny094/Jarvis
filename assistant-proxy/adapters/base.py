# adapters/base.py
"""
Abstract Base Adapter.
Alle Chat-UI-Adapter erben von dieser Klasse.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from core.models import CoreChatRequest, CoreChatResponse


class BaseAdapter(ABC):
    """
    Basisklasse für alle Chat-UI-Adapter.
    
    Jeder Adapter muss implementieren:
    - name: Eindeutiger Name des Adapters
    - transform_request: Raw Request → CoreChatRequest
    - transform_response: CoreChatResponse → Raw Response für die UI
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Eindeutiger Name des Adapters (z.B. 'lobechat', 'openwebui')."""
        pass
    
    @abstractmethod
    def transform_request(self, raw_request: Dict[str, Any]) -> CoreChatRequest:
        """
        Transformiert einen Raw-Request der Chat-UI 
        in ein einheitliches CoreChatRequest.
        
        Args:
            raw_request: Der originale Request-Body der Chat-UI
            
        Returns:
            CoreChatRequest für die Core-Bridge
        """
        pass
    
    @abstractmethod
    def transform_response(self, response: CoreChatResponse) -> Dict[str, Any]:
        """
        Transformiert eine CoreChatResponse zurück
        ins Format der Chat-UI.
        
        Args:
            response: Die Response von der Core-Bridge
            
        Returns:
            Dict im Format der jeweiligen Chat-UI
        """
        pass
    
    def transform_error(self, error: Exception) -> Dict[str, Any]:
        """
        Transformiert einen Fehler ins Format der Chat-UI.
        Kann von Subklassen überschrieben werden.
        """
        return {
            "error": str(error),
            "adapter": self.name,
        }
