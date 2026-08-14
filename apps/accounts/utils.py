"""
Employee ID generation for admin-driven employee registration.

The Employee ID is stored as the user's `username` (same convention used
by self-registration — see forms.RegisterForm), so no schema change is
needed. IDs are generated in the sequential form E2E-001, E2E-002, ...
"""
import re

from django.db import IntegrityError, transaction

EMPLOYEE_ID_PREFIX = "E2E-"
EMPLOYEE_ID_DIGITS = 3

_EMPLOYEE_ID_RE = re.compile(rf"^{re.escape(EMPLOYEE_ID_PREFIX)}(\d+)$")

# How many times to retry generation on a collision (e.g. two admins
# registering an employee at almost the same moment) before giving up.
_MAX_ATTEMPTS = 5


def next_employee_id(User):
    """Returns the next sequential Employee ID as a string, e.g. 'E2E-004'.

    Looks at the highest existing `E2E-###`-style username and returns one
    past it, zero-padded to at least EMPLOYEE_ID_DIGITS digits. Usernames
    that don't match that exact pattern (e.g. free-form self-registration
    IDs) are ignored rather than raising an error.
    """
    highest = 0
    existing = User.objects.filter(
        username__startswith=EMPLOYEE_ID_PREFIX
    ).values_list("username", flat=True)
    for username in existing:
        match = _EMPLOYEE_ID_RE.match(username)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{EMPLOYEE_ID_PREFIX}{highest + 1:0{EMPLOYEE_ID_DIGITS}d}"


def create_employee_with_generated_id(User, build_user):
    """
    Creates and saves a User whose `username` is an auto-generated, unique
    Employee ID.

    `build_user(employee_id)` must return an *unsaved* User instance for
    that candidate ID (callers set whatever other fields they need there).
    On a rare collision (IntegrityError on the unique username) this
    generates the next ID and retries, up to `_MAX_ATTEMPTS` times, so
    concurrent registrations can't silently clobber each other.
    """
    last_error = None
    for _ in range(_MAX_ATTEMPTS):
        employee_id = next_employee_id(User)
        user = build_user(employee_id)
        try:
            with transaction.atomic():
                user.save()
            return user
        except IntegrityError as exc:
            last_error = exc
            continue
    raise last_error
