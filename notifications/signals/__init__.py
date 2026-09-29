"""Service-signal bindings. AFTER only -- see the developer guide, sections 3 and 8."""
import logging

logger = logging.getLogger(__name__)


def bind_service_signals():
    from core.service_signals import ServiceSignalBindType
    from core.signals import bind_service_signal
    from notifications.adapters import (
        access_request, api_etl, approval, case_management, communications)

    bindings = (
        ('api_etl_service.import_finished', api_etl.on_import_finished_signal),
        ('approval_service.request_approval', approval.on_requested),
        ('approval_service.reject', approval.on_rejected),
        ('approval_service.return_for_correction', approval.on_returned),
        ('approval_service.finalized', approval.on_finalized),
        ('approval_service.finalized', access_request.on_approval_finalized),
        ('access_request_service.provision', access_request.on_provisioned),
        ('communications_post_service.publish', communications.on_post_published),
        ('task_service.create', case_management.on_case_task_created),
        ('task_service.complete_task', case_management.on_data_update_task_complete),
        ('case_payment_service.update_details', case_management.on_payment_change),
        ('case_pending_service.decide', case_management.on_pending_decided),
        ('case_household_service.deactivate_household', case_management.on_household_deactivated),
        ('case_followup_service.add', case_management.on_follow_up_added),
        ('case_followup_service.update_status', case_management.on_follow_up_status),
    )
    for name, handler in bindings:
        try:
            bind_service_signal(name, handler, bind_type=ServiceSignalBindType.AFTER)
        except Exception:
            logger.warning('notifications: could not bind %s', name, exc_info=True)
