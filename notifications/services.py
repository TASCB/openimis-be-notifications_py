"""Notification service — fan-out, read state, pruning."""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from notifications import channels as channel_registry
from notifications.apps import NotificationsConfig
from notifications.audience import resolve as resolve_audience
from notifications.models import Notification, NotificationPreference, NotificationType

logger = logging.getLogger(__name__)


class NotificationService:
    """Creates notifications. Callers are event adapters, never domain modules directly."""

    def __init__(self, user=None):
        self.user = user

    # ------------------------------------------------------------------ create
    def notify(self, type_code, *, subject, body='', target_route='', source_ref='',
               group_key='', actor=None, subject_user=None, location_ids=None,
               recipients=None):
        """Fan an event out to its audience. Returns rows written; never raises."""
        try:
            return self._notify(
                type_code, subject=subject, body=body, target_route=target_route,
                source_ref=source_ref, group_key=group_key, actor=actor,
                subject_user=subject_user, location_ids=location_ids, recipients=recipients,
            )
        except Exception:
            logger.error('notifications: notify(%s) failed', type_code, exc_info=True)
            return 0

    def _notify(self, type_code, *, subject, body, target_route, source_ref, group_key,
                actor, subject_user, location_ids, recipients):
        ntype = NotificationType.objects.filter(code=type_code, is_active=True).first()
        if not ntype:
            logger.warning('notifications: unknown or inactive type %r', type_code)
            return 0

        if recipients is None:
            recipients = resolve_audience(
                ntype.audience_rule,
                {'actor': actor, 'subject': subject_user, 'location_ids': location_ids or []},
            )

        recipients = self._dedupe(recipients)
        if not recipients:
            return 0

        cap = int(getattr(NotificationsConfig, 'fanout_max_recipients', 500) or 500)
        if len(recipients) > cap:
            logger.error(
                'notifications: type %s resolved %s recipients, capped at %s — check its audience_rule',
                type_code, len(recipients), cap,
            )
            recipients = recipients[:cap]

        recipients = self._apply_preferences(ntype, recipients)
        if not recipients:
            return 0

        recipients = self._drop_already_sent(group_key, recipients)
        if not recipients:
            return 0

        rows = [
            Notification(
                recipient=user,
                type=ntype,
                category=ntype.category,
                severity=ntype.severity,
                subject=subject[:255],
                body=body or '',
                target_route=target_route or '',
                source_ref=source_ref or '',
                group_key=group_key or '',
            )
            for user in recipients
        ]
        Notification.objects.bulk_create(rows, batch_size=500)

        self._dispatch_external(ntype, rows)
        return len(rows)

    @staticmethod
    def _dedupe(recipients):
        seen, out = set(), []
        for user in recipients or []:
            if user is not None and user.id not in seen:
                seen.add(user.id)
                out.append(user)
        return out

    @staticmethod
    def _apply_preferences(ntype, recipients):
        """Opt-out: only an explicit disabled row removes someone."""
        if ntype.is_mandatory:
            return recipients
        opted_out = set(
            NotificationPreference.objects.filter(
                user_id__in=[u.id for u in recipients],
                type_code=ntype.code,
                channel='INAPP',
                enabled=False,
            ).values_list('user_id', flat=True)
        )
        if not opted_out:
            return recipients
        return [u for u in recipients if u.id not in opted_out]

    @staticmethod
    def _drop_already_sent(group_key, recipients):
        """Idempotency guard for a re-fired event."""
        if not group_key:
            return recipients
        already = set(
            Notification.objects.filter(
                group_key=group_key, recipient_id__in=[u.id for u in recipients]
            ).values_list('recipient_id', flat=True)
        )
        if not already:
            return recipients
        return [u for u in recipients if u.id not in already]

    def _dispatch_external(self, ntype, rows):
        """Hand off to every enabled non-in-app channel. No-op until EMAIL/SMS are
        registered -- see the developer guide, section 5."""
        enabled = set(getattr(NotificationsConfig, 'channels_enabled', ['INAPP']) or ['INAPP'])
        for code in ntype.default_channels or []:
            if code == 'INAPP' or code not in enabled:
                continue
            channel = channel_registry.get(code)
            if channel is None or not channel.is_available():
                logger.info(
                    'notifications: channel %s unavailable — %s notification(s) not delivered on it',
                    code, len(rows),
                )
                continue
            for row in rows:
                address = channel.address_for(row.recipient)
                if not address:
                    continue
                try:
                    channel.send(row, address)
                except Exception:
                    logger.warning('notifications: channel %s failed for %s', code, row.id, exc_info=True)

    # -------------------------------------------------------------- read state
    def mark_read(self, notification_ids, user):
        return Notification.objects.filter(
            id__in=notification_ids, recipient=user, is_read=False
        ).update(is_read=True, read_at=timezone.now())

    def mark_all_read(self, user):
        return Notification.objects.filter(recipient=user, is_read=False).update(
            is_read=True, read_at=timezone.now()
        )

    def unread_count(self, user):
        return Notification.objects.filter(recipient=user, is_read=False).count()


def notify_on_commit(**kwargs):
    """Queue a notification for after the caller's transaction commits. Why this matters is
    in the developer guide, section 3."""
    type_code = kwargs.pop('type_code')
    transaction.on_commit(lambda: NotificationService().notify(type_code, **kwargs))


def prune(days=None):
    """Delete read/informational notifications older than the retention window."""
    days = int(days if days is not None else getattr(NotificationsConfig, 'retention_days', 90) or 90)
    cutoff = timezone.now() - timedelta(days=days)
    qs = Notification.objects.filter(created_at__lt=cutoff).filter(
        Q(is_read=True) | Q(severity='INFO')
    )
    count = qs.count()
    qs.delete()
    return count
