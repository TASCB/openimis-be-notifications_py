from django.db import migrations

CLOSE_SQL = """
UPDATE "notifications_Notification" n
SET is_read = TRUE, read_at = NOW()
FROM "notifications_NotificationType" t
WHERE t.id = n.type_id
  AND t.code = 'approval.step.assigned'
  AND n.is_read = FALSE
  AND NOT EXISTS (
      SELECT 1
      FROM approval_approvalrequest r
      JOIN approval_approvalstep s ON s.approval_request_id = r."UUID"
      WHERE 'approval:' || r."UUID" = n.source_ref
        AND s."UUID"::text = split_part(n.group_key, ':', 3)
        AND r.status = 'PENDING'
        AND s."order" = r.current_step_order
  )
"""


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0004_personal_rights_for_all_roles'),
        ('approval', '0004_approvalstep_assigned_group_id'),
    ]

    operations = [migrations.RunSQL(CLOSE_SQL, migrations.RunSQL.noop)]
