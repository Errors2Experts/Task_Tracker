from django import forms
from django.core.exceptions import ValidationError
from django_ckeditor_5.widgets import CKEditor5Widget

from .models import Task, TaskAttachment, TaskComment, TaskPriority, TaskStatus
from .validators import (
    validate_attachment_file,
    validate_comment_body,
    validate_due_date_not_past,
)


class TaskRowForm(forms.Form):
    """One row in the 'Assign a task' table. A formset repeats this per task."""
    task_title = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Prepare onboarding checklist", "required": True}),
    )
    task_description = forms.CharField(
        required=False,
        widget=CKEditor5Widget(config_name='extends', attrs={"placeholder": "Task description (optional)"}),
    )
    priority = forms.ChoiceField(
        choices=TaskPriority.choices, required=False, initial=TaskPriority.MEDIUM,
    )
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    due_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    attachment = forms.FileField(required=False)

    def clean_attachment(self):
        uploaded_file = self.cleaned_data.get("attachment")
        if uploaded_file:
            validate_attachment_file(uploaded_file)
        return uploaded_file

    def clean(self):
        cleaned = super().clean()
        # An entirely blank row (user added a row but never filled it) should
        # just be skipped rather than raising a "this field is required" error.
        if not cleaned.get("task_title"):
            cleaned["_skip"] = True
            return cleaned

        if not cleaned.get("priority"):
            cleaned["priority"] = TaskPriority.MEDIUM

        due_date = cleaned.get("due_date")
        if due_date:
            try:
                validate_due_date_not_past(due_date)
            except ValidationError as exc:
                self.add_error("due_date", exc)
        return cleaned


class TaskEditForm(forms.ModelForm):
    """Full-field edit — priority, due date/time, description, and
    reassignment. Only ever shown to users `can_edit_task_fields()` allows in
    (see permissions.py); never to the assignee-only tier or HR."""

    class Meta:
        model = Task
        fields = ["title", "description", "priority", "due_date", "due_time", "assigned_to", "reporting_to"]
        widgets = {
            "title": forms.TextInput(),
            "description": forms.Textarea(attrs={"rows": 4}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "due_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, assignable_employees=None, reporting_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        if assignable_employees is not None:
            self.fields["assigned_to"].queryset = assignable_employees
        if reporting_choices is not None:
            self.fields["reporting_to"].queryset = reporting_choices
        self.fields["reporting_to"].required = False

    def clean_due_date(self):
        due_date = self.cleaned_data.get("due_date")
        # Editing an already-assigned task is allowed to keep a due date that
        # has since slipped into the past (it'll just show as overdue) — this
        # check only stops *moving* the due date to a new past date.
        if due_date and due_date != self.instance.due_date:
            validate_due_date_not_past(due_date)
        return due_date


class TaskStatusProgressForm(forms.ModelForm):
    """The only form the assignee (Employee/Intern) ever gets: status and
    progress on their own task. Kept as its own form (rather than reusing
    TaskEditForm) so there is no way for extra fields to sneak in.

    'Cancelled' is deliberately left out of the choices here — that status
    only ever gets set by the Team Lead reject decision (see
    task_team_lead_decision), which also snapshots pre_cancel_status.
    Letting anyone set it through this generic form would desync that
    bookkeeping and let an Employee/Intern (or anyone else with edit rights)
    cancel a task on their own, which isn't allowed."""

    class Meta:
        model = Task
        fields = ["status", "progress"]
        widgets = {
            "progress": forms.NumberInput(attrs={"min": 0, "max": 100, "step": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label) for value, label in self.fields["status"].choices
            if value != TaskStatus.CANCELLED
        ]

    def clean_progress(self):
        progress = self.cleaned_data.get("progress")
        if progress is None:
            return progress
        if not (0 <= progress <= 100):
            raise ValidationError("Progress must be between 0 and 100.")
        return progress


class TaskCommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": "Add a comment..."}),
        }

    def clean_body(self):
        return validate_comment_body(self.cleaned_data.get("body"))


class TaskAttachmentForm(forms.ModelForm):
    class Meta:
        model = TaskAttachment
        fields = ["file"]

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        validate_attachment_file(uploaded_file)
        return uploaded_file