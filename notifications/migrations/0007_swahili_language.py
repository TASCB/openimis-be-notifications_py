from django.db import migrations

# Swahili is offered next to English: users choose it in the app, and the server writes their notifications in it.
# English first, Swahili second, French (shipped by openIMIS) last.
ORDER = {'en': 1, 'sw': 2, 'fr': 3}


def add_swahili(apps, schema_editor):
    Language = apps.get_model('core', 'Language')
    Language.objects.get_or_create(code='sw', defaults={'name': 'Kiswahili', 'sort_order': ORDER['sw']})
    for code, order in ORDER.items():
        # only fill an order nobody has set, so a server's own ordering stays
        Language.objects.filter(code=code, sort_order__isnull=True).update(sort_order=order)


def remove_swahili(apps, schema_editor):
    # users may have chosen it: move them back to English before the language goes
    apps.get_model('core', 'InteractiveUser').objects.filter(language_id='sw').update(language_id='en')
    apps.get_model('core', 'Language').objects.filter(code='sw').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0031_alter_mutationlog_client_mutation_id'),
        ('notifications', '0006_unapplied_audience_pct'),
    ]

    operations = [migrations.RunPython(add_swahili, remove_swahili)]
