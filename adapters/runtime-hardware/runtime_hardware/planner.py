from __future__ import annotations

from typing import Dict, Iterable, List

from .models import AttachmentIntent, AttachmentPlan, HardwareResource, PlanAction, RuntimeCapability


def _plan_action_metadata(resource: HardwareResource) -> dict:
    return {
        "kind": resource.kind,
        "host_path": resource.host_path,
        "risk_level": resource.risk_level,
        "capabilities": list(resource.capabilities or []),
        "availability_state": resource.availability_state,
        "resource_metadata": dict(resource.metadata or {}),
    }


def build_plan(
    *,
    connector: str,
    target_type: str,
    target_id: str,
    intents: Iterable[AttachmentIntent],
    resources: Dict[str, HardwareResource],
    capabilities: Dict[str, RuntimeCapability],
) -> AttachmentPlan:
    actions: List[PlanAction] = []

    for intent in intents:
        resource = resources.get(intent.resource_id)
        if resource is None:
            actions.append(
                PlanAction(
                    resource_id=intent.resource_id,
                    action="reject",
                    supported=False,
                    explanation="resource_not_found",
                )
            )
            continue

        capability = capabilities.get(resource.kind)
        if capability is None:
            actions.append(
                PlanAction(
                    resource_id=resource.id,
                    action="unsupported",
                    supported=False,
                    explanation=f"unsupported_resource_kind:{resource.kind}",
                )
            )
            continue

        if target_type not in {"container", "blueprint"}:
            actions.append(
                PlanAction(
                    resource_id=resource.id,
                    action="unsupported",
                    supported=False,
                    explanation=f"unsupported_target_type:{target_type}",
                )
            )
            continue

        if capability.attach_live:
            actions.append(
                PlanAction(
                    resource_id=resource.id,
                    action="live_attach",
                    supported=True,
                    requires_restart=False,
                    requires_approval=bool(capability.requires_privileged),
                    explanation="live_attach_supported",
                    metadata=_plan_action_metadata(resource),
                )
            )
            continue

        if capability.stage_supported:
            actions.append(
                PlanAction(
                    resource_id=resource.id,
                    action="stage_for_recreate",
                    supported=True,
                    requires_restart=True,
                    requires_approval=bool(capability.requires_privileged),
                    explanation=capability.notes or "container_runtime_requires_recreate",
                    metadata=_plan_action_metadata(resource),
                )
            )
            continue

        actions.append(
            PlanAction(
                resource_id=resource.id,
                action="unsupported",
                supported=False,
                requires_approval=bool(capability.requires_privileged),
                explanation=capability.notes or "unsupported",
                metadata=_plan_action_metadata(resource),
            )
        )

    if not actions:
        summary = "no_intents"
    elif any(action.action == "live_attach" for action in actions):
        summary = "contains_live_attach"
    elif any(action.action == "stage_for_recreate" for action in actions):
        summary = "requires_recreate"
    else:
        summary = "unsupported"

    return AttachmentPlan(
        target_type=target_type,
        target_id=target_id,
        connector=connector,
        actions=actions,
        summary=summary,
    )
