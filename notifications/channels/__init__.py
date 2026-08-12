"""Channel registry, keyed by code."""
from notifications.channels.base import DeliveryResult, NotificationChannel
from notifications.channels.inapp import InAppChannel

_CHANNELS = {}


def register(channel):
    _CHANNELS[channel.code] = channel
    return channel


register(InAppChannel())

# EMAIL and SMS land in Phase 6 (NOTIFICATIONS_TODO.md task 0.1).


def get(code):
    return _CHANNELS.get(code)


def available_codes():
    return [code for code, ch in _CHANNELS.items() if ch.is_available()]


def all_codes():
    return list(_CHANNELS.keys())


__all__ = ['DeliveryResult', 'NotificationChannel', 'register', 'get', 'available_codes', 'all_codes']
