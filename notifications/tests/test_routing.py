from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from notifications import routing


class ApprovalRouteTest(SimpleTestCase):
    def _request(self, domain):
        return SimpleNamespace(id='req-1', object_id='obj-9', summary={}, flow=SimpleNamespace(domain=domain))

    def _routes(self):
        return mock.patch.multiple(
            routing.NotificationsConfig,
            domain_routes={'training.Training': '/trainings/training/{id}',
                           'tasaf_payment.Paylist': '/tasafPayment/paylist/{id}'},
            approver_routes={'training.Training': '/approval/request/{request_id}'},
        )

    def test_a_training_approver_is_sent_to_the_approval_request(self):
        with self._routes():
            route = routing.route_for_approval(self._request('training.Training'), for_approver=True)
        self.assertEqual(route, '/approval/request/req-1')

    def test_the_training_officer_is_sent_to_the_training(self):
        with self._routes():
            route = routing.route_for_approval(self._request('training.Training'))
        self.assertEqual(route, '/trainings/training/obj-9')

    def test_other_domains_keep_their_record_route_for_approvers(self):
        with self._routes():
            route = routing.route_for_approval(self._request('tasaf_payment.Paylist'), for_approver=True)
        self.assertEqual(route, '/tasafPayment/paylist/obj-9')
