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


UNAPPLIED_ROUTE = '/tasafPayment/returnFeedback'


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
        service.notify('payment.muse.unapplied',
                       subject=f'Payments on {label} came back unapplied; repay, send to Case or withdraw them',
                       body=f'First reason: {description}' if description else '',
                       group_key=f'{key}:UNAPPLIED',
                       **{**common, 'target_route': UNAPPLIED_ROUTE})
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


WITHDRAWN_ROUTE = '/caseManagement/accountCorrections?reason=WITHDRAWN'
WITHDRAWN_TEXT = {
    'PROVIDER_MISMATCH': "number and provider don't match",
    'INVALID_MOBILE': 'invalid mobile number',
}


def _district_chains(accounts):
    from location.models import Location
    from tasaf_payment.models import PaymentAccount

    located = dict(PaymentAccount.objects.filter(id__in=[a.id for a in accounts])
                   .values_list('id', 'group_beneficiary__group__location_id'))
    locations = Location.objects.filter(id__in={i for i in located.values() if i}).select_related(
        'parent__parent__parent')
    chains = {}
    for location in locations:
        chain, node = [], location
        while node is not None and len(chain) < 10:
            chain.append(node)
            node = node.parent
        district = next((n for n in chain if n.type == 'D'), chain[-1])
        chains[location.id] = chain[chain.index(district):]
    return {account_id: chains.get(location_id) for account_id, location_id in located.items()}


def on_accounts_withdrawn(sender=None, accounts=None, user=None, **kwargs):
    from collections import Counter

    if not accounts:
        return
    by_district, chains = {}, _district_chains(accounts)
    for account in accounts:
        chain = chains.get(account.id)
        by_district.setdefault(chain[0].id if chain else None, (chain, []))[1].append(account)
    for district_id, (chain, members) in by_district.items():
        marker = (members[0].json_ext or {}).get('verification_withdrawn') or {}
        reasons = Counter(((a.json_ext or {}).get('verification_withdrawn') or {}).get('code') for a in members)
        where = f' in {chain[0].name}' if chain else ''
        NotificationService().notify(
            'case.account.withdrawn',
            subject=f'{len(members)} payment account(s){where} were not sent to GePG',
            body='; '.join(f'{n} {WITHDRAWN_TEXT.get(code, code or "other")}' for code, n in reasons.most_common())
                 + '. Correct them in Case Management ▸ Accounts to correct.',
            target_route=WITHDRAWN_ROUTE,
            group_key=f'gepg.withdrawn:{marker.get("at", "")}:{district_id or "-"}',
            actor=user,
            location_ids=[n.id for n in chain] if chain else [],
        )


GEPG_REQUESTS_ROUTE = '/tasafPayment/workspace?tab=verification&verification=gepg'
DECISION_TEXT = (('VERIFIED', 'verified'), ('FAILED', 'failed'), ('MANUAL', 'need review'))


def on_gepg_answered(sender=None, request=None, counts=None, **kwargs):
    if request is None:
        return
    counts = counts or {}
    parts = [f'{counts.get(code, 0)} {text}' for code, text in DECISION_TEXT]
    if counts.get('UNCHECKED'):
        parts.append(f"{counts['UNCHECKED']} not checked (provider did not answer)")
    waiting = counts.get('PENDING', 0)
    NotificationService().notify(
        'payment.gepg.answered',
        subject=f'GePG answered {request.acc_verif_id} ({request.fsp_code}): ' + ', '.join(parts),
        body=f'{waiting} account(s) still waiting for an answer.' if waiting else '',
        target_route=GEPG_REQUESTS_ROUTE,
        source_ref=request.acc_verif_id,
        group_key=f'gepg.answered:{request.acc_verif_id}:{sum(counts.values()) - waiting}',
    )


def on_gepg_unanswered(sender=None, request=None, minutes=None, **kwargs):
    if request is None:
        return
    NotificationService().notify(
        'payment.gepg.unanswered',
        subject=f'GePG has not answered {request.acc_verif_id} ({request.fsp_code}) after {minutes} minutes',
        body=f'{request.item_count} account(s) are waiting. Give GePG the request ID '
             f'{request.esb_request_id or request.acc_verif_id} to trace it.',
        target_route=GEPG_REQUESTS_ROUTE,
        source_ref=request.acc_verif_id,
        group_key=f'gepg.unanswered:{request.acc_verif_id}',
    )
