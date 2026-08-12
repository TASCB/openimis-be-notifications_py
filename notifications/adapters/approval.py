"""Approval engine adapter. Nothing in openimis-be-approval_py changes."""
import logging

from notifications.routing import route_for_approval
from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)


def _payload(kwargs):
    """Unpack ``data=[args, kwargs]`` + ``result`` from a service signal."""
    data = kwargs.get('data') or []
    args = data[0] if len(data) > 0 else ()
    kwds = data[1] if len(data) > 1 else {}
    return args, (kwds or {}), kwargs.get('result')


def _request_of(result):
    if isinstance(result, dict):
        return result.get('data') or result
    return None


def _actor(kwargs):
    cls_ = kwargs.get('cls_')
    return getattr(cls_, 'user', None)


def _approvers_for_step(step):
    """Who can act on this step, from its own ``required_right``."""
    from notifications.audience import _users_with_right
    right = getattr(step, 'required_right', None)
    if not right:
        return []
    return list(_users_with_right(right))


def on_requested(**kwargs):
    """``approval_service.request_approval`` — tell the people who can act."""
    try:
        _args, _kwds, result = _payload(kwargs)
        request = _request_of(result)
        if not request:
            return
        request_id = request.get('id') if isinstance(request, dict) else getattr(request, 'id', None)
        if not request_id:
            return

        from approval.models import ApprovalRequest
        obj = ApprovalRequest.objects.filter(id=request_id).select_related('flow').first()
        if not obj:
            return
        step = getattr(obj, 'current_step', None) or obj.steps.filter(
            is_current=True).first() if hasattr(obj, 'steps') else None
        recipients = _approvers_for_step(step) if step else []
        if not recipients:
            return

        label = getattr(obj.flow, 'name', None) or getattr(obj.flow, 'code', 'Request')
        notify_on_commit(
            type_code='approval.step.assigned',
            subject=f'{label} is awaiting your approval',
            body=f'Reference {getattr(obj, "reference_code", "") or request_id}',
            target_route=route_for_approval(obj),
            source_ref=f'approval:{request_id}',
            group_key=f'approval.step.assigned:{request_id}:{getattr(step, "id", "")}',
            actor=_actor(kwargs),
            recipients=recipients,
        )
    except Exception:
        logger.warning('notifications: approval.on_requested failed', exc_info=True)


def _notify_subject(kwargs, type_code, subject_line):
    try:
        _args, _kwds, result = _payload(kwargs)
        request = _request_of(result)
        if not request:
            return
        request_id = request.get('id') if isinstance(request, dict) else getattr(request, 'id', None)
        if not request_id:
            return

        from approval.models import ApprovalRequest
        obj = ApprovalRequest.objects.filter(id=request_id).select_related('flow').first()
        if not obj:
            return

        owner = getattr(obj, 'requested_by', None) or getattr(obj, 'user_created', None)
        if not owner:
            return

        label = getattr(obj.flow, 'name', None) or getattr(obj.flow, 'code', 'Request')
        notify_on_commit(
            type_code=type_code,
            subject=subject_line.format(label=label),
            body=f'Reference {getattr(obj, "reference_code", "") or request_id}',
            target_route=route_for_approval(obj),
            source_ref=f'approval:{request_id}',
            group_key=f'{type_code}:{request_id}',
            actor=_actor(kwargs),
            subject_user=owner,
        )
    except Exception:
        logger.warning('notifications: approval.%s failed', type_code, exc_info=True)


def on_rejected(**kwargs):
    _notify_subject(kwargs, 'approval.rejected', '{label} was rejected')


def on_returned(**kwargs):
    _notify_subject(kwargs, 'approval.returned', '{label} was returned for correction')


def on_finalized(**kwargs):
    _notify_subject(kwargs, 'approval.finalized', '{label} was finalised')
