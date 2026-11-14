import logging
from datetime import date

from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)

PMT_ROUTE = '/pmt-configuration'
INDIVIDUALS_ROUTE = '/individuals'
LEGACY_IMPORTS_ROUTE = '/legacy/imports'
TASK_ROUTE = '/tasks/task/{id}'

_UPLOAD_TYPES = {
    'SUCCESS': ('import.upload.completed', 'Upload finished'),
    'PARTIAL_SUCCESS': ('import.upload.partial', 'Upload finished with skipped rows'),
    'FAIL': ('import.upload.failed', 'Upload failed'),
    'WAITING_FOR_VERIFICATION': ('import.upload.waiting', 'Upload sent for approval'),
}
_LEGACY_TYPES = {
    'SUCCESS': ('import.legacy.completed', 'PSSN import finished'),
    'COMPLETED_WITH_ERRORS': ('import.legacy.partial', 'PSSN import finished with errors'),
    'FAIL': ('import.legacy.failed', 'PSSN import failed'),
}
_BATCHED_EVENTS = {'individual_deduplication.resolve'}


def _task_labels():
    from individual.apps import IndividualConfig
    labels = {
        IndividualConfig.validation_import_valid_items: 'Member upload',
        IndividualConfig.validation_upload_valid_items: 'Member update upload',
        IndividualConfig.validation_import_group_valid_items: 'Household upload',
        IndividualConfig.deduplication_review_event: 'Duplicate review',
        IndividualConfig.pct_enrolment_task_event: 'PCT enrolment',
        'PmtGlobalFormulaService.update': 'PMT formula change',
        'GroupService.delete': 'Household deletion',
    }
    return {k: v for k, v in labels.items() if k}


def _kwargs_data(kwargs):
    data = kwargs.get('data') or []
    return (data[1] if len(data) > 1 else None) or {}


def _actor(kwargs):
    return getattr(kwargs.get('cls_'), 'user', None)


def on_pmt_run_finished(**kwargs):
    from individual.models import PmtRunProgress
    try:
        mutation_id = _kwargs_data(kwargs).get('mutation_id')
        run = PmtRunProgress.objects.filter(mutation_id=mutation_id).select_related('user').first()
        if run is None or run.user is None:
            return
        failed = run.status == PmtRunProgress.Status.FAILED
        what = 'PMT rerun' if run.operation == PmtRunProgress.Operation.RERUN else 'PMT cutoff adjustment'
        scope = run.district_code or 'all PAAs'
        if failed:
            subject, body = f'{what} failed — {scope}', '; '.join(map(str, run.errors or []))[:1000]
        else:
            subject = f'{what} finished — {scope}'
            parts = []
            if run.previous_cutoff is not None and run.pmt_cutoff is not None:
                parts.append(f'Cutoff {run.previous_cutoff:g} → {run.pmt_cutoff:g}')
            if run.poor_before is not None and run.poor_after is not None:
                parts.append(f'eligible households {run.poor_before:,} → {run.poor_after:,}')
            if run.errors:
                parts.append(f'{len(run.errors)} warning(s)')
            body = ', '.join(parts)
        notify_on_commit(
            type_code='pmt.run.failed' if failed else 'pmt.run.completed',
            subject=subject,
            body=body,
            target_route=PMT_ROUTE,
            source_ref=f'pmt:{run.mutation_id}',
            group_key=f'pmt.run:{run.mutation_id}',
            actor=_actor(kwargs),
            subject_user=run.user,
        )
    except Exception:
        logger.warning('notifications: registry.on_pmt_run_finished failed', exc_info=True)


def on_upload_finished(**kwargs):
    from individual.models import IndividualDataSourceUpload
    try:
        upload = IndividualDataSourceUpload.objects.filter(id=_kwargs_data(kwargs).get('upload_id')).first()
        if upload is None:
            return
        mapped = _UPLOAD_TYPES.get(upload.status)
        if not mapped:
            return
        uploader = getattr(upload, 'user_created', None)
        if uploader is None:
            return
        type_code, title = mapped
        error = upload.error if isinstance(upload.error, dict) else {}
        notify_on_commit(
            type_code=type_code,
            subject=f'{title} — {upload.source_name or "file"}',
            body='; '.join(f'{k}: {v}' for k, v in error.items())[:1000] if upload.status == 'FAIL' else '',
            target_route=INDIVIDUALS_ROUTE,
            source_ref=f'upload:{upload.id}',
            group_key=f'{type_code}:{upload.id}',
            actor=_actor(kwargs),
            subject_user=uploader,
        )
    except Exception:
        logger.warning('notifications: registry.on_upload_finished failed', exc_info=True)


