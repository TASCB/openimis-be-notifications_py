from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from notifications.adapters import tasaf_payment


class MuseEventAdapterTest(SimpleTestCase):
    def test_withdrawn_payees_reuse_the_rejection_type(self):
        paylist = SimpleNamespace(uuid='p-1', muse_msg_id='TMAC4FA5E22D9A01',
                                  muse_batch_reference='TP261009-AC4FA5E2')
        with mock.patch.object(tasaf_payment, 'NotificationService') as service:
            tasaf_payment.on_muse_event(paylist=paylist, event='payees_withdrawn',
                                        withdrawn=4, kept=1, needs_review=0, description='x')
        code = service.return_value.notify.call_args.args[0]
        kwargs = service.return_value.notify.call_args.kwargs
        self.assertEqual(code, 'payment.muse.batch_rejected')
        self.assertEqual(kwargs['subject'], 'TP261009-AC4FA5E2: 4 payee(s) moved to Case Management')
        self.assertIn('1 kept for the resend, 0 need review', kwargs['body'])
        self.assertTrue(kwargs['group_key'].endswith(':WITHDRAWN'))


class VerificationEventAdapterTest(SimpleTestCase):
    def _notify(self, status, reason=None):
        district = SimpleNamespace(id=7, parent=None)
        village = SimpleNamespace(id=9, parent=district)
        group = SimpleNamespace(id='g-1', code='P3-020109102-03763487', location=village)
        account = SimpleNamespace(uuid='a-1', fsp_name='Equity Bank', group_beneficiary=SimpleNamespace(group=group),
                                  json_ext={'verification_sent': {'sent_at': 'T1', 'after_change': True}})
        with mock.patch.object(tasaf_payment, 'NotificationService') as service:
            tasaf_payment.on_verification_event(account=account, status=status, failure_reason=reason)
        return service.return_value.notify.call_args

    def test_officers_of_the_district_hear_a_failure_and_why(self):
        from tasaf_payment.models import VerificationStatus
        call = self._notify(VerificationStatus.FAILED, 'Account closed')
        self.assertEqual(call.args[0], 'case.payment_account.verified')
        self.assertEqual(call.kwargs['subject'], 'Equity Bank account for household P3-020109102-03763487 failed verification')
        self.assertEqual(call.kwargs['body'], 'Account closed')
        self.assertEqual(call.kwargs['location_ids'], [9, 7])
        self.assertEqual(call.kwargs['target_route'], '/groups/group/g-1')

    def test_a_verified_account_carries_no_reason(self):
        from tasaf_payment.models import VerificationStatus
        call = self._notify(VerificationStatus.VERIFIED, 'stale text')
        self.assertTrue(call.kwargs['subject'].endswith(' verified'))
        self.assertEqual(call.kwargs['body'], '')
