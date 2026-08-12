"""Resolve the FE route a notification opens. Mapping and rationale: developer guide s.13."""
import logging

from notifications.apps import NotificationsConfig

logger = logging.getLogger(__name__)


def route_for_approval(approval_request):
    try:
        domain = getattr(approval_request, 'domain', None) or getattr(
            getattr(approval_request, 'flow', None), 'domain', None)
        object_id = getattr(approval_request, 'object_id', None)
        routes = getattr(NotificationsConfig, 'domain_routes', {}) or {}

        template = routes.get(domain) if domain else None
        if template and object_id:
            return template.format(id=object_id)

        fallback = getattr(NotificationsConfig, 'fallback_approval_route',
                           '/approval/request/{request_id}')
        return fallback.format(request_id=approval_request.id)
    except Exception:
        logger.warning('notifications: could not resolve route', exc_info=True)
        return ''