def on_legacy_api_import_finished(**kwargs):
    try:
        data = _kwargs_data(kwargs)
        mapped = _LEGACY_TYPES.get(data.get('status'))
        user = _actor(kwargs)
        if not mapped or user is None:
            return
        type_code, title = mapped
        place = data.get('paa_name') or data.get('district_code') or ''
        batch_id = data.get('batch_id') or ''
        notify_on_commit(
            type_code=type_code,
            subject=f'{title}{f" — {place}" if place else ""}',
            body=(data.get('message') or '')[:1000],
            target_route=f'{LEGACY_IMPORTS_ROUTE}/batch/{batch_id}' if batch_id else LEGACY_IMPORTS_ROUTE,
            source_ref=f'legacy_batch:{batch_id}',
            group_key=f'{type_code}:{batch_id or data.get("district_code")}:{date.today().isoformat()}',
            actor=user,
            subject_user=user,
        )
    except Exception:
        logger.warning('notifications: registry.on_legacy_api_import_finished failed', exc_info=True)


def _result_task(kwargs, nested):
    result = kwargs.get('result') or {}
    if not result.get('success'):
        return None
    data = result.get('data') or {}
    return (data.get('task') if nested else data) or None


def _executors(task):
    if task.task_group_id is None:
        return []
    from tasks_management.models import TaskExecutor
    return [
        e.user for e in TaskExecutor.objects
        .filter(task_group_id=task.task_group_id, is_deleted=False).select_related('user')
    ]


def on_task_created(**kwargs):
    from tasks_management.models import Task
    try:
        task_repr = _result_task(kwargs, nested=False)
        labels = _task_labels()
        if not task_repr or task_repr.get('business_event') not in labels:
            return
        task = Task.objects.filter(id=task_repr.get('id')).first()
        if task is None:
            return
        actor = _actor(kwargs)
        recipients = [u for u in _executors(task) if actor is None or u.id != actor.id]
        if not recipients:
            logger.info('notifications: registry task %s (%s) has no task-group recipients',
                        task.id, task.business_event)
            return
        label = labels[task.business_event]
        batched = task.business_event in _BATCHED_EVENTS
        notify_on_commit(
            type_code='registry.task.submitted',
            subject=f'{label}{"s" if batched else ""} waiting for approval',
            body='' if batched else (task.source or ''),
            target_route='/tasks' if batched else TASK_ROUTE.format(id=task.id),
            source_ref=str(task.id),
            group_key=(f'registry.task.submitted:{task.business_event}:{date.today().isoformat()}'
                       if batched else f'registry.task.submitted:{task.id}'),
            actor=actor,
            recipients=recipients,
        )
    except Exception:
        logger.warning('notifications: registry.on_task_created failed', exc_info=True)


def _decided_on_case_page(task):
    try:
        from case_management.models import PendingDataUpdate
    except ImportError:
        return False
    return PendingDataUpdate.objects.filter(task_id=task.id, is_deleted=False).exists()


def on_task_completed(**kwargs):
    from tasks_management.models import Task
    try:
        task_repr = _result_task(kwargs, nested=True)
        labels = _task_labels()
        if not task_repr or task_repr.get('business_event') not in labels:
            return
        task = Task.objects.filter(id=task_repr.get('id')).select_related('user_created').first()
        if task is None or task.user_created is None or _decided_on_case_page(task):
            return
        approved = task.status == Task.Status.COMPLETED
        notify_on_commit(
            type_code='registry.task.decided',
            subject=f"Your {labels[task.business_event].lower()} was {'approved' if approved else 'rejected'}",
            body='',
            target_route=TASK_ROUTE.format(id=task.id),
            source_ref=str(task.id),
            group_key=f'registry.task.decided:{task.id}',
            actor=_actor(kwargs),
            subject_user=task.user_created,
        )
    except Exception:
        logger.warning('notifications: registry.on_task_completed failed', exc_info=True)
