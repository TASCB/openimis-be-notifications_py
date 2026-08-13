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


def _payload(kwargs):
    """Unpack ``data=[args, kwargs]`` + ``result`` from a service signal."""
    data = kwargs.get('data') or []
    args = data[0] if len(data) > 0 else ()
    kwds = data[1] if len(data) > 1 else {}
    return args, (kwds or {}), kwargs.get('result')


def on_import_finished_signal(**kwargs):
    """Bound to ``api_etl_service.import_finished``. api_etl passes everything by keyword;
    the actor rides on the sender, as in the approval adapter."""
    try:
        _args, kwds, _result = _payload(kwargs)
        on_import_finished(
            kwds.get('history_id'),
            kwds.get('status'),
            getattr(kwargs.get('cls_'), 'user', None),
            paa_name=kwds.get('paa_name') or '',
            counts=kwds.get('counts') or {},
        )
    except Exception:
        logger.warning('notifications: api_etl signal unpack failed', exc_info=True)


def on_import_finished(history_id, status, user, *, paa_name='', counts=None):
    """Announce a terminal PulledHistory state to everyone who could have started the import.

    Recipients are NOT passed: the audience comes from the type's ``audience_rule``, which
    resolves the import right (953002). Passing ``recipients`` would bypass it.
    """
    try:
        key = (status or '').lower()
        mapped = _STATUS_TYPES.get(key)
        if not mapped:
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
            actor=user,
            subject_user=user,
        )
    except Exception:
        logger.warning('notifications: api_etl.on_import_finished failed', exc_info=True)
