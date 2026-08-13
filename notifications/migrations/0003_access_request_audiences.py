import uuid

from django.db import migrations

# Seeding skips codes that already exist, so a seeded server needs these applied explicitly.
SUBJECT_RULE = {'kind': 'subject'}
ICT_RULE = {'kind': 'right', 'right': '230202', 'exclude_actor': False}
APPROVER_RULE = {
    'kind': 'union',
    'of': [{'kind': 'right', 'right': '230201'}, {'kind': 'right', 'right': '230202'}],
}

READY_TO_PROVISION = {
    'code': 'account.ready_to_provision',
    'label': 'An access request is awaiting provisioning',
    'category': 'ACCOUNT',
    'severity': 'ACTION',
    'audience_rule': ICT_RULE,
}


def apply_audiences(apps, schema_editor):
    NotificationType = apps.get_model('notifications', 'NotificationType')

    if not NotificationType.objects.filter(code=READY_TO_PROVISION['code']).exists():
        NotificationType.objects.create(
            id=uuid.uuid4(),
            code=READY_TO_PROVISION['code'],
            label=READY_TO_PROVISION['label'],
            category=READY_TO_PROVISION['category'],
            severity=READY_TO_PROVISION['severity'],
            default_channels=['INAPP'],
            audience_rule=READY_TO_PROVISION['audience_rule'],
            is_mandatory=False,
            is_active=True,
        )

    # A rejected applicant has no account, so the subject rule could never reach anyone.
    NotificationType.objects.filter(
        code='account.request_rejected', audience_rule=SUBJECT_RULE
    ).update(audience_rule=APPROVER_RULE, label='An access request was not approved')


def revert_audiences(apps, schema_editor):
    NotificationType = apps.get_model('notifications', 'NotificationType')
    NotificationType.objects.filter(code=READY_TO_PROVISION['code']).delete()
    NotificationType.objects.filter(
        code='account.request_rejected', audience_rule=APPROVER_RULE
    ).update(audience_rule=SUBJECT_RULE, label='Your access request was not approved')


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_import_audience_right'),
    ]

    operations = [
        migrations.RunPython(apply_audiences, revert_audiences),
    ]
