"""tasaf_payment MUSE events (tasaf_payment.events.muse_event) -> payment roles."""
import logging

from notifications.services import NotificationService

logger = logging.getLogger(__name__)

STATUS_TEXT = {
    'RECEIVED': 'MUSE received',
    'ACCEPTED': 'MUSE accepted',
    'SENT_TO_BANK': 'MUSE sent to the bank',
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
    elif event == 'unapplied':
        service.notify('payment.muse.unapplied', subject=f'Payments on {label} came back unapplied',
                       body=f'First reason: {description}' if description else '',
                       group_key=f'{key}:UNAPPLIED', **common)
    elif event == 'closed':
        counts = _counts(paylist)
        service.notify('payment.muse.closed', subject=f'{label} closed',
                       body=f"{counts.get('PROCESSED', 0)} paid, {counts.get('UNAPPLIED', 0)} unapplied",
                       group_key=f'{key}:CLOSED', **common)
