"""
scheduler/substitution_service.py

Stage 9: Resource Substitution (teachers).

Answers one question: "if the currently assigned teacher for this
Subject were unavailable, who else could reasonably take it, and why?"

This deliberately reuses the SAME definition of "assigned teacher" that
the rest of the project uses (timetable_service.build_sessions() picks
subject.qualified_teachers.first() as the one actually teaching it,
falling back automatically to an available qualified alternative if
that teacher is marked unavailable) - so the workload numbers shown
here match what Stages 4-8 actually schedule, not a different,
inconsistent notion of "workload."

Two factors decide whether a candidate is a real suggestion:
  - AVAILABILITY (Teacher.is_available) - a hard requirement. An
    unavailable teacher cannot actually be assigned, so they are
    excluded from suggestions entirely, not just penalized.
  - WORKLOAD (against Teacher.max_hours_per_week) - a soft ranking
    signal: feasible (under cap) candidates are suggested first, sorted
    by lowest resulting workload; over-cap candidates are still shown,
    but clearly marked, since a human may choose to accept the overload
    or raise the cap rather than have no options at all.
"""

from .models import Subject, Teacher


def _teacher_current_workload(teacher):
    """
    How many sessions per week this teacher is ALREADY assigned to teach,
    using the same rule as build_sessions(): only subjects where this
    teacher is the FIRST qualified teacher count as "assigned" to them.
    (Being second or third choice on some other subject doesn't add load -
    that subject is being taught by someone else, unless a substitution
    happened - see build_sessions() for the full rule.)
    """
    total = 0
    for subject in Subject.objects.filter(qualified_teachers=teacher):
        if subject.qualified_teachers.first().id == teacher.id:
            total += subject.hours_per_week
    return total


def suggest_teacher_substitutes(subject_id):
    """
    Returns:
        {
            "subject": Subject,
            "current_teacher": Teacher or None,
            "current_teacher_unavailable": bool,
            "suggestions": [
                {
                    "teacher": Teacher,
                    "current_workload": int,       # hours/week already assigned
                    "projected_workload": int,      # if they also took this subject
                    "over_cap": bool,               # would exceed max_hours_per_week
                    "reason": str,                  # human-readable explanation
                },
                ...
            ]  # only AVAILABLE teachers appear here, sorted: feasible (not
               # over cap) first, then by lowest projected workload
            "unavailable_alternatives": [Teacher, ...]  # qualified but
               # currently unavailable - shown separately so it's clear
               # they exist but can't be used right now, rather than
               # looking like they were never qualified at all
        }
        or {"error": "..."} if the subject doesn't exist.
    """
    try:
        subject = Subject.objects.select_related("division").get(id=subject_id)
    except Subject.DoesNotExist:
        return {"error": f"No subject with id {subject_id}."}

    current_teacher = subject.qualified_teachers.first()

    alternatives = subject.qualified_teachers.all()
    if current_teacher:
        alternatives = alternatives.exclude(id=current_teacher.id)

    available_alternatives = [t for t in alternatives if t.is_available]
    unavailable_alternatives = [t for t in alternatives if not t.is_available]

    suggestions = []
    for teacher in available_alternatives:
        current_workload = _teacher_current_workload(teacher)
        projected_workload = current_workload + subject.hours_per_week
        over_cap = projected_workload > teacher.max_hours_per_week

        if over_cap:
            reason = (
                f"Qualified for {subject.code} and currently available, but already teaches "
                f"{current_workload} hrs/week; adding {subject.hours_per_week} more would bring "
                f"them to {projected_workload} hrs/week, over their {teacher.max_hours_per_week}-hour "
                f"cap. Usable only if their cap is raised or another of their subjects is reassigned."
            )
        else:
            room_left = teacher.max_hours_per_week - projected_workload
            reason = (
                f"Qualified for {subject.code} and currently available. Currently teaches "
                f"{current_workload} hrs/week; adding {subject.hours_per_week} more brings them to "
                f"{projected_workload} hrs/week, still {room_left} hrs under their "
                f"{teacher.max_hours_per_week}-hour cap."
            )

        suggestions.append({
            "teacher": teacher,
            "current_workload": current_workload,
            "projected_workload": projected_workload,
            "over_cap": over_cap,
            "reason": reason,
        })

    # Best suggestions first: feasible (not over cap) before infeasible,
    # and within each group, whoever ends up with the lightest load.
    suggestions.sort(key=lambda s: (s["over_cap"], s["projected_workload"]))

    return {
        "subject": subject,
        "current_teacher": current_teacher,
        "current_teacher_unavailable": bool(current_teacher and not current_teacher.is_available),
        "current_teacher_workload": _teacher_current_workload(current_teacher) if current_teacher else None,
        "suggestions": suggestions,
        "unavailable_alternatives": unavailable_alternatives,
    }
