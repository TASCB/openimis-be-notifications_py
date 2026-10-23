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
    """Who can act on this step: holders of ``required_right``, narrowed to ``assigned_role``
    when the step carries one, so the notice reaches the people who can actually sign."""
    from notifications.audience import _users_with_right
    right = getattr(step, 'required_right', None)
    if not right:
        return []
    users = list(_users_with_right(right))
    role_id = getattr(step, 'assigned_role_id', None)
    if role_id:
        from core.models import UserRole
        in_role = set(UserRole.objects.filter(
            role_id=role_id, validity_to__isnull=True).values_list('user_id', flat=True))
        users = [u for u in users if u.i_user_id in in_role]
    return users


def _describe(obj):
    summary = obj.summary or {}
    flow = getattr(obj.flow, 'name', None) or getattr(obj.flow, 'code', 'Request')
    title = summary.get('title') or (f"Account for {summary['full_name']}" if summary.get('full_name') else None)
    return title or flow, flow


def _body(obj, flow, extra=None):
    summary = obj.summary or {}
    parts = [flow]
    if summary.get('reference_code'):
        parts.append(f"Ref {summary['reference_code']}")
    if extra:
        parts.append(extra)
    return ' · '.join(parts)


STEP_ASSIGNED = 'approval.step.assigned'


def _step_key(request_id, step):
    return f'{STEP_ASSIGNED}:{request_id}:{getattr(step, "id", "")}'


def _close_step_notices(request_id, keep_key=None):
    from django.utils import timezone
    from notifications.models import Notification
    qs = Notification.objects.filter(
        source_ref=f'approval:{request_id}', type__code=STEP_ASSIGNED, is_read=False)
    if keep_key:
        qs = qs.exclude(group_key=keep_key)
    qs.update(is_read=True, read_at=timezone.now())


def _request_id(kwargs):
    _args, _kwds, result = _payload(kwargs)
    request = _request_of(result)
    if not request:
        return None
    return request.get('id') if isinstance(request, dict) else getattr(request, 'id', None)


def _notify_current_step(request_id, kwargs):
    from approval.models import ApprovalRequest
    obj = ApprovalRequest.objects.filter(id=request_id).select_related('flow').first()
    if not obj:
        return
    # ApprovalStep has no is_current: the live step is the one at current_step_order.
    step = obj.steps.filter(order=obj.current_step_order, is_deleted=False).first()
    if not step:
        return
    key = _step_key(request_id, step)
    _close_step_notices(request_id, keep_key=key)
    recipients = _approvers_for_step(step)
    if not recipients:
        return

    title, flow = _describe(obj)
    notify_on_commit(
        type_code=STEP_ASSIGNED,
        subject=f'{title} is awaiting your approval',
        body=_body(obj, flow),
        target_route=route_for_approval(obj),
        source_ref=f'approval:{request_id}',
        group_key=key,
        actor=_actor(kwargs),
        recipients=recipients,
    )


def on_requested(**kwargs):
    """``approval_service.request_approval`` — tell the people who can act."""
    try:
        request_id = _request_id(kwargs)
        if request_id:
            _notify_current_step(request_id, kwargs)
    except Exception:
        logger.warning('notifications: approval.on_requested failed', exc_info=True)


def on_approved(**kwargs):
    try:
        _args, _kwds, result = _payload(kwargs)
        data = _request_of(result) or {}
        request_id = data.get('id') if isinstance(data, dict) else None
        if request_id and str(data.get('status', '')).upper() == 'PENDING':
            _notify_current_step(request_id, kwargs)
    except Exception:
        logger.warning('notifications: approval.on_approved failed', exc_info=True)


def _notify_subject(kwargs, type_code, subject_line, extra=None):
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

        title, flow = _describe(obj)
        notify_on_commit(
            type_code=type_code,
            subject=subject_line.format(label=title),
            body=_body(obj, flow, extra(obj) if extra else None),
            target_route=route_for_approval(obj),
            source_ref=f'approval:{request_id}',
            group_key=f'{type_code}:{request_id}',
            actor=_actor(kwargs),
            subject_user=owner,
        )
    except Exception:
        logger.warning('notifications: approval.%s failed', type_code, exc_info=True)


def _close_all(kwargs):
    try:
        request_id = _request_id(kwargs)
        if request_id:
            _close_step_notices(request_id)
    except Exception:
        logger.warning('notifications: closing approval notices failed', exc_info=True)


def on_rejected(**kwargs):
    _close_all(kwargs)
    _notify_subject(kwargs, 'approval.rejected', '{label} was rejected')


def on_returned(**kwargs):
    _close_all(kwargs)
    _notify_subject(kwargs, 'approval.returned', '{label} was returned for correction')


def _cancel_reason(obj):
    reason = (obj.summary or {}).get('cancel_reason')
    return f'Reason: {reason}' if reason else None


def on_finalized(**kwargs):
    _close_all(kwargs)
    _args, _kwds, result = _payload(kwargs)
    decision = str((_request_of(result) or {}).get('decision') or '').upper()
    if decision == 'APPROVED':
        _notify_subject(kwargs, 'approval.finalized', '{label} was approved')
    elif decision == 'CANCELLED':
        _notify_subject(kwargs, 'approval.finalized', '{label} was cancelled', extra=_cancel_reason)
