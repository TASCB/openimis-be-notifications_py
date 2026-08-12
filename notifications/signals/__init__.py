"""Service-signal bindings. AFTER only -- see the developer guide, sections 3 and 8."""
import logging

logger = logging.getLogger(__name__)


def bind_service_signals():
    from core.service_signals import ServiceSignalBindType
    from core.signals import bind_service_signal
    from notifications.adapters import access_request, approval, communications

    bindings = (
        ('approval_service.request_approval', approval.on_requested),
        ('approval_service.reject', approval.on_rejected),
        ('approval_service.return_for_correction', approval.on_returned),
        ('approval_service.finalized', approval.on_finalized),
        ('approval_service.finalized', access_request.on_approval_finalized),
        ('communications_post_service.publish', communications.on_post_published),
    )
    for name, handler in bindings:
        try:
            bind_service_signal(name, handler, bind_type=ServiceSignalBindType.AFTER)
        except Exception:
            logger.warning('notifications: could not bind %s', name, exc_info=True)
