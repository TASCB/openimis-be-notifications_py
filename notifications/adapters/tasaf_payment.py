"""tasaf_payment MUSE events (tasaf_payment.events.muse_event) -> payment roles."""
import logging

from notifications.services import NotificationService

logger = logging.getLogger(__name__)

STATUS_TEXT = {
    'RECEIVED': 'MUSE received',
    'ACCEPTED': 'MUSE accepted',
    'SENT_TO_BANK': 'MUSE sent to the bank / MNO',
    'ACCEPTED_BY_BANK': 'Bank / MNO accepted',
    'PROCESSED_BY_BANK': 'Bank / MNO processed',
}


def _label(paylist):
    return paylist.muse_batch_reference or f'paylist {str(paylist.uuid)[:8]}'


def _counts(paylist):
    from django.db.models import Count
    rows = paylist.items.filter(is_deleted=False).values('status').annotate(n=Count('id'))
    return {r['status']: r['n'] for r in rows}


def on_muse_event(sender=None, paylist=None, event=None, status=None, description=None, **kwargs):
    if paylist is None:
        return
    status = str(status or '')
    label = _label(paylist)
    key = f'tasaf.muse:{paylist.uuid}:{paylist.muse_msg_id or ""}'
    common = {'target_route': f'/tasafPayment/paylist/{paylist.uuid}', 'source_ref': str(paylist.uuid)}
    service = NotificationService()

    if event == 'batch_status' and status == 'REJECTED':
        service.notify('payment.muse.batch_rejected', subject=f'MUSE rejected {label}',
                       body=description or '', group_key=f'{key}:REJECTED', **common)
    elif event == 'batch_status' and status in STATUS_TEXT:
        service.notify('payment.muse.batch_status', subject=f'{STATUS_TEXT[status]} {label}',
                       body=description or '', group_key=f'{key}:{status}', **common)
    elif event == 'payees_withdrawn':
        withdrawn, kept, review = (int(kwargs.get(k) or 0) for k in ('withdrawn', 'kept', 'needs_review'))
        service.notify('payment.muse.batch_rejected',
                       subject=f'{label}: {withdrawn} payee(s) moved to Case Management',
                       body=(f'{kept} kept for the resend, {review} need review. '
                             f'Resend the rest from the paylist page.'),
                       group_key=f'{key}:WITHDRAWN', **common)
    elif event == 'withdrawn_lapsed':
        service.notify('payment.muse.batch_rejected',
                       subject=f'{label}: {int(kwargs.get("lapsed") or 0)} returned payee(s) not re-paid by the cycle cut-off',
                       body='They are left unpaid; the payroll goes on to reconciliation.',
                       group_key=f'{key}:LAPSED', **common)
    elif event == 'unapplied':
        service.notify('payment.muse.unapplied', subject=f'Payments on {label} came back unapplied; sent to Case Management for correction',
                       body=f'First reason: {description}' if description else '',
                       group_key=f'{key}:UNAPPLIED', **common)
    elif event == 'closed':
        counts = _counts(paylist)
        service.notify('payment.muse.closed', subject=f'{label} closed',
                       body=f"{counts.get('PROCESSED', 0)} paid, {counts.get('UNAPPLIED', 0)} unapplied",
                       group_key=f'{key}:CLOSED', **common)


def on_verification_event(sender=None, account=None, status=None, failure_reason=None, **kwargs):
    from tasaf_payment.models import VerificationStatus
    from notifications.adapters.case_management import HOUSEHOLD_ROUTE, _location_ids

    if account is None:
        return
    group = getattr(getattr(account, 'group_beneficiary', None), 'group', None)
    household = f'household {group.code}' if group is not None else 'a household'
    outcome = {
        VerificationStatus.VERIFIED: 'verified',
        VerificationStatus.FAILED: 'failed verification',
        VerificationStatus.MANUAL: 'needs an HQ review of the name',
    }.get(status, 'came back from verification')
    NotificationService().notify(
        'case.payment_account.verified',
        subject=f'{account.fsp_name} account for {household} {outcome}',
        body='' if status == VerificationStatus.VERIFIED else (failure_reason or ''),
        target_route=HOUSEHOLD_ROUTE.format(id=group.id if group is not None else ''),
        source_ref=str(account.uuid),
        group_key=f'case.verify:{account.uuid}:{(account.json_ext or {}).get("verification_sent", {}).get("sent_at", "")}',
        location_ids=_location_ids(group),
    )
