"""ETL imports → notifications.

The highest net-new value in the module: an import runs for minutes in a Celery worker and
today finishes with no signal to the person who started it. Partial success in particular is
easy to miss entirely.
"""
import logging

from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)

_STATUS_TYPES = {
    'completed': ('import.completed', 'Import finished'),
    'partial_success': ('import.partial', 'Import finished with skipped rows'),
    'failed': ('import.failed', 'Import failed'),
}


def on_import_finished(history_id, status, user, *, paa_name='', counts=None):
    """Called by the api_etl adapter shim once a PulledHistory reaches a terminal state."""
    try:
        key = (status or '').lower()
        mapped = _STATUS_TYPES.get(key)
        if not mapped or not user:
            return
        type_code, title = mapped
        counts = counts or {}
        detail = ', '.join(f'{k}: {v}' for k, v in counts.items() if v is not None)
        notify_on_commit(
            type_code=type_code,
            subject=f'{title}{f" — {paa_name}" if paa_name else ""}',
            body=detail,
            target_route='/imports',
            source_ref=f'api_etl:{history_id}',
            group_key=f'{type_code}:{history_id}',
            subject_user=user,
            recipients=[user],
        )
    except Exception:
        logger.warning('notifications: api_etl.on_import_finished failed', exc_info=True)
