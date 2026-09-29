"""Case management adapter. Emits via ``notify_on_commit`` and never passes ``recipients=``,
which would bypass the location-scoped audiences.
"""
import logging

from notifications.services import notify_on_commit

logger = logging.getLogger(__name__)

HOUSEHOLD_ROUTE = '/caseManagement/household/{id}'
FOLLOW_UP_ROUTE = '/caseManagement/followUps/{id}'
PENDING_UPDATES_ROUTE = '/caseManagement/pendingUpdates'

# Person / membership / household edits held by maker-checker. TMOs decide them on Pending
# updates, so that is where these messages point, not the Tasks inbox.
DATA_UPDATE_LABELS = {
    'IndividualService.update': 'Member update',
    'GroupIndividualService.update': 'Member update',
    'GroupService.update': 'Household update',
}
_REPRESENTATIVE_FIELDS = ('role', 'recipient_type')


def _payload(kwargs):
    data = kwargs.get('data') or []
    args = data[0] if len(data) > 0 else ()
    kwds = data[1] if len(data) > 1 else {}
    return args, (kwds or {}), kwargs.get('result')


def _actor(kwargs):
    return getattr(kwargs.get('cls_'), 'user', None)


def _succeeded(result):
    return isinstance(result, dict) and result.get('success')


def _data(result):
    return (result or {}).get('data') or {}


def _location_ids(group):
    """The household's location and its ancestors: officers are scoped to districts, households
    sit at village level."""
    ids, location = [], getattr(group, 'location', None) if group is not None else None
    while location is not None and len(ids) < 10:
        ids.append(location.id)
        location = location.parent
    return ids


def on_payment_change(**kwargs):
    """A material change applied directly. Queued changes are already announced by
    on_case_task_created (and the approval engine), so they are skipped here.
    """
    from case_management.apps import CaseManagementConfig
    from case_management.models import PaymentChangeAudit

    try:
        if CaseManagementConfig.enable_payment_change_approval:
            return
        _, _, result = _payload(kwargs)
        data = _data(result)
        if not _succeeded(result) or data.get('queued') or not data.get('is_material'):
            return
        audit = PaymentChangeAudit.objects.filter(id=_data(result).get('id')).first()
        if not audit:
            return
        group = getattr(audit.group_beneficiary, 'group', None)
        notify_on_commit(
            type_code='case.payment_change.submitted',
            subject='Payment change awaiting approval',
            body=f"{audit.get_change_type_display()} on household "
                 f"{getattr(group, 'code', 'unknown')} — reason {audit.reason_code or 'not given'}",
            target_route=HOUSEHOLD_ROUTE.format(id=getattr(group, 'id', '')),
            source_ref=str(audit.id),
            group_key=f'case.payment_change:{audit.payment_account_id}',
            actor=_actor(kwargs),
            location_ids=_location_ids(group),
        )
    except Exception:
        logger.exception('notifications: case payment change adapter failed')


def on_case_task_created(**kwargs):
    """A case request was parked for a checker."""
    from case_management.services import (
        DEACTIVATE_HOUSEHOLD_EVENT, DEACTIVATE_MEMBER_EVENT, PAYMENT_CHANGE_EVENT,
    )

    LABELS = {
        PAYMENT_CHANGE_EVENT: 'Payment change',
        DEACTIVATE_MEMBER_EVENT: 'Member deactivation',
        DEACTIVATE_HOUSEHOLD_EVENT: 'Household deactivation',
    }
    try:
        _, _, result = _payload(kwargs)
        if not _succeeded(result):
            return
        task = _data(result)
        event = (task.get('business_event') or '')
        if event in DATA_UPDATE_LABELS:
            _notify_data_update_queued(task, kwargs)
            return
        if event not in LABELS:
            return

        data = task.get('data') or {}
        group = _group_for_task(event, data)
        notify_on_commit(
            type_code='case.update.queued',
            subject=f'{LABELS[event]} waiting for approval',
            body=(f"Reason {data.get('reason_code') or 'not given'}"
                  + (f" — household {group.code}" if group is not None else '')),
            target_route='/tasksManagement/tasks',
            source_ref=str(task.get('id') or ''),
            group_key=f"case.task:{task.get('id')}",
            actor=_actor(kwargs),
            location_ids=_location_ids(group),
        )
    except Exception:
        logger.exception('notifications: case task adapter failed')


def _load_task(task_id):
    from tasks_management.models import Task
    return Task.objects.filter(id=task_id).select_related('entity_type', 'user_created').first()


def _household_of_task(task):
    from case_management.services import _task_target, household_of
    target = _task_target(task)
    return household_of(target) if target is not None else None


def _is_representative_change(data):
    current, incoming = data.get('current_data') or {}, data.get('incoming_data') or {}
    return any(f in incoming and incoming.get(f) != current.get(f) for f in _REPRESENTATIVE_FIELDS)


def _data_update_label(event, data):
    return 'Representative change' if _is_representative_change(data) else DATA_UPDATE_LABELS[event]


def _notify_data_update_queued(task_repr, kwargs):
    task = _load_task(task_repr.get('id'))
    if task is None:
        return
    data = task.data or {}
    group = _household_of_task(task)
    notify_on_commit(
        type_code='case.update.queued',
        subject=f'{_data_update_label(task.business_event, data)} waiting for approval',
        body=f"Household {group.code}" if group is not None else '',
        target_route=PENDING_UPDATES_ROUTE,
        source_ref=str(task.id),
        group_key=f'case.task:{task.id}',
        actor=_actor(kwargs),
        location_ids=_location_ids(group),
    )


