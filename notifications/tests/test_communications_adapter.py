from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from notifications.adapters import communications

MAKER = SimpleNamespace(id='maker', username='maker')
CHECKER = SimpleNamespace(id='checker', username='checker')


def _activity(**kw):
    return SimpleNamespace(**{'id': 'a-1', 'title': 'Press briefing', 'code': 'COM1', 'activity_type': 'EVENT',
                              'user_created': MAKER, 'user_created_id': MAKER.id, 'json_ext': {}, **kw})


class ActivityTransitionTest(SimpleTestCase):
    def _run(self, action, actor, activity=None, success=True):
        objects = mock.MagicMock()
        objects.filter.return_value.select_related.return_value.first.return_value = activity or _activity()
        with mock.patch('communications.models.CommunicationActivity.objects', objects), \
                mock.patch('notifications.audience._users_with_right', return_value=[MAKER, CHECKER]), \
                mock.patch.object(communications, '_close_submitted_notices') as close, \
                mock.patch.object(communications, 'notify_on_commit') as notify:
            communications.on_activity_transition(
                cls_=SimpleNamespace(user=actor), data=[('a-1', action), {}], result={'success': success})
        return notify, close

    def test_submit_tells_the_approvers_but_not_the_maker(self):
        notify, _ = self._run('submit', MAKER)
        kwargs = notify.call_args.kwargs
        self.assertEqual(kwargs['type_code'], 'comms.activity.submitted')
        self.assertEqual(kwargs['recipients'], [CHECKER])
        self.assertEqual(kwargs['subject'], 'Press briefing is awaiting your approval')
        self.assertEqual(kwargs['target_route'], '/communications/events/event/a-1')

    def test_reject_tells_the_maker_why_and_closes_the_waiting_notice(self):
        notify, close = self._run('reject', CHECKER, _activity(activity_type='PRESS_RELEASE',
                                                               json_ext={'reject_reason': 'Add the budget'}))
        close.assert_called_once_with('a-1')
        kwargs = notify.call_args.kwargs
        self.assertEqual((kwargs['recipients'], kwargs['subject'], kwargs['body']),
                         ([MAKER], 'Press briefing was rejected', 'Add the budget'))
        self.assertEqual(kwargs['target_route'], '/communications/activities/activity/a-1')

    def test_failed_or_other_transitions_send_nothing(self):
        self._run('submit', MAKER, success=False)[0].assert_not_called()
        self._run('schedule', MAKER)[0].assert_not_called()


class PostPublishedTest(SimpleTestCase):
    def _run(self, publisher):
        post = SimpleNamespace(id='p-1', title='Notice', user_created=MAKER)
        objects = mock.MagicMock()
        objects.filter.return_value.select_related.return_value.first.return_value = post
        with mock.patch('communications.models.CommunicationPost.objects', objects), \
                mock.patch.object(communications, 'notify_on_commit') as notify:
            communications.on_post_published(
                cls_=SimpleNamespace(user=publisher),
                result={'success': True, 'data': {'id': 'p-1', 'is_published': True}})
        return notify

    def test_the_author_is_told_not_the_publisher(self):
        self.assertEqual(self._run(CHECKER).call_args.kwargs['recipients'], [MAKER])

    def test_no_notice_when_the_author_publishes(self):
        self._run(MAKER).assert_not_called()
