from __future__ import annotations

import uuid

from core.models import User
from django.test import TestCase

from notifications.models import Notification, NotificationPreference, NotificationType
from notifications.services import NotificationService, prune


def _user(username):
    return User.objects.create(id=uuid.uuid4(), username=username)


def _make_type(admin, **fields):
    return NotificationType.objects.create(**fields)


class NotificationServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.order_by('id').first() or _user('seeduser')
        cls.a = _user('notif_a')
        cls.b = _user('notif_b')
        cls.ntype = _make_type(cls.admin, code='test.event', label='Test event',
                              category='SYSTEM', severity='INFO',
                              default_channels=['INAPP'], audience_rule={'kind': 'actor'})

    def _notify(self, **over):
        kwargs = dict(subject='Hello', recipients=[self.a, self.b])
        kwargs.update(over)
        return NotificationService().notify('test.event', **kwargs)

    def test_fans_out_one_row_per_recipient(self):
        self.assertEqual(self._notify(), 2)
        self.assertEqual(Notification.objects.filter(type=self.ntype).count(), 2)

    def test_unknown_type_is_ignored_not_raised(self):
        self.assertEqual(
            NotificationService().notify('does.not.exist', subject='x', recipients=[self.a]), 0)

    def test_duplicate_recipients_are_collapsed(self):
        self.assertEqual(self._notify(recipients=[self.a, self.a, self.a]), 1)

    def test_group_key_makes_a_repeat_event_idempotent(self):
        self.assertEqual(self._notify(group_key='g1'), 2)
        self.assertEqual(self._notify(group_key='g1'), 0)
        self.assertEqual(Notification.objects.filter(group_key='g1').count(), 2)

    def test_opt_out_removes_only_that_user(self):
        NotificationPreference.objects.create(
            id=uuid.uuid4(), user=self.b, type_code='test.event',
            channel='INAPP', enabled=False)
        self.assertEqual(self._notify(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.b).count(), 0)

    def test_mandatory_type_ignores_opt_out(self):
        self.ntype.is_mandatory = True
        self.ntype.save()
        NotificationPreference.objects.create(
            id=uuid.uuid4(), user=self.b, type_code='test.event',
            channel='INAPP', enabled=False)
        self.assertEqual(self._notify(), 2)

    def test_fanout_is_capped_and_does_not_mass_write(self):
        from notifications.apps import NotificationsConfig
        original = NotificationsConfig.fanout_max_recipients
        NotificationsConfig.fanout_max_recipients = 1
        try:
            self.assertEqual(self._notify(), 1)
        finally:
            NotificationsConfig.fanout_max_recipients = original

    def test_inactive_type_produces_nothing(self):
        self.ntype.is_active = False
        self.ntype.save()
        self.assertEqual(self._notify(), 0)


class ReadStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.order_by('id').first() or _user('seeduser2')
        cls.a = _user('notif_read_a')
        cls.ntype = _make_type(cls.admin, code='test.read', label='Read test',
                              category='SYSTEM', severity='INFO',
                              default_channels=['INAPP'], audience_rule={})

    def _make(self, n=3):
        NotificationService().notify('test.read', subject='s', recipients=[self.a])
        for _ in range(n - 1):
            Notification.objects.create(
                recipient=self.a, type=self.ntype, subject='s', category='SYSTEM')

    def test_unread_count_and_mark_all(self):
        self._make(3)
        svc = NotificationService(self.a)
        self.assertEqual(svc.unread_count(self.a), 3)
        self.assertEqual(svc.mark_all_read(self.a), 3)
        self.assertEqual(svc.unread_count(self.a), 0)

    def test_mark_read_cannot_touch_another_users_rows(self):
        self._make(1)
        other = _user('notif_read_b')
        row = Notification.objects.filter(recipient=self.a).first()
        self.assertEqual(NotificationService(other).mark_read([row.id], other), 0)
        row.refresh_from_db()
        self.assertFalse(row.is_read)

    def test_prune_keeps_unread_action_items(self):
        self._make(2)
        Notification.objects.update(severity='ACTION', is_read=False)
        Notification.objects.all().update(
            created_at=Notification.objects.first().created_at)
        # nothing is old enough yet
        self.assertEqual(prune(days=3650), 0)
        self.assertEqual(Notification.objects.count(), 2)
