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


def _teacher_current_workload(teacher, sessions=None):
    """
    How many sessions per week this teacher is ALREADY assigned to teach,
    computed directly from build_sessions() so workload numbers match the
    actual scheduler pipeline exactly.

    Pass a pre-built `sessions` list to avoid redundant DB calls (Bug 3 fix).
    If omitted, build_sessions() is called once internally.
    """
    if sessions is None:
        from .timetable_service import build_sessions
        sessions, _ = build_sessions()
    return sum(1 for s in sessions if s["teacher"].id == teacher.id)


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

    # Bug 3 fix: call build_sessions() exactly ONCE and reuse the result for
    # all workload lookups, instead of N+1 separate DB queries (one per teacher).
    from .timetable_service import build_sessions
    all_sessions, _ = build_sessions()

    def _workload(teacher):
        return sum(1 for s in all_sessions if s["teacher"].id == teacher.id)

    suggestions = []
    for teacher in available_alternatives:
        current_workload = _workload(teacher)
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
        "current_teacher_workload": _workload(current_teacher) if current_teacher else None,
        "suggestions": suggestions,
        "unavailable_alternatives": unavailable_alternatives,
    }
