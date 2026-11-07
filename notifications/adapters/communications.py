"""Communications adapter: activity approval (submit / approve / reject) and post published.

The dispatch_channel stub (marks SENT without sending) is re-pointed in Phase 6, once a real
EMAIL channel exists.
"""
import logging

from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)

ACTIVITY_SUBMITTED = 'comms.activity.submitted'
ACTIVITY_DECIDED = 'comms.activity.decided'
APPROVE_RIGHT = 220110


def _activity_route(activity):
    kind = 'events/event' if activity.activity_type == 'EVENT' else 'activities/activity'
    return f'/communications/{kind}/{activity.id}'


def _close_submitted_notices(activity_id):
    from django.utils import timezone
    from notifications.models import Notification
    Notification.objects.filter(
        group_key=f'{ACTIVITY_SUBMITTED}:{activity_id}', is_read=False,
    ).update(is_read=True, read_at=timezone.now())


def on_activity_transition(**kwargs):
    """``communications_activity_service.transition``: tell approvers on submit, the creator on a decision."""
    try:
        result = kwargs.get('result') or {}
        if not isinstance(result, dict) or not result.get('success'):
            return
        data = kwargs.get('data') or []
        args = data[0] if len(data) > 0 else ()
        kwds = (data[1] if len(data) > 1 else {}) or {}
        activity_id = args[0] if len(args) > 0 else kwds.get('activity_id')
        action = args[1] if len(args) > 1 else kwds.get('action')
        if action not in ('submit', 'approve', 'reject') or not activity_id:
            return

        from communications.models import CommunicationActivity
        activity = CommunicationActivity.objects.filter(id=activity_id).select_related('user_created').first()
        if not activity:
            return
        actor = getattr(kwargs.get('cls_'), 'user', None)
        title = activity.title or activity.code or 'Activity'

        if action == 'submit':
            from notifications.audience import _users_with_right
            creator_id = activity.user_created_id
            recipients = [u for u in _users_with_right(APPROVE_RIGHT) if u.id != creator_id]
            notify_on_commit(
                type_code=ACTIVITY_SUBMITTED,
                subject=f'{title} is awaiting your approval',
                body=activity.code or '',
                target_route=_activity_route(activity),
                source_ref=f'communications.activity:{activity.id}',
                group_key=f'{ACTIVITY_SUBMITTED}:{activity.id}',
                actor=actor, recipients=recipients,
            )
            return

        _close_submitted_notices(activity.id)
        author = activity.user_created
        if not author or author == actor:
            return
        if action == 'approve':
            subject, body = f'{title} was approved', activity.code or ''
        else:
            subject = f'{title} was rejected'
            body = (activity.json_ext or {}).get('reject_reason') or ''
        notify_on_commit(
            type_code=ACTIVITY_DECIDED,
            subject=subject, body=body,
            target_route=_activity_route(activity),
            source_ref=f'communications.activity:{activity.id}',
            group_key=f'{ACTIVITY_DECIDED}:{activity.id}:{action}',
            actor=actor, subject_user=author, recipients=[author],
        )
    except Exception:
        logger.warning('notifications: communications.on_activity_transition failed', exc_info=True)


def on_post_published(**kwargs):
    """Tell the post's author, not the person who pressed Publish."""
    try:
        result = kwargs.get('result') or {}
        payload = result.get('data') if isinstance(result, dict) else None
        if not isinstance(payload, dict) or not payload.get('is_published'):
            return
        post_id = payload.get('id')
        if not post_id:
            return
        from communications.models import CommunicationPost
        post = CommunicationPost.objects.filter(id=post_id).select_related('user_created').first()
        author = post.user_created if post else None
        publisher = getattr(kwargs.get('cls_'), 'user', None)
        if not author or author == publisher:
            return
        notify_on_commit(
            type_code='comms.post_published',
            subject=f"Your post was published{': ' + post.title if post.title else ''}",
            target_route='/communications/feed',
            source_ref=f'communications:{post_id}',
            group_key=f'comms.post_published:{post_id}',
            actor=publisher, subject_user=author, recipients=[author],
        )
    except Exception:
        logger.warning('notifications: communications.on_post_published failed', exc_info=True)
