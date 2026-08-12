"""Communications adapter: post published.

The dispatch_channel stub (marks SENT without sending) is re-pointed in Phase 6, once a real
EMAIL channel exists.
"""
import logging

from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)


def on_post_published(**kwargs):
    try:
        result = kwargs.get('result') or {}
        payload = result.get('data') if isinstance(result, dict) else None
        if not isinstance(payload, dict):
            return
        post_id = payload.get('id')
        cls_ = kwargs.get('cls_')
        author = getattr(cls_, 'user', None)
        if not post_id or not author:
            return
        notify_on_commit(
            type_code='comms.post_published',
            subject=f"Your post was published{': ' + payload['title'] if payload.get('title') else ''}",
            target_route='/communications/feed',
            source_ref=f'communications:{post_id}',
            group_key=f'comms.post_published:{post_id}',
            subject_user=author, recipients=[author],
        )
    except Exception:
        logger.warning('notifications: communications.on_post_published failed', exc_info=True)
