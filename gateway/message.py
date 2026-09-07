"""Gateway HTTP handlers for provider interactive message actions."""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.approval_broker import approval_resolution_post_payload, get_runtime_approval, record_approval_result
from shared.lib.config import settings
from shared.lib.db import async_session_factory
from shared.lib.mattermost_api import MattermostAPIError, get_user_username
from shared.lib.models import Approval, SessionEvent, Task

logger = logging.getLogger(__name__)
router = APIRouter()


class MattermostInteractiveAction(BaseModel):
    user_id: str = ""
    post_id: str = ""
    channel_id: str = ""
    team_id: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


def _verify_interactive_action_token(token: str) -> bool:
    expected = settings.message_bus.action_callback_secret
    if not expected:
        logger.error("Mattermost approval callback rejected because message_bus.action_callback_secret is unset")
        return False
    return hmac.compare_digest(token, expected)


def _interactive_error(message: str) -> dict[str, Any]:
    return {"error": {"message": message}}


@dataclass(frozen=True)
class ApprovalActionResolution:
    approval: Approval
    task: Task
    approved: bool | None
    status_message: str


async def resolve_approval_action(
    session: AsyncSession,
    *,
    context: dict[str, Any],
    user_id: str,
    username: str = "",
    post_id: str,
    channel_id: str,
    source: str,
) -> ApprovalActionResolution:
    """Apply one authenticated provider action to gateway-owned approval state."""
    decision = str(context.get("decision") or "").strip().lower()
    if decision not in {"approve", "reject"}:
        raise ValueError("Unsupported approval action")
    try:
        approval_id = UUID(str(context.get("approval_id") or ""))
    except ValueError as exc:
        raise ValueError("Invalid approval identifier") from exc

    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise ValueError("Approval not found")
    task = await session.get(Task, approval.task_id)
    if task is None:
        raise ValueError("Associated task not found")

    request_id = str(context.get("request_id") or "")
    if request_id:
        matched = await get_runtime_approval(
            session,
            task_id=approval.task_id,
            tool_name=approval.tool_name,
            request_id=request_id,
        )
        if matched is None or matched.id != approval.id:
            raise ValueError("Approval action no longer matches an open request")

    delivery = approval.approval_metadata.get("gateway_delivery", {}) if approval.approval_metadata else {}
    expected_post_id = str(delivery.get("post_id") or "")
    if expected_post_id and post_id and expected_post_id != post_id:
        raise ValueError("Approval action does not match the approval prompt")
    expected_channel_id = str(delivery.get("channel_id") or "")
    if expected_channel_id and channel_id and expected_channel_id != channel_id:
        raise ValueError("Approval action does not match the approval channel")

    if approval.status != "pending":
        return ApprovalActionResolution(
            approval=approval,
            task=task,
            approved=None,
            status_message=f":lock: Approval already resolved as **{approval.status}**.",
        )

    approved = decision == "approve"
    approved_by = username.strip() or user_id or "operator"
    session.add(
        SessionEvent(
            task_id=task.id,
            event_type="approval_action",
            data={
                "approval_id": str(approval.id),
                "tool_name": approval.tool_name,
                "decision": decision,
                "user_id": user_id,
                "username": approved_by,
                "post_id": post_id,
                "channel_id": channel_id,
            },
        )
    )
    await record_approval_result(
        session,
        task,
        approval,
        approved=approved,
        reason=None if approved else f"Approval rejected in message provider by {approved_by}",
        approved_by=approved_by,
        approved_by_user_id=user_id or None,
        approval_reply=decision,
        source=source,
    )
    await session.commit()
    status_label = "approved" if approved else "rejected"
    return ApprovalActionResolution(
        approval=approval,
        task=task,
        approved=approved,
        status_message=f":white_check_mark: Approval **{status_label}** for `{approval.tool_name}` by @{approved_by}.",
    )


async def _resolve_mattermost_username(user_id: str) -> str:
    if not user_id:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await get_user_username(
                client,
                api_url=settings.message_bus.api_url,
                bot_token=settings.message_bus.bot_token,
                user_id=user_id,
            )
    except (MattermostAPIError, httpx.HTTPError) as exc:
        logger.warning("Could not resolve Mattermost username for approval action: %s", exc)
        return ""


@router.post("/message/actions/approval")
async def message_approval_action(payload: MattermostInteractiveAction):
    context = payload.context or {}
    if not _verify_interactive_action_token(str(context.get("token") or "")):
        return _interactive_error("Invalid approval action token")

    username = await _resolve_mattermost_username(payload.user_id)
    async with async_session_factory() as session:
        try:
            resolution = await resolve_approval_action(
                session,
                context=context,
                user_id=payload.user_id,
                username=username,
                post_id=payload.post_id,
                channel_id=payload.channel_id,
                source="mattermost_interactive",
            )
        except ValueError as exc:
            return _interactive_error(str(exc))

    if resolution.approved is None:
        ephemeral_text = f"This approval is already {resolution.approval.status}."
        message = resolution.status_message
        props: dict[str, Any] = {}
    else:
        status_label = "approved" if resolution.approved else "rejected"
        ephemeral_text = f"You {status_label} this approval request."
        approved_by = username or payload.user_id or "operator"
        message, props = approval_resolution_post_payload(
            resolution.task,
            resolution.approval,
            approved=resolution.approved,
            approved_by=approved_by,
        )
    return {
        "update": {
            "message": message,
            "props": props,
        },
        "ephemeral_text": ephemeral_text,
        "skip_slack_parsing": True,
    }
