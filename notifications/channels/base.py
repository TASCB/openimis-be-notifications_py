"""Channel plugin contract. Nothing is ever marked SENT without a channel confirming it --
see the developer guide, section 5."""
from dataclasses import dataclass


@dataclass
class DeliveryResult:
    status: str          # SENT | SKIPPED | FAILED
    detail: str = ''

    @property
    def ok(self):
        return self.status == 'SENT'


class NotificationChannel:
    code = None

    def is_available(self) -> bool:
        """False when switched off or credentials are missing."""
        raise NotImplementedError

    def address_for(self, user):
        """Destination for this user, or None if unreachable."""
        raise NotImplementedError

    def send(self, notification, address) -> DeliveryResult:
        raise NotImplementedError
