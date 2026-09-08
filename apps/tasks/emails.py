"""
Email notifications for task lifecycle events, sent through Django's
configured EMAIL_* backend (settings.py) — point EMAIL_HOST / EMAIL_HOST_USER
/ EMAIL_HOST_PASSWORD at Brevo's SMTP relay in your .env to send real mail:

    EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
    EMAIL_HOST=smtp-relay.brevo.com
    EMAIL_PORT=587
    EMAIL_USE_TLS=True
    EMAIL_HOST_USER=<your Brevo SMTP login>
    EMAIL_HOST_PASSWORD=<your Brevo SMTP key>
    DEFAULT_FROM_EMAIL=<a sender verified in Brevo>

Wired from apps/tasks/signals.py, right alongside the existing push
notifications, so nothing at any call site (views, API, admin) needs to
remember to send mail — logging the TaskActivity is enough.

  CREATED   -> To: assignee                            CC: Admin, Manager, HR
  COMPLETED -> To: Team Lead + department lead          CC: Admin, Manager, HR
               (Technical/Testing/Digital Marketing Lead, per department)
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db.models import Q
from django.urls import reverse
from django.utils.html import strip_tags

from apps.accounts.models import Designation
from apps.accounts.permissions import DESIGNATION_DEPARTMENT_MAP

logger = logging.getLogger(__name__)


def _with_designation(designation):
    """Users who hold `designation` as EITHER their primary designation OR
    one of their (possibly several) EmployeeAssignment rows — so someone
    holding a role only as a secondary designation still gets the same
    emails as anyone who holds it as their primary one."""
    User = get_user_model()
    return User.objects.filter(
        Q(designation=designation) | Q(assignments__designation=designation),
        is_active=True,
    ).distinct()


def _admin_manager_hr():
    """Admin (superuser), Manager, HR — the standing CC list on every task email."""
    User = get_user_model()
    users = set(User.objects.filter(is_superuser=True, is_active=True))
    users.update(_with_designation(Designation.MANAGER))
    users.update(_with_designation(Designation.HR))
    return users


def _team_and_dept_leads(task):
    """Team Lead (Developer) for this exact team + the department-wide lead
    (Technical/Testing/Digital Marketing Lead) for the task's department —
    the "To" list for a completion mail."""
    if not task.team_id:
        return set()

    User = get_user_model()
    leads = set(User.objects.filter(
        Q(designation=Designation.TEAM_LEAD_DEVELOPER, team_id=task.team_id)
        | Q(assignments__designation=Designation.TEAM_LEAD_DEVELOPER, assignments__team_id=task.team_id),
        is_active=True,
    ).distinct())
    dept_designations = [
        designation for designation, department in DESIGNATION_DEPARTMENT_MAP.items()
        if department == task.team.department
    ]
    for designation in dept_designations:
        leads.update(_with_designation(designation))
    return leads


def _emails(users):
    return sorted({u.email for u in users if u.email})


def _task_url(task):
    return f"{settings.SITE_URL.rstrip('/')}{reverse('task_detail', args=[task.id])}"


def _send(subject, body, to, cc):
    if not to:
        logger.info("Skipping email %r — no To recipients", subject)
        return
    cc = [addr for addr in cc if addr not in to]
    try:
        EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to,
            cc=cc,
        ).send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send email %r to %s (cc %s)", subject, to, cc)


def send_task_created_email(task):
    """Notify the assignee that a task was assigned to them, with
    Admin/Manager/HR on CC."""
    if not task.assigned_to or not task.assigned_to.email:
        return

    to = [task.assigned_to.email]
    cc = _emails(_admin_manager_hr())

    attachment_lines = "\n".join(
        f"  - {a.original_filename or 'file'}: {a.file.url}"
        for a in task.attachments.all()
    ) or "  -"

    body = (
        f"Hi {task.assigned_to.get_full_name() or task.assigned_to.username},\n\n"
        f"A new task has been assigned to you.\n\n"
        f"Title       : {task.title}\n"
        f"Description : {strip_tags(task.description).strip() or '-'}\n"
        f"Priority    : {task.get_priority_display()}\n"
        f"Team        : {task.team}\n"
        f"Due date    : {task.due_date or '-'}\n"
        f"Assigned by : {task.created_by.get_full_name() if task.created_by else '-'}\n\n"
        f"Attachments :\n{attachment_lines}\n\n"
        f"View task: {_task_url(task)}\n"
    )
    _send(f"New Task Assigned: {task.title}", body, to, cc)


def send_task_completed_email(task):
    """Notify the task's Team Lead + department lead that it's been marked
    Completed, with Admin/Manager/HR on CC."""
    to = _emails(_team_and_dept_leads(task))
    if not to:
        return

    cc = _emails(_admin_manager_hr())

    body = (
        f"The task below has been marked as Completed.\n\n"
        f"Title        : {task.title}\n"
        f"Team         : {task.team}\n"
        f"Completed by : {task.assigned_to.get_full_name() if task.assigned_to else '-'}\n\n"
        f"View task: {_task_url(task)}\n"
    )
    _send(f"Task Completed: {task.title}", body, to, cc)