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


class AccountsWithdrawnAdapterTest(SimpleTestCase):
    def test_one_message_per_district_with_the_reasons(self):
        region = SimpleNamespace(id=1, name='Arusha', type='R')
        meru = SimpleNamespace(id=7, name='Meru', type='D')
        moshi = SimpleNamespace(id=8, name='Moshi', type='D')

        def account(pk, code):
            return SimpleNamespace(id=pk, json_ext={'verification_withdrawn': {'code': code, 'at': 'T1'}})

        accounts = [account(1, 'PROVIDER_MISMATCH'), account(2, 'PROVIDER_MISMATCH'),
                    account(3, 'INVALID_MOBILE'), account(4, 'PROVIDER_MISMATCH')]
        chains = {1: [meru, region], 2: [meru, region], 3: [meru, region], 4: [moshi, region]}
        with mock.patch.object(tasaf_payment, '_district_chains', return_value=chains), \
                mock.patch.object(tasaf_payment, 'NotificationService') as service:
            tasaf_payment.on_accounts_withdrawn(accounts=accounts, user=None)
        calls = {c.kwargs['location_ids'][0]: c for c in service.return_value.notify.call_args_list}
        self.assertEqual(set(calls), {7, 8})
        meru_call = calls[7]
        self.assertEqual(meru_call.args[0], 'case.account.withdrawn')
        self.assertEqual(meru_call.kwargs['subject'], '3 payment account(s) in Meru were not sent to GePG')
        self.assertTrue(meru_call.kwargs['body'].startswith("2 number and provider don't match; 1 invalid mobile number."))
        self.assertEqual(meru_call.kwargs['location_ids'], [7, 1])
        self.assertEqual(meru_call.kwargs['target_route'], '/caseManagement/accountCorrections?reason=WITHDRAWN')
        self.assertEqual(meru_call.kwargs['group_key'], 'gepg.withdrawn:T1:7')
