from django.contrib import admin

from notifications.models import Notification, NotificationPreference, NotificationType


@admin.register(NotificationType)
class NotificationTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'category', 'severity', 'is_mandatory', 'is_active')
    list_filter = ('category', 'severity', 'is_active', 'is_mandatory')
    search_fields = ('code', 'label')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'recipient', 'category', 'severity', 'subject', 'is_read')
    list_filter = ('category', 'severity', 'is_read')
    search_fields = ('subject', 'source_ref')
    raw_id_fields = ('recipient',)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'type_code', 'channel', 'enabled')
    list_filter = ('channel', 'enabled')
    raw_id_fields = ('user',)
