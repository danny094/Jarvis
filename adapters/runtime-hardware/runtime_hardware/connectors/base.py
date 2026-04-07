from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from runtime_hardware.models import (
    AttachmentIntent,
    AttachmentPlan,
    AttachmentState,
    ConnectorInfo,
    HardwareResource,
    RuntimeCapability,
    ValidateResult,
)


class RuntimeConnector(ABC):
    @abstractmethod
    def info(self) -> ConnectorInfo:
        raise NotImplementedError

    @abstractmethod
    def list_resources(self) -> List[HardwareResource]:
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> List[RuntimeCapability]:
        raise NotImplementedError

    @abstractmethod
    def get_target_state(self, *, target_type: str, target_id: str) -> AttachmentState:
        raise NotImplementedError

    @abstractmethod
    def plan(self, *, target_type: str, target_id: str, intents: List[AttachmentIntent]) -> AttachmentPlan:
        raise NotImplementedError

    @abstractmethod
    def validate(self, *, target_type: str, target_id: str, resource_ids: List[str]) -> ValidateResult:
        raise NotImplementedError

    @abstractmethod
    def resource_index(self) -> Dict[str, HardwareResource]:
        raise NotImplementedError
