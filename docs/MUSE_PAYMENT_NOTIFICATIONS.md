# MUSE payment notifications — how fast, and who gets them

Traced 2026-11-02 for the question "if a paylist is rejected in MUSE, do I get the notification on
time?". Covers the `payment.muse.*` types fed by `tasaf_payment.events.muse_event`.

## 1. Path of a rejection

```
MUSE ─▶ GovESB ─▶ tasaf_payment views (MUSE callback) ─▶ muse/inbound.handle()
     ─▶ services.apply_muse_batch_status(REJECTED)      paylist.status = REJECTED, muse_status_desc = reason
     ─▶ events.emit_muse_event('batch_status')          sent on transaction commit
     ─▶ notifications/adapters/tasaf_payment.on_muse_event
     ─▶ NotificationService.notify('payment.muse.batch_rejected')   INAPP rows, one per recipient
     ─▶ fe-notifications NotificationBell                 polls the unread count
```

- MUSE **pushes** the reply; nothing on our side polls MUSE. The callback is handled inside the
  request, so the paylist and the notification are written within the same second.
- A reply that arrives **before our Submit has finished** is held (send-race marker) and applied as
  soon as the paylist is SUBMITTED — seconds.
- REJECTED is applied only while the paylist is at ACCEPTED or earlier; a late REJECTED after the bank
  stages is ignored.
- Notification text: subject `MUSE rejected <batch ref>`, body = MUSE's reason, link to the paylist.
  `group_key` includes the MUSE message id, so a re-send that is rejected again notifies again.

## 2. When it shows

The bell (`NotificationBell`) fetches the unread count every **60 s** (`DEFAULT_POLL_SECONDS`) while
the MIS tab is visible, and at once when the tab becomes visible again. So: **within about a minute**
for a logged-in user.

## 3. Who receives it

| Type | Audience | Roles today |
|---|---|---|
| `payment.muse.batch_rejected`, `batch_status`, `closed` | right `270303` (approve paylist) or `270304` (submit paylist) | Payment Approver, IMIS Administrator |
| `payment.muse.unapplied` | `270402` | unapplied decision makers |
| `payment.muse.unapplied_overdue` | `270403` | unapplied managers |

With the agreed job-title mapping, Payment Approver = ED, DFA, Accounts Manager, Disbursement Manager.
**Not notified of a rejection:** Disbursement Maker (E-Payment Officer, Accountant – Disbursements)
and Finance Manager (Reviewer) — the people who prepared the paylist.

## 4. When it is not on time

- **User not logged in** — INAPP is the only working channel (email is not working); they see it at
  the next login.
- **MUSE's message never reaches us** (e.g. GovESB refuses the callback, as happened with GePG's
  403) — nothing is created and the paylist stays SUBMITTED. Unlike GePG
  (`gepg_answer_warning_minutes`), MUSE has **no "no reply yet" reminder**.

## 5. Possible changes (not built)

1. Add Disbursement Maker and Finance Manager (Reviewer) to the rejection audience. Needs a data
   migration: `_seed_types` only creates missing types on `post_migrate`, so editing `DEFAULT_TYPES`
   does not change a server's existing row.
2. A reminder when a SUBMITTED paylist has had no MUSE reply after a set time (like GePG's).

## 6. Checking it

- Type exists and is active: `select code, is_active from "notifications_NotificationType" where code like 'payment.muse%';`
  Types are created by `migrate` (post_migrate); a database that has not been migrated since a type
  was added lacks it (local dev on 2026-11-02 lacked `payment.muse.unapplied_overdue`).
- Who would receive it: users holding `270303` / `270304` through a live role.
- Did MUSE's reply arrive: the MUSE inbound log row for the paylist (message type RESPONSE / ACK,
  status) and the paylist's `muse_status_desc` / `muse_status_at`.
