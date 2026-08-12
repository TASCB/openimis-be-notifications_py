"""Access request adapter: account provisioned / request rejected.

There is no ``access_request_service.provisioned`` signal. Provisioning happens when the
ACCESS_REQUEST_ACCOUNT approval finalises, so this binds to ``approval_service.finalized``
and filters by flow code -- adding a signal to access_request would break the one-way
dependency.
"""
import logging

from notifications.routing import route_for_approval
from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)

FLOW_CODE = 'ACCESS_REQUEST_ACCOUNT'


def on_approval_finalized(**kwargs):
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

        owner = getattr(obj, 'requested_by', None) or getattr(obj, 'user_created', None)
        if not owner:
            return

        approved = str(getattr(obj, 'status', '')).upper() in ('APPROVED', 'FINALIZED', 'COMPLETED')
        if approved:
            notify_on_commit(
                type_code='account.provisioned',
                subject='Your TASAF MIS account has been created',
                body=('Your account is ready. If you did not receive a set-password email, '
                      'contact ICT to have it re-sent.'),
                target_route=route_for_approval(obj),
                source_ref=f'access_request:{request_id}',
                group_key=f'account.provisioned:{request_id}',
                subject_user=owner, recipients=[owner],
            )
        else:
            notify_on_commit(
                type_code='account.request_rejected',
                subject='Your access request was not approved',
                body=f'Reference {getattr(obj, "reference_code", "") or request_id}',
                target_route=route_for_approval(obj),
                source_ref=f'access_request:{request_id}',
                group_key=f'account.request_rejected:{request_id}',
                subject_user=owner, recipients=[owner],
            )
    except Exception:
        logger.warning('notifications: access_request.on_approval_finalized failed', exc_info=True)
