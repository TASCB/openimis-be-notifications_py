from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from notifications.adapters import approval


class ApprovalWordingTest(SimpleTestCase):
    def _finalize(self, decision, summary):
        request = SimpleNamespace(
            id='r-1', summary=summary, requested_by='owner', flow=SimpleNamespace(name='Payment / paylist approval', code='PAYMENT_APPROVAL'))
        objects = mock.MagicMock()
        objects.filter.return_value.select_related.return_value.first.return_value = request
        with mock.patch('approval.models.ApprovalRequest.objects', objects), \
                mock.patch.object(approval, 'notify_on_commit') as notify, \
                mock.patch.object(approval, '_close_step_notices'), \
                mock.patch.object(approval, 'route_for_approval', return_value='/x'):
            approval.on_finalized(result={'success': True, 'data': {'id': 'r-1', 'decision': decision}}, data=[(), {}])
        return notify

    def test_an_approved_paylist_names_itself_and_says_approved(self):
        notify = self._finalize('APPROVED', {'title': 'Moshi MNO test #1 · Mobile money'})
        kwargs = notify.call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Moshi MNO test #1 · Mobile money was approved')
        self.assertEqual(kwargs['body'], 'Payment / paylist approval')
        self.assertNotIn('r-1', kwargs['body'])

    def test_a_cancellation_says_cancelled_and_why(self):
        kwargs = self._finalize('CANCELLED', {'title': 'Moshi MNO test #1', 'cancel_reason': 'Test removed'}).call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Moshi MNO test #1 was cancelled')
        self.assertEqual(kwargs['body'], 'Payment / paylist approval · Reason: Test removed')

    def test_a_rejection_is_left_to_the_rejection_notice(self):
        self._finalize('REJECTED', {'title': 'X'}).assert_not_called()

    def test_an_access_request_names_the_applicant_and_its_reference(self):
        kwargs = self._finalize('APPROVED', {'full_name': 'Asha Juma', 'reference_code': 'AR-2026-0012'}).call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Account for Asha Juma was approved')
        self.assertEqual(kwargs['body'], 'Payment / paylist approval · Ref AR-2026-0012')

    def test_without_a_summary_the_flow_name_is_used(self):
        kwargs = self._finalize('APPROVED', {}).call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Payment / paylist approval was approved')


class AccessRequestWordingTest(SimpleTestCase):
    def _finalize(self, status):
        from notifications.adapters import access_request
        request = SimpleNamespace(
            id='r-9', status=status, summary={'full_name': 'Asha Juma', 'reference_code': 'AR-2026-0012'},
            flow=SimpleNamespace(code=access_request.FLOW_CODE))
        objects = mock.MagicMock()
        objects.filter.return_value.select_related.return_value.first.return_value = request
        with mock.patch('approval.models.ApprovalRequest.objects', objects), \
                mock.patch.object(access_request, 'notify_on_commit') as notify, \
                mock.patch.object(access_request, 'route_for_approval', return_value='/x'):
            access_request.on_approval_finalized(result={'data': {'id': 'r-9'}})
        return notify.call_args.kwargs

    def test_approved_names_the_applicant_and_the_reference(self):
        kwargs = self._finalize('APPROVED')
        self.assertEqual(kwargs['subject'], 'Access request for Asha Juma is approved and awaiting provisioning')
        self.assertEqual(kwargs['body'], 'Ref AR-2026-0012')

    def test_not_approved_never_shows_the_request_id(self):
        kwargs = self._finalize('REJECTED')
        self.assertEqual(kwargs['subject'], 'Access request for Asha Juma was not approved')
        self.assertNotIn('r-9', kwargs['body'])


class ApprovalNoticeLifecycleTest(SimpleTestCase):
    def test_a_decided_request_closes_its_waiting_notices(self):
        with mock.patch.object(approval, '_close_step_notices') as close, \
                mock.patch.object(approval, '_notify_subject'):
            approval.on_finalized(result={'success': True, 'data': {'id': 'r-1', 'decision': 'APPROVED'}}, data=[(), {}])
        close.assert_called_once_with('r-1')

    def test_a_step_approved_mid_flow_notifies_the_next_step(self):
        with mock.patch.object(approval, '_notify_current_step') as notify:
            approval.on_approved(result={'success': True, 'data': {'id': 'r-1', 'status': 'PENDING'}}, data=[(), {}])
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], 'r-1')

    def test_the_last_approval_is_left_to_finalized(self):
        with mock.patch.object(approval, '_notify_current_step') as notify:
            approval.on_approved(result={'success': True, 'data': {'id': 'r-1', 'status': 'APPROVED'}}, data=[(), {}])
        notify.assert_not_called()
