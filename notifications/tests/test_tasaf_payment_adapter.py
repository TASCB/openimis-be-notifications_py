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
