"""Declarative audience resolution. Rule kinds and the two id/caching traps are documented in
the module developer guide, section 4."""
import logging

from core.models import User

logger = logging.getLogger(__name__)


def _users_with_right(right_code):
    from core.models import RoleRight, UserRole

    role_ids = list(
        RoleRight.filter_queryset()
        .filter(right_id=str(right_code))
        .values_list('role_id', flat=True)
        .distinct()
    )
    if not role_ids:
        return User.objects.none()

    i_user_ids = list(
        UserRole.filter_queryset()
        .filter(role_id__in=role_ids)
        .values_list('user_id', flat=True)
        .distinct()
    )
    if not i_user_ids:
        return User.objects.none()

    return User.objects.filter(i_user_id__in=i_user_ids, validity_to__isnull=True)


def _users_with_role_name(role_name):
    from core.models import Role, UserRole

    role_ids = list(
        Role.filter_queryset()
        .filter(name=role_name)
        .values_list('id', flat=True)
    )
    if not role_ids:
        return User.objects.none()
    i_user_ids = list(
        UserRole.filter_queryset()
        .filter(role_id__in=role_ids)
        .values_list('user_id', flat=True)
        .distinct()
    )
    return User.objects.filter(i_user_id__in=i_user_ids, validity_to__isnull=True)


def _apply_location_scope(users, location_ids):
    """Keep users whose district scope intersects ``location_ids``. Users with no district
    row count as unscoped and are kept."""
    if not location_ids:
        return users
    try:
        from location.models import UserDistrict
    except Exception:
        return users

    candidate_i_ids = [u.i_user_id for u in users if u.i_user_id]
    if not candidate_i_ids:
        return users

    scoped = set(
        UserDistrict.filter_queryset()
        .filter(user_id__in=candidate_i_ids)
        .values_list('user_id', flat=True)
        .distinct()
    )
    in_scope = set(
        UserDistrict.filter_queryset()
        .filter(user_id__in=candidate_i_ids, location_id__in=location_ids)
        .values_list('user_id', flat=True)
        .distinct()
    )
    return [u for u in users if u.i_user_id not in scoped or u.i_user_id in in_scope]


def resolve(rule, context):
    """Resolve an ``audience_rule`` to distinct ``core.User``. Never raises: an unresolvable
    rule yields nobody and logs."""
    try:
        return _resolve(rule or {}, context or {})
    except Exception:
        logger.warning('notifications: audience rule failed to resolve: %s', rule, exc_info=True)
        return []


def _resolve(rule, context):
    kind = (rule.get('kind') or '').lower()

    if kind == 'union':
        seen, out = set(), []
        for sub in rule.get('of') or []:
            for user in _resolve(sub, context):
                if user.id not in seen:
                    seen.add(user.id)
                    out.append(user)
        return out

    if kind == 'actor':
        actor = context.get('actor')
        return [actor] if actor else []

    if kind == 'subject':
        subject = context.get('subject')
        return [subject] if subject else []

    if kind == 'user':
        user = User.objects.filter(id=rule.get('user_id'), validity_to__isnull=True).first()
        return [user] if user else []

    if kind == 'right':
        users = list(_users_with_right(rule.get('right')))
    elif kind == 'role':
        users = list(_users_with_role_name(rule.get('role')))
    else:
        logger.warning('notifications: unknown audience rule kind %r', kind)
        return []

    if rule.get('location_scope') == 'request':
        users = _apply_location_scope(users, context.get('location_ids') or [])

    if rule.get('exclude_actor', True):
        actor = context.get('actor')
        if actor is not None:
            users = [u for u in users if u.id != actor.id]

    return users
