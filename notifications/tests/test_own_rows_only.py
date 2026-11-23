from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from notifications.schema import NotificationGQLType, NotificationPreferenceGQLType


class OwnRowsOnlyTest(SimpleTestCase):
    def info(self, user):
        return SimpleNamespace(context=SimpleNamespace(user=user))

    def test_notifications_are_limited_to_the_recipient(self):
        user, qs = SimpleNamespace(is_anonymous=False), mock.Mock()
        NotificationGQLType.get_queryset(qs, self.info(user))
        qs.filter.assert_called_once_with(recipient=user)

    def test_preferences_are_limited_to_their_owner(self):
        user, qs = SimpleNamespace(is_anonymous=False), mock.Mock()
        NotificationPreferenceGQLType.get_queryset(qs, self.info(user))
        qs.filter.assert_called_once_with(user=user)

    def test_anonymous_sees_nothing(self):
        qs = mock.Mock()
        NotificationGQLType.get_queryset(qs, self.info(SimpleNamespace(is_anonymous=True)))
        qs.none.assert_called_once_with()
        qs.filter.assert_not_called()
