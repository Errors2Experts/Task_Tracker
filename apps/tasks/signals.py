"""
Turns every TaskActivity into one or more TaskNotification rows, so
notifications never have to be created by hand at each call site (views,
API viewsets, admin) — log the activity once and the notification follows
automatically. This is the single place that decides *who* gets notified
for each kind of event.
"""
import json
import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from pywebpush import WebPushException, webpush

from .emails import send_task_completed_email, send_task_created_email
from .models import TaskActivity, TaskNotification

logger = logging.getLogger(__name__)


from django.contrib.auth import get_user_model

from apps.accounts.permissions import DESIGNATION_DEPARTMENT_MAP, get_team_lead_reviewers

User = get_user_model()

# Status changes: the people managing the task should hear about it.
STATUS_VERBS = {"PENDING", "IN_PROGRESS", "BLOCKED", "COMPLETED"}

# Changes to the task itself: the assignee should hear about it.
ASSIGNEE_NOTIFY_VERBS = {"CREATED", "REASSIGNED", "PRIORITY_CHANGED", "DUE_DATE_CHANGED"}

# Collaborative events: everyone with a stake in the task should hear about it.
PARTICIPANT_VERBS = {"COMMENTED", "ATTACHMENT_ADDED", "ATTACHMENT_REMOVED", "PROGRESS_UPDATED"}

# Cross-team approval workflow: these are targeted, not broadcast — only the
# specific people who need to act (or who asked for the task) get them.
APPROVAL_REQUEST_VERBS = {"APPROVAL_REQUESTED"}
APPROVAL_DECISION_VERBS = {"APPROVAL_GRANTED", "APPROVAL_REJECTED"}

# The assigner ticked "Team Lead Approved" while creating a cross-team task —
# nothing is pending review, but the target team's lead should still know a
# task landed on their team pre-approved on their behalf. Targeted at the
# team lead(s) only, not broadcast like a normal CREATED notification.
APPROVAL_PRE_GRANTED_VERBS = {"APPROVAL_PRE_GRANTED"}


def _department_leads_for(task):
    """Users whose designation maps (via DESIGNATION_DEPARTMENT_MAP) to this
    task's department — e.g. every Technical Lead for a Development-team
    task, every Testing Lead for a Testing-team task, and so on. These leads
    have full read/assign visibility over their entire department (see
    accounts/permissions.py), so — just like Admin and Manager — they should
    hear about every task in it, not only the ones they personally assigned.
    """
    if not task.team_id:
        return User.objects.none()

    designations = [
        designation for designation, department in DESIGNATION_DEPARTMENT_MAP.items()
        if department == task.team.department
    ]
    if not designations:
        return User.objects.none()

    return User.objects.filter(designation__in=designations, is_active=True)


def _recipients_for(activity):
    task = activity.task
    recipients = set()

    if activity.verb in APPROVAL_REQUEST_VERBS:
        # Cross-team assignment: only the target team's reviewer(s) need to
        # act — not broadcast to everyone the way a normal update is.
        recipients.update(get_team_lead_reviewers(task.team))
        recipients.discard(activity.actor)
        return recipients

    if activity.verb in APPROVAL_DECISION_VERBS:
        # Let whoever made the assignment (and the assignee) know the outcome.
        recipients.update(filter(None, [task.created_by, task.assigned_to]))
        recipients.discard(activity.actor)
        return recipients

    if activity.verb in APPROVAL_PRE_GRANTED_VERBS:
        # Pre-approved by the assigner at creation time — only the target
        # team's lead(s) need to hear about it, not the usual CREATED
        # broadcast (department leads, managers, admins).
        recipients.update(get_team_lead_reviewers(task.team))
        recipients.discard(activity.actor)
        return recipients

    if activity.verb in STATUS_VERBS:
        recipients.update(filter(None, [task.created_by, task.reporting_to]))

    elif activity.verb in ASSIGNEE_NOTIFY_VERBS:
        recipients.update(filter(None, [task.assigned_to]))

    elif activity.verb in PARTICIPANT_VERBS:
        recipients.update(filter(None, [
            task.assigned_to,
            task.created_by,
            task.reporting_to,
        ]))

    recipients.update(User.objects.filter(is_superuser=True))
    recipients.update(
        User.objects.filter(designation="MANAGER", is_active=True)
    )
    recipients.update(_department_leads_for(task))
    recipients.discard(activity.actor)

    return recipients


def _send_push_for_new_task(recipient, task, message):
    subscriptions = recipient.push_subscriptions.all()
    if not subscriptions:
        return

    payload = json.dumps({
        "title": "New task assigned",
        "body": message,
        "priority": task.priority,
        "task_id": task.id,
        "url": reverse("task_detail", args=[task.id]),
    })

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}"},
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                subscription.delete()
            else:
                logger.warning("Push send failed for %s: %s", recipient, exc)


@receiver(post_save, sender=TaskActivity)
def create_notifications_for_activity(sender, instance, created, **kwargs):
    if not created:
        return

    recipients = _recipients_for(instance)
    if not recipients:
        return

    message = instance.description()
    TaskNotification.objects.bulk_create([
        TaskNotification(
            recipient=recipient,
            task=instance.task,
            actor=instance.actor,
            verb=instance.verb,
            message=message,
        )
        for recipient in recipients
    ])

    if instance.verb == "CREATED" and instance.task_id:
        for recipient in recipients:
            _send_push_for_new_task(recipient, instance.task, message)
        try:
            send_task_created_email(instance.task)
        except Exception:
            logger.exception("Failed to send task-created email for task %s", instance.task_id)

    elif instance.verb == "COMPLETED" and instance.task_id:
        try:
            send_task_completed_email(instance.task)
        except Exception:
            logger.exception("Failed to send task-completed email for task %s", instance.task_id)