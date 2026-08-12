"""GraphQL surface. Everything is scoped server-side to ``info.context.user``; there is
deliberately no userId argument anywhere."""
import graphene
from core.schema import OrderedDjangoFilterConnectionField
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _
from graphene_django import DjangoObjectType

from notifications.apps import NotificationsConfig
from notifications.models import Notification, NotificationPreference, NotificationType
from notifications.services import NotificationService


def _check(info, perms):
    user = info.context.user
    if not user or user.is_anonymous:
        raise PermissionDenied(_('unauthorized'))
    if not user.has_perms(perms):
        raise PermissionDenied(_('unauthorized'))
    return user


class NotificationTypeGQLType(DjangoObjectType):
    class Meta:
        model = NotificationType
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'code': ['exact', 'icontains'],
            'category': ['exact'],
            'is_active': ['exact'],
        }


class NotificationGQLType(DjangoObjectType):
    type_code = graphene.String()

    class Meta:
        model = Notification
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'category': ['exact'],
            'severity': ['exact'],
            'is_read': ['exact'],
            'created_at': ['exact', 'gte', 'lte'],
        }

    def resolve_type_code(self, info):
        return self.type.code if self.type_id else None


class NotificationPreferenceGQLType(DjangoObjectType):
    class Meta:
        model = NotificationPreference
        interfaces = (graphene.relay.Node,)
        filter_fields = {'type_code': ['exact'], 'channel': ['exact']}


class MarkNotificationsRead(graphene.Mutation):
    class Arguments:
        ids = graphene.List(graphene.UUID, required=False)
        all = graphene.Boolean(required=False, default_value=False)

    updated = graphene.Int()

    @classmethod
    def mutate(cls, root, info, ids=None, all=False):
        user = _check(info, NotificationsConfig.gql_notification_mark_read_perms)
        service = NotificationService(user)
        if all:
            return MarkNotificationsRead(updated=service.mark_all_read(user))
        return MarkNotificationsRead(updated=service.mark_read(ids or [], user))


class SetNotificationPreference(graphene.Mutation):
    class Arguments:
        type_code = graphene.String(required=True)
        channel = graphene.String(required=False, default_value='INAPP')
        enabled = graphene.Boolean(required=True)

    ok = graphene.Boolean()

    @classmethod
    def mutate(cls, root, info, type_code, channel='INAPP', enabled=True):
        user = _check(info, NotificationsConfig.gql_preference_manage_perms)
        ntype = NotificationType.objects.filter(code=type_code).first()
        if ntype and ntype.is_mandatory:
            raise PermissionDenied(_('notifications.validation.type_is_mandatory'))
        NotificationPreference.objects.update_or_create(
            user=user, type_code=type_code, channel=channel,
            defaults={'enabled': enabled},
        )
        return SetNotificationPreference(ok=True)


class Query(graphene.ObjectType):
    notifications = OrderedDjangoFilterConnectionField(
        NotificationGQLType, orderBy=graphene.List(of_type=graphene.String))
    notification_unread_count = graphene.Int()
    notification_types = OrderedDjangoFilterConnectionField(NotificationTypeGQLType)
    notification_preferences = OrderedDjangoFilterConnectionField(NotificationPreferenceGQLType)
    notification_config = graphene.JSONString()

    def resolve_notifications(self, info, **kwargs):
        user = _check(info, NotificationsConfig.gql_notification_search_perms)
        return Notification.objects.filter(recipient=user).select_related('type')

    def resolve_notification_unread_count(self, info, **kwargs):
        user = _check(info, NotificationsConfig.gql_notification_search_perms)
        return NotificationService(user).unread_count(user)

    def resolve_notification_types(self, info, **kwargs):
        _check(info, NotificationsConfig.gql_notification_search_perms)
        return NotificationType.objects.filter(is_active=True)

    def resolve_notification_preferences(self, info, **kwargs):
        user = _check(info, NotificationsConfig.gql_preference_manage_perms)
        return NotificationPreference.objects.filter(user=user)

    def resolve_notification_config(self, info, **kwargs):
        """Bell cadence, so polling can be retuned without a frontend release."""
        _check(info, NotificationsConfig.gql_notification_search_perms)
        return {
            'pollSeconds': NotificationsConfig.bell_poll_seconds,
            'dropdownSize': NotificationsConfig.bell_dropdown_size,
        }


class Mutation(graphene.ObjectType):
    mark_notifications_read = MarkNotificationsRead.Field()
    set_notification_preference = SetNotificationPreference.Field()