def on_data_update_task_complete(**kwargs):
    """Tell the submitter how their held edit ended, whether the TMO decided it on Pending
    updates or someone completed the task in the Tasks inbox: both paths complete the task."""
    from case_management.models import PendingDataUpdate

    try:
        _, _, result = _payload(kwargs)
        if not _succeeded(result):
            return
        task_repr = _data(result).get('task') or {}
        task = _load_task(task_repr.get('id'))
        if task is None or task.business_event not in DATA_UPDATE_LABELS:
            return
        pending = PendingDataUpdate.objects.filter(task_id=task.id, is_deleted=False).first()
        submitter = (pending.submitted_by if pending and pending.submitted_by_id else task.user_created)
        if submitter is None:
            return
        approved = task.status == task.Status.COMPLETED
        group = _household_of_task(task)
        note = ((pending.summary or {}).get('decision_note') if pending else None) or ''
        notify_on_commit(
            type_code='case.update.decided',
            subject=f"Your {_data_update_label(task.business_event, task.data or {}).lower()} was "
                    f"{'approved' if approved else 'rejected'}"
                    + (f" — household {group.code}" if group is not None else ''),
            body=note,
            target_route=PENDING_UPDATES_ROUTE,
            source_ref=str(task.id),
            group_key=f'case.task.decided:{task.id}',
            actor=_actor(kwargs),
            subject_user=submitter,
        )
    except Exception:
        logger.exception('notifications: case data-update decision adapter failed')


def _group_for_task(event, data):
    """Resolve the household a queued request concerns, for the location-scoped audience."""
    from case_management.services import DEACTIVATE_MEMBER_EVENT, PAYMENT_CHANGE_EVENT
    from individual.models import Group, GroupIndividual
    from tasaf_payment.models import PaymentAccount

    try:
        if event == PAYMENT_CHANGE_EVENT:
            account = PaymentAccount.objects.filter(
                id=data.get('payment_account_id')).select_related(
                'group_beneficiary__group').first()
            return getattr(account.group_beneficiary, 'group', None) if account else None
        if event == DEACTIVATE_MEMBER_EVENT:
            membership = GroupIndividual.objects.filter(
                id=data.get('group_individual_id')).select_related('group').first()
            return membership.group if membership else None
        return Group.objects.filter(id=data.get('group_id')).first()
    except Exception:
        return None


def on_pending_decided(**kwargs):
    from case_management.models import PendingDataUpdate

    try:
        _, _, result = _payload(kwargs)
        if not _succeeded(result):
            return
        pending = PendingDataUpdate.objects.filter(id=_data(result).get('id')).first()
        if not pending:
            return
        # A held edit is completed through its task; on_data_update_task_complete reports it,
        # so reporting it here as well would tell the submitter twice.
        if pending.is_proposal and pending.task_id:
            return
        notify_on_commit(
            type_code='case.payment_change.decided',
            subject=f"Your {pending.get_update_type_display().lower()} was "
                    f"{pending.get_status_display().lower()}",
            body=(pending.summary or {}).get('decision_note') or '',
            target_route=HOUSEHOLD_ROUTE.format(id=pending.group_id or ''),
            source_ref=str(pending.id),
            actor=_actor(kwargs),
            subject_user=pending.submitted_by,
        )
    except Exception:
        logger.exception('notifications: case pending decision adapter failed')


def on_household_deactivated(**kwargs):
    from case_management.models import HouseholdDeactivation

    try:
        _, _, result = _payload(kwargs)
        if not _succeeded(result):
            return
        record = HouseholdDeactivation.objects.filter(id=_data(result).get('id')).first()
        if not record:
            return
        notify_on_commit(
            type_code='case.household.deactivated',
            subject=f'Household {record.group.code} deactivated',
            body=f"{record.get_mode_display()} — {record.reason_code}"
                 f" effective {record.effective_date}",
            target_route=HOUSEHOLD_ROUTE.format(id=record.group_id),
            source_ref=str(record.id),
            actor=_actor(kwargs),
            location_ids=_location_ids(record.group),
        )
    except Exception:
        logger.exception('notifications: case deactivation adapter failed')


def on_follow_up_added(**kwargs):
    from case_management.models import FollowUpRemark

    try:
        _, _, result = _payload(kwargs)
        if not _succeeded(result):
            return
        remark = FollowUpRemark.objects.filter(id=_data(result).get('id')).first()
        if not remark or not remark.assigned_to_id:
            return
        notify_on_commit(
            type_code='case.followup.assigned',
            subject=f'Follow-up assigned: {remark.get_category_display()}',
            body=remark.remark[:280],
            target_route=FOLLOW_UP_ROUTE.format(id=remark.id),
            source_ref=str(remark.id),
            actor=_actor(kwargs),
            subject_user=remark.assigned_to,
        )
    except Exception:
        logger.exception('notifications: case follow-up adapter failed')


def on_follow_up_status(**kwargs):
    from case_management.models import FollowUpRemark, FollowUpStatus

    try:
        _, _, result = _payload(kwargs)
        if not _succeeded(result):
            return
        if _data(result).get('status') != FollowUpStatus.ESCALATED:
            return
        remark = FollowUpRemark.objects.filter(id=_data(result).get('id')).first()
        if not remark:
            return
        notify_on_commit(
            type_code='case.followup.escalated',
            subject=f'Follow-up escalated: {remark.get_category_display()}',
            body=remark.remark[:280],
            target_route=FOLLOW_UP_ROUTE.format(id=remark.id),
            source_ref=str(remark.id),
            actor=_actor(kwargs),
            location_ids=_location_ids(remark.group),
        )
    except Exception:
        logger.exception('notifications: case escalation adapter failed')
