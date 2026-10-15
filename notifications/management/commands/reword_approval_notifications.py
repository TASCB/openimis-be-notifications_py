import uuid

from django.core.management.base import BaseCommand


def _is_uuid(value):
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def reworded(notification, request):
    from notifications.adapters.approval import _body, _cancel_reason, _describe

    code = notification.type.code
    title, flow = _describe(request)
    summary = request.summary or {}
    if code == 'approval.step.assigned':
        return f'{title} is awaiting your approval', _body(request, flow)
    if code == 'approval.rejected':
        return f'{title} was rejected', _body(request, flow)
    if code == 'approval.returned':
        return f'{title} was returned for correction', _body(request, flow)
    if code == 'approval.finalized':
        status = str(request.status).upper()
        if status == 'CANCELLED':
            return f'{title} was cancelled', _body(request, flow, _cancel_reason(request))
        if status == 'REJECTED':
            return f'{title} was rejected', _body(request, flow)
        return f'{title} was approved', _body(request, flow)
    if code in ('account.ready_to_provision', 'account.request_rejected'):
        who = f" for {summary['full_name']}" if summary.get('full_name') else ''
        body = f"Ref {summary['reference_code']}" if summary.get('reference_code') else ''
        if code == 'account.ready_to_provision':
            return f'Access request{who} is approved and awaiting provisioning', body
        return f'Access request{who} was not approved', body
    return None


class Command(BaseCommand):
    help = ("Rewrite the subject and body of stored approval and access-request notifications in the "
            "current wording (item name, outcome, real reference). Dry run unless --apply.")

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        from approval.models import ApprovalRequest
        from notifications.models import Notification

        rows = (Notification.objects.select_related('type')
                .filter(source_ref__regex=r'^(approval|access_request):'))
        ids = {n.source_ref.split(':', 1)[1] for n in rows}
        requests = {str(r.id): r for r in ApprovalRequest.objects.select_related('flow').filter(
            id__in=[i for i in ids if _is_uuid(i)])}
        changed, missing = [], 0
        for n in rows:
            request = requests.get(n.source_ref.split(':', 1)[1])
            if request is None:
                missing += 1
                continue
            new = reworded(n, request)
            if new and (new[0][:255], new[1]) != (n.subject, n.body or ''):
                changed.append((n, new[0][:255], new[1]))

        for n, subject, body in changed[:5]:
            self.stdout.write(f'  {n.subject}  ->  {subject}  |  {body}')
        self.stdout.write(f'{len(changed)} to rewrite, {missing} whose request no longer exists.')
        if not options['apply']:
            self.stdout.write(self.style.WARNING('Dry run: nothing was changed. Add --apply to rewrite them.'))
            return
        for n, subject, body in changed:
            n.subject, n.body = subject, body
        Notification.objects.bulk_update([n for n, _, _ in changed], ['subject', 'body'], batch_size=500)
        self.stdout.write(self.style.SUCCESS(f'Rewrote {len(changed)} notification(s).'))
