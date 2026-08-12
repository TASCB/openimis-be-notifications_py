from django.core.management.base import BaseCommand

from notifications.services import prune


class Command(BaseCommand):
    help = 'Delete read/informational notifications older than the retention window.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None,
                            help='Override retention_days from module config.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        if opts['dry_run']:
            from datetime import timedelta
            from django.db.models import Q
            from django.utils import timezone
            from notifications.apps import NotificationsConfig
            from notifications.models import Notification
            days = opts['days'] or NotificationsConfig.retention_days
            cutoff = timezone.now() - timedelta(days=int(days))
            n = Notification.objects.filter(created_at__lt=cutoff).filter(
                Q(is_read=True) | Q(severity='INFO')).count()
            self.stdout.write(f'would delete {n} notification(s) older than {days} days')
            return
        deleted = prune(opts['days'])
        self.stdout.write(self.style.SUCCESS(f'deleted {deleted} notification(s)'))
