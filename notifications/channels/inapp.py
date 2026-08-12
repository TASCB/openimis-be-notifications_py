"""In-app channel. Delivery is the Notification row itself, so it cannot fail."""
from notifications.channels.base import DeliveryResult, NotificationChannel


class InAppChannel(NotificationChannel):
    code = 'INAPP'

    def is_available(self):
        return True

    def address_for(self, user):
        return str(user.id)

    def send(self, notification, address):
        return DeliveryResult(status='SENT', detail='in-app row written')
