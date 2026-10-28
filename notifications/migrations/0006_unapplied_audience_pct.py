from django.db import migrations

# Seeding skips codes that already exist, so a seeded server needs the new audience applied explicitly.
OLD_RULE = {
    'kind': 'union',
    'of': [{'kind': 'right', 'right': '270303', 'exclude_actor': False},
           {'kind': 'right', 'right': '270304', 'exclude_actor': False}],
}
NEW_RULE = {'kind': 'right', 'right': '270402', 'exclude_actor': False}


def apply_audience(apps, schema_editor):
    apps.get_model('notifications', 'NotificationType').objects.filter(
        code='payment.muse.unapplied', audience_rule=OLD_RULE,
    ).update(audience_rule=NEW_RULE, severity='ACTION')


def revert_audience(apps, schema_editor):
    apps.get_model('notifications', 'NotificationType').objects.filter(
        code='payment.muse.unapplied', audience_rule=NEW_RULE,
    ).update(audience_rule=OLD_RULE, severity='WARNING')


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0005_close_decided_approval_notices'),
    ]

    operations = [
        migrations.RunPython(apply_audience, revert_audience),
    ]
