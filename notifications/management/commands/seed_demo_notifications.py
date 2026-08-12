"""Seed demo notifications for manual testing. Rows carry a ``demo:`` group_key so they can
be purged with --clear-only without touching real notifications."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import User
from notifications.models import Notification, NotificationType

# (type_code, subject, body, target_route, minutes_ago)
SAMPLES = [
    ('approval.step.assigned',
     'Paylist PL-2026-08-KASULU is awaiting your approval',
     'Reference APR-2026-0431 · 1,284 households · TZS 38,520,000',
     '/tasks', 2),
    ('approval.step.assigned',
     'Training request TRN-2026-0087 is awaiting your approval',
     'Reference APR-2026-0430 · Kigoma TOT, 3 days',
     '/tasks', 26),
    ('approval.rejected',
     'Communication activity CA-2026-0112 was rejected',
     'Reason: budget code missing on the activity plan',
     '/approval/requests', 95),
    ('approval.returned',
     'Access request AR-2026-0233 was returned for correction',
     'Reason: attach the signed designation letter',
     '/approval/requests', 190),
    ('approval.finalized',
     'Paylist PL-2026-07-MISSENYI was finalised',
     'Approved by the Executive Director',
     '/approval/requests', 400),
    ('import.completed',
     'Import finished — Tandahimba',
     'inserted: 4,812 · updated: 96 · households: 1,204',
     '/imports', 55),
    ('import.partial',
     'Import finished with skipped rows — Missenyi',
     'inserted: 812 · skipped: 4 (missing surname) · households: 203',
     '/imports', 140),
    ('import.failed',
     'Import failed — Kasulu TC',
     "Questionnaire validation failed: 'DODOSO LA KAYA - RM4-KASULUDC' "
     'targets a different council type',
     '/imports', 320),
    ('account.provisioned',
     'Your TASAF MIS account has been created',
     'A set-password link was sent to your registered email address.',
     '/access-requests', 1440),
    ('account.request_rejected',
     'Access request for J. Mwakalinga was not approved',
     'Reference AR-2026-0229',
     '/access-requests', 2880),
    ('comms.post_published',
     'Your post was published: PSSN Wave 5 field briefing',
     '',
     '/communications/feed', 610),
    ('import.completed',
     'Import finished — Bariadi DC',
     'inserted: 2,140 · updated: 12 · households: 534',
     '/imports', 4320),
]


class Command(BaseCommand):
    help = 'Seed demo notifications for manual testing of the bell and list.'

    def add_arguments(self, parser):
        parser.add_argument('--user', default='Admin',
                            help='Username to receive them (default: Admin)')
        parser.add_argument('--read', type=int, default=3,
                            help='How many of the oldest to mark as already read (default: 3)')
        parser.add_argument('--clear', action='store_true',
                            help='Delete existing demo notifications first')
        parser.add_argument('--clear-only', action='store_true',
                            help='Delete demo notifications and exit')

    def handle(self, *args, **opts):
        user = User.objects.filter(username=opts['user'], validity_to__isnull=True).first()
        if not user:
            self.stderr.write(self.style.ERROR(f"user {opts['user']!r} not found"))
            return

        if opts['clear'] or opts['clear_only']:
            deleted, _ = Notification.objects.filter(
                recipient=user, group_key__startswith='demo:').delete()
            self.stdout.write(f'cleared {deleted} demo notification(s)')
            if opts['clear_only']:
                return

        types = {t.code: t for t in NotificationType.objects.all()}
        missing = {code for code, *_ in SAMPLES} - set(types)
        if missing:
            self.stderr.write(self.style.ERROR(
                f'missing NotificationType rows: {sorted(missing)} — run migrate first'))
            return

        now = timezone.now()
        created = []
        for idx, (code, subject, body, route, mins) in enumerate(SAMPLES):
            group_key = f'demo:{idx}'
            if Notification.objects.filter(recipient=user, group_key=group_key).exists():
                continue
            ntype = types[code]
            created.append(Notification(
                recipient=user, type=ntype,
                category=ntype.category, severity=ntype.severity,
                subject=subject, body=body, target_route=route,
                source_ref=f'demo:{code}:{idx}', group_key=group_key,
            ))
        Notification.objects.bulk_create(created)

        # auto_now_add ignores supplied values, so ages are applied after insert.
        for idx, (code, subject, body, route, mins) in enumerate(SAMPLES):
            Notification.objects.filter(
                recipient=user, group_key=f'demo:{idx}'
            ).update(created_at=now - timedelta(minutes=mins))

        n_read = max(0, int(opts['read']))
        if n_read:
            oldest = list(
                Notification.objects.filter(recipient=user, group_key__startswith='demo:')
                .order_by('created_at').values_list('id', flat=True)[:n_read]
            )
            Notification.objects.filter(id__in=oldest).update(is_read=True, read_at=now)

        unread = Notification.objects.filter(recipient=user, is_read=False).count()
        total = Notification.objects.filter(recipient=user).count()
        self.stdout.write(self.style.SUCCESS(
            f'{user.username}: created {len(created)}, now {unread} unread of {total} total'))
