"""Access request adapter: ready to provision / account provisioned / request rejected.

Two distinct moments, and conflating them was the original bug. ``approval_service.finalized``
only moves the request to ICT_APPROVED -- the account does not exist yet. It is created later,
when ICT calls ``provision()``, which is where ``created_user`` is set. So the "your account
exists" message binds to ``access_request_service.provision``, and finalisation only tells ICT
there is something waiting.

A public applicant is not authenticated, so ``ApprovalRequest.requested_by`` is the *system*
user, never the applicant. Nothing applicant-facing may use it.
"""
import logging

from notifications.routing import route_for_approval
from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)

FLOW_CODE = 'ACCESS_REQUEST_ACCOUNT'


def _payload(kwargs):
    data = kwargs.get('data') or []
    args = data[0] if len(data) > 0 else ()
    kwds = data[1] if len(data) > 1 else {}
    return args, (kwds or {}), kwargs.get('result')


def _access_request_of(result):
    """Resolve the AccessRequest from a service result carrying ``data.id``."""
    if not isinstance(result, dict) or not result.get('success'):
        return None
    payload = result.get('data')
    request_id = payload.get('id') if isinstance(payload, dict) else None
    if not request_id:
        return None
    from access_request.models import AccessRequest
    return AccessRequest.objects.filter(id=request_id, is_deleted=False).first()


def on_provisioned(**kwargs):
    """Bound to ``access_request_service.provision``: the account now exists."""
    try:
        _args, _kwds, result = _payload(kwargs)
        req = _access_request_of(result)
        if not req or not req.created_user:
            return
        notify_on_commit(
            type_code='account.provisioned',
            subject='Your TASAF MIS account has been created',
            body=('Your account is ready. If you did not receive a set-password email, '
                  'contact ICT to have it re-sent.'),
            target_route='/access-requests',
            source_ref=f'access_request:{req.id}',
            group_key=f'account.provisioned:{req.id}',
            subject_user=req.created_user,
        )
    except Exception:
        logger.warning('notifications: access_request.on_provisioned failed', exc_info=True)


def on_approval_finalized(**kwargs):
    """Bound to ``approval_service.finalized``: the request is decided, not provisioned."""
    try:
        result = kwargs.get('result') or {}
        payload = result.get('data') if isinstance(result, dict) else None
        request_id = (payload or {}).get('id') if isinstance(payload, dict) else None
        if not request_id:
            return

        from approval.models import ApprovalRequest
        obj = ApprovalRequest.objects.filter(id=request_id).select_related('flow').first()
        if not obj or getattr(obj.flow, 'code', '') != FLOW_CODE:
            return

        approved = str(getattr(obj, 'status', '')).upper() == 'APPROVED'
        reference = getattr(obj, 'reference_code', '') or request_id
        common = {
            'target_route': route_for_approval(obj),
            'source_ref': f'access_request:{request_id}',
        }
        if approved:
            notify_on_commit(
                type_code='account.ready_to_provision',
                subject='An access request is approved and awaiting provisioning',
                body=f'Reference {reference}',
                group_key=f'account.ready_to_provision:{request_id}',
                **common,
            )
        else:
            notify_on_commit(
                type_code='account.request_rejected',
                subject='An access request was not approved',
                body=f'Reference {reference}',
                group_key=f'account.request_rejected:{request_id}',
                **common,
            )
    except Exception:
        logger.warning('notifications: access_request.on_approval_finalized failed', exc_info=True)
