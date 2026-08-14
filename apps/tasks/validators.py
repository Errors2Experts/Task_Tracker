"""
Shared validation logic for the Task Management module — used by both the
server-rendered forms (forms.py) and the REST API (serializers.py) so the
two surfaces can never drift apart on what counts as valid input.
"""
import os

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import ALLOWED_ATTACHMENT_EXTENSIONS, MAX_ATTACHMENT_SIZE_BYTES


def validate_progress_value(value):
    if value is None:
        return
    if not (0 <= value <= 100):
        raise ValidationError("Progress must be between 0 and 100.")


def validate_due_date_not_past(due_date, *, allow_today=True):
    """Used when a task is first created — a task shouldn't be assigned
    with a due date already in the past. Editing an existing task's other
    fields does not re-run this (a task can legitimately become overdue)."""
    if not due_date:
        return
    today = timezone.localdate()
    if due_date < today or (due_date == today and not allow_today):
        raise ValidationError("Due date can't be in the past.")


def validate_comment_body(body):
    body = (body or "").strip()
    if not body:
        raise ValidationError("Comment can't be empty.")
    if len(body) > 2000:
        raise ValidationError("Comment is too long (max 2000 characters).")
    return body


def validate_attachment_file(uploaded_file):
    """Extension + size checks, shared by the plain form and the API
    serializer. Raises django.core.exceptions.ValidationError on failure."""
    if not uploaded_file:
        raise ValidationError("Please choose a file to upload.")

    ext = os.path.splitext(uploaded_file.name)[1].lstrip(".").lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValidationError(
            f'Files of type ".{ext}" aren\'t allowed. Allowed types: '
            + ", ".join(ALLOWED_ATTACHMENT_EXTENSIONS)
        )

    if uploaded_file.size > MAX_ATTACHMENT_SIZE_BYTES:
        max_mb = MAX_ATTACHMENT_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(f"File is too large — the limit is {max_mb} MB.")
