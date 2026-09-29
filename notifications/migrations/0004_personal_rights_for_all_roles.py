"""Every role may see, mark read and set preferences for its own notifications (280001-3; the
queries only return the caller's own). Reverse keeps them on roles holding 280901.
"""
from django.db import migrations

PERSONAL = (280001, 280002, 280003)
ADMIN_MARKER = 280901


def grant(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for right in PERSONAL:
            cursor.execute(
                """
                INSERT INTO "tblRoleRight" ("RoleID", "RightID", "ValidityFrom", "AuditUserId")
                SELECT r."RoleID", %s, NOW(), 1
                FROM "tblRole" r
                WHERE r."ValidityTo" IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM "tblRoleRight" x
                      WHERE x."RoleID" = r."RoleID" AND x."RightID" = %s AND x."ValidityTo" IS NULL
                  )
                """,
                [right, right],
            )


def revoke(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM "tblRoleRight" rr
            WHERE rr."RightID" IN %s
              AND NOT EXISTS (
                  SELECT 1 FROM "tblRoleRight" a
                  WHERE a."RoleID" = rr."RoleID" AND a."RightID" = %s AND a."ValidityTo" IS NULL
              )
            """,
            [PERSONAL, ADMIN_MARKER],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_access_request_audiences'),
    ]

    operations = [migrations.RunPython(grant, revoke)]
