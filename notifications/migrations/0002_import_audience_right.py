from django.db import migrations

# Seeding skips rows that already exist, so servers seeded before this change keep the old
# initiator-only audience. Only rows still carrying that exact default are updated, so an
# admin edit is never overwritten.
OLD_RULE = {'kind': 'subject'}
NEW_RULE = {'kind': 'right', 'right': '953002', 'exclude_actor': False}

LABELS = {
    'import.completed': 'An import finished',
    'import.partial': 'An import finished with skipped rows',
    'import.failed': 'An import failed',
}


def set_import_audience(apps, schema_editor):
    NotificationType = apps.get_model('notifications', 'NotificationType')
    for code, label in LABELS.items():
        NotificationType.objects.filter(code=code, audience_rule=OLD_RULE).update(
            audience_rule=NEW_RULE, label=label
        )


def restore_subject_audience(apps, schema_editor):
    NotificationType = apps.get_model('notifications', 'NotificationType')
    NotificationType.objects.filter(code__in=LABELS.keys(), audience_rule=NEW_RULE).update(
        audience_rule=OLD_RULE
    )


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(set_import_audience, restore_subject_audience),
    ]
