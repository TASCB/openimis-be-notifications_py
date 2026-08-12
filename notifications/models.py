"""Notification models — module 28."""
import uuid

from core.models import User
from django.db import models


class Category(models.TextChoices):
    APPROVAL = 'APPROVAL', 'Approval'
    ACCOUNT = 'ACCOUNT', 'Account'
    IMPORT = 'IMPORT', 'Import'
    COMMS = 'COMMS', 'Communications'
    SYSTEM = 'SYSTEM', 'System'


class Severity(models.TextChoices):
    INFO = 'INFO', 'Information'
    ACTION = 'ACTION', 'Action required'
    WARNING = 'WARNING', 'Warning'


class Channel(models.TextChoices):
    INAPP = 'INAPP', 'In-app'
    EMAIL = 'EMAIL', 'Email'
    SMS = 'SMS', 'SMS'


class NotificationType(models.Model):
    """Registry row per event kind, seeded on post_migrate and editable by admins."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.SYSTEM)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.INFO)
    default_channels = models.JSONField(default=list)
    audience_rule = models.JSONField(default=dict)
    is_mandatory = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notifications_NotificationType'

    def __str__(self):
        return self.code


class Notification(models.Model):
    """One row per recipient, fanned out at write time."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    type = models.ForeignKey(NotificationType, on_delete=models.PROTECT, related_name='notifications')

    category = models.CharField(max_length=20, choices=Category.choices, default=Category.SYSTEM)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.INFO)

    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True, default='')
    target_route = models.CharField(max_length=255, blank=True, default='')

    source_ref = models.CharField(max_length=255, blank=True, default='')
    group_key = models.CharField(max_length=255, blank=True, default='')

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications_Notification'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at'], name='notif_badge_idx'),
            models.Index(fields=['source_ref'], name='notif_source_idx'),
            models.Index(fields=['recipient', 'group_key'], name='notif_group_idx'),
        ]

    def __str__(self):
        return f'{self.recipient_id}: {self.subject}'


class NotificationPreference(models.Model):
    """Opt-out preference. Absent means enabled."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_preferences')
    type_code = models.CharField(max_length=100)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.INAPP)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'notifications_NotificationPreference'
        unique_together = [('user', 'type_code', 'channel')]

    def __str__(self):
        return f'{self.user_id}/{self.type_code}/{self.channel}={self.enabled}'
