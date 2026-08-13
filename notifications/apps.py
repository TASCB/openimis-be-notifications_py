"""AppConfig for the Notifications module (module 28, rights 28xxxx)."""
import logging
import uuid

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)

MODULE_NAME = 'notifications'
IMIS_ADMINISTRATOR_SYSTEM = 64

DEFAULT_CONFIG = {
    # Rights
    'gql_notification_search_perms': ['280001'],
    'gql_notification_mark_read_perms': ['280002'],
    'gql_preference_manage_perms': ['280003'],
    'gql_notification_admin_perms': ['280901'],
    # Behaviour
    'channels_enabled': ['INAPP'],
    'bell_poll_seconds': 60,
    'bell_dropdown_size': 10,
    'retention_days': 90,
    'fanout_max_recipients': 500,
    'seed_types': True,
    # approval flow domain -> FE route for the DOMAIN record. {id} is the domain object id.
    'domain_routes': {
        'access_request.AccessRequest': '/access-requests/request/{id}',
        'tasaf_payment.Paylist': '/tasafPayment/paylist/{id}',
        'training.Training': '/trainings/training/{id}',
        'social_protection.Beneficiary': '/groups/group/{id}',
        'communications.CommunicationActivity': '/communications/activities/activity/{id}',
    },
    # used when the domain has no mapping, or the domain record id is unknown
    'fallback_approval_route': '/approval/request/{request_id}',
}

ALL_RIGHTS = [280001, 280002, 280003, 280901]

# Seeded idempotently by code; existing rows are never overwritten.
# api_etl gql_mutation_execute_api_etl_rule_perms — the right that starts an import.
IMPORT_RIGHT = '953002'
IMPORT_AUDIENCE = {'kind': 'right', 'right': IMPORT_RIGHT, 'exclude_actor': False}

DEFAULT_TYPES = [
    {
        'code': 'approval.step.assigned',
        'label': 'An approval step is waiting for you',
        'category': 'APPROVAL', 'severity': 'ACTION',
        'audience_rule': {'kind': 'actor'},
    },
    {
        'code': 'approval.rejected',
        'label': 'Your request was rejected',
        'category': 'APPROVAL', 'severity': 'ACTION',
        'audience_rule': {'kind': 'subject'},
    },
    {
        'code': 'approval.returned',
        'label': 'Your request was returned for correction',
        'category': 'APPROVAL', 'severity': 'ACTION',
        'audience_rule': {'kind': 'subject'},
    },
    {
        'code': 'approval.finalized',
        'label': 'Your request was finalised',
        'category': 'APPROVAL', 'severity': 'INFO',
        'audience_rule': {'kind': 'subject'},
    },
    {
        'code': 'account.provisioned',
        'label': 'Your account has been created',
        'category': 'ACCOUNT', 'severity': 'INFO',
        'audience_rule': {'kind': 'subject'},
        'is_mandatory': True,
    },
    {
        'code': 'account.request_rejected',
        'label': 'Your access request was not approved',
        'category': 'ACCOUNT', 'severity': 'INFO',
        'audience_rule': {'kind': 'subject'},
        'is_mandatory': True,
    },
    # Imports go to everyone holding the right that starts one (api_etl 953002), not just
    # the initiator: a run finishing at 3am must reach whoever is on shift. exclude_actor
    # is False because the initiator is exactly who wants the result.
    {
        'code': 'import.completed',
        'label': 'An import finished',
        'category': 'IMPORT', 'severity': 'INFO',
        'audience_rule': IMPORT_AUDIENCE,
    },
    {
        'code': 'import.partial',
        'label': 'An import finished with skipped rows',
        'category': 'IMPORT', 'severity': 'WARNING',
        'audience_rule': IMPORT_AUDIENCE,
    },
    {
        'code': 'import.failed',
        'label': 'An import failed',
        'category': 'IMPORT', 'severity': 'WARNING',
        'audience_rule': IMPORT_AUDIENCE,
    },
    {
        'code': 'comms.post_published',
        'label': 'A communication post was published',
        'category': 'COMMS', 'severity': 'INFO',
        'audience_rule': {'kind': 'subject'},
    },
]


class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = MODULE_NAME

    gql_notification_search_perms = []
    gql_notification_mark_read_perms = []
    gql_preference_manage_perms = []
    gql_notification_admin_perms = []
    channels_enabled = ['INAPP']
    bell_poll_seconds = 60
    bell_dropdown_size = 10
    retention_days = 90
    fanout_max_recipients = 500
    seed_types = True
    domain_routes = {}
    fallback_approval_route = '/approval/request/{request_id}'

    def ready(self):
        from core.models import ModuleConfiguration
        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CONFIG)
        self.__load_config(cfg)
        post_migrate.connect(on_post_migrate, sender=self)

    @classmethod
    def __load_config(cls, cfg):
        for field in cfg:
            if hasattr(NotificationsConfig, field):
                setattr(NotificationsConfig, field, cfg[field])


def on_post_migrate(sender, **kwargs):
    apps = kwargs.get('apps')
    try:
        _seed_admin_rights(apps)
    except Exception:
        logger.warning('notifications: right seeding skipped', exc_info=True)
    try:
        if NotificationsConfig.seed_types:
            _seed_types(apps)
    except Exception:
        logger.warning('notifications: type seeding skipped', exc_info=True)


def _seed_admin_rights(apps):
    """Grant the module rights to the IMIS administrator role. Other roles are an admin
    decision -- see the developer guide, section 10."""
    role_model = apps.get_model('core', 'Role')
    role_right_model = apps.get_model('core', 'RoleRight')

    role = role_model.objects.filter(
        is_system=IMIS_ADMINISTRATOR_SYSTEM, validity_to__isnull=True
    ).first()
    if not role:
        return
    for right_id in ALL_RIGHTS:
        role_right_model.objects.get_or_create(
            role=role, right_id=right_id, validity_to=None,
            defaults={'audit_user_id': 1},
        )


def _seed_types(apps):
    """Seed the code-defined types. Existing rows are left alone so admin edits survive a
    redeploy."""
    model = apps.get_model('notifications', 'NotificationType')
    for spec in DEFAULT_TYPES:
        if model.objects.filter(code=spec['code']).exists():
            continue
        model.objects.create(
            id=uuid.uuid4(),
            code=spec['code'],
            label=spec['label'],
            category=spec.get('category', 'SYSTEM'),
            severity=spec.get('severity', 'INFO'),
            default_channels=spec.get('default_channels', ['INAPP']),
            audience_rule=spec.get('audience_rule', {}),
            is_mandatory=spec.get('is_mandatory', False),
            is_active=True,
        )
