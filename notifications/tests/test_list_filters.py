import uuid

from core.models import User
from django.test import TestCase

from notifications.models import Notification, NotificationType
from notifications.schema import narrow_notifications


class ListFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(id=uuid.uuid4(), username='notif_filter_user')
        for code in ('case.test_filter', 'approval.test_filter', 'casefile.test_filter'):
            NotificationType.objects.create(code=code, label=code, category='SYSTEM', severity='INFO',
                                            default_channels=['INAPP'], audience_rule={})
        make = lambda code, subject, body='': Notification.objects.create(
            recipient=cls.user, type=NotificationType.objects.get(code=code), subject=subject, body=body, category='SYSTEM')
        make('case.test_filter', 'Equity Bank account for household P3-020109102-03763487 failed verification')
        make('approval.test_filter', 'Paylist approval was finalised', 'Reference PL-2026-0042')
        make('casefile.test_filter', 'Not a case notification')

    def _subjects(self, **kwargs):
        qs = narrow_notifications(Notification.objects.filter(recipient=self.user), **kwargs)
        return sorted(n.subject for n in qs)

    def test_module_matches_the_type_prefix_only(self):
        self.assertEqual(self._subjects(module='case'),
                         ['Equity Bank account for household P3-020109102-03763487 failed verification'])

    def test_search_looks_in_subject_and_body_ignoring_case(self):
        self.assertEqual(len(self._subjects(search='03763487')), 1)
        self.assertEqual(self._subjects(search='pl-2026'), ['Paylist approval was finalised'])

    def test_filters_combine_and_blank_means_all(self):
        self.assertEqual(self._subjects(module='approval', search='equity'), [])
        self.assertEqual(len(self._subjects(module='', search='  ')), 3)
