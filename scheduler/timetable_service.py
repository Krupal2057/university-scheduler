"""
scheduler/timetable_service.py

Stage 4: connects the real database to the C++ engines.
Stage 6: adds Greedy as a second engine, plus timing and an independent
conflict verifier, so the two algorithms can be honestly compared.

This file deliberately does its job in clearly separate steps, so that if
something goes wrong you know exactly which step to check:

  1. build_sessions()        Database rows  -> list of session dicts
  2. run_engine()             session dicts  -> a named C++ engine -> colors + timing
  3. count_conflicts()        colors         -> independent check: any violations?
  4. build_timetable_rows()   colors         -> real TimeSlot objects, for display
  5. compare_algorithms()     runs both engines on the SAME sessions, for Stage 6's
                              comparison page

Each step's output is plain Python data (lists/dicts), so you can test any
step on its own in the Django shell without running the whole pipeline.
"""

import os
import subprocess
import tempfile
import time

from django.conf import settings

from .models import Subject, TimeSlot

CPP_ENGINE_DIR = os.path.join(settings.BASE_DIR, "cpp_engine")

# Every engine here reads the exact same input format (see graph_coloring.cpp
# and greedy.cpp) and writes the exact same output format, which is what
# makes an apples-to-apples comparison possible.
ENGINES = {
    "Graph Coloring": os.path.join(CPP_ENGINE_DIR, "graph_coloring_engine"),
    "Greedy": os.path.join(CPP_ENGINE_DIR, "greedy_engine"),
}

# Kept for backward compatibility with Stage 4's generate_timetable view.
ENGINE_PATH = ENGINES["Graph Coloring"]


def build_sessions():
    """
    Expand every Subject into one "session" per required hour per week.

    Stage 9 addition: if a subject's usual (first qualified) teacher is
    marked unavailable, automatically fall back to the next AVAILABLE
    qualified teacher for that subject, and record it as an informative
    (non-error) warning. This means every stage that calls build_sessions()
    - Generate Timetable, Compare Algorithms, Diagnose - automatically
    benefits from substitution, with no changes needed on their end.

    Returns:
        sessions: list of dicts, each {"subject": Subject, "teacher": Teacher}
                  The position of a dict in this list IS its session_id,
                  and must match the order written to the engine's input
                  file exactly - the engine only ever deals with plain
                  integer IDs (0, 1, 2, ...), not subject names.
        warnings: list of strings - either "skipped" problems, or
                  informative notes about an automatic substitution.
    """
    sessions = []
    warnings = []

    for subject in Subject.objects.select_related("division").prefetch_related("qualified_teachers").order_by("id"):
        qualified = list(subject.qualified_teachers.all())
        if not qualified:
            warnings.append(f"Skipped '{subject}': no qualified teacher assigned.")
            continue

        primary = qualified[0]

        if primary.is_available:
            chosen = primary
        else:
            substitute = next((t for t in qualified[1:] if t.is_available), None)
            if substitute is None:
                warnings.append(
                    f"Skipped '{subject}': primary teacher '{primary}' is unavailable and no "
                    f"other qualified teacher for this subject is currently available."
                )
                continue
            chosen = substitute
            warnings.append(
                f"Substitution: '{subject}' reassigned from unavailable '{primary}' to "
                f"'{chosen}' (also a qualified teacher for this subject, currently available)."
            )

        for _ in range(subject.hours_per_week):
            sessions.append({"subject": subject, "teacher": chosen})

    return sessions, warnings


def run_engine(engine_path, sessions):
    """
    Write `sessions` to a temp file in the shared input format, run the
    given compiled C++ engine on it, and parse its output. Used for BOTH
    Graph Coloring and Greedy - they are interchangeable at this level.

    Returns:
        colors: list of ints, colors[i] = time slot color assigned to
                sessions[i]. Same length and order as `sessions`.
        num_colors_used: total distinct time slots the engine needed.
        elapsed_ms: wall-clock time for the subprocess call itself, in
                    milliseconds. This is a genuine measurement, not an
                    estimate - it times only the engine's own run, not
                    Python's file writing/reading around it.
    """
    if not sessions:
        return [], 0, 0.0

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(f"{len(sessions)}\n")
        for s in sessions:
            f.write(f"{s['teacher'].id} {s['subject'].division_id}\n")
        input_path = f.name

    try:
        start = time.perf_counter()
        result = subprocess.run(
            [engine_path, input_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
    finally:
        os.remove(input_path)

    if result.returncode != 0:
        raise RuntimeError(f"{engine_path} failed: {result.stderr.strip()}")

    colors = [None] * len(sessions)
    for line in result.stdout.strip().splitlines():
        session_id_str, color_str = line.split()
        colors[int(session_id_str)] = int(color_str)

    num_colors_used = max(colors) + 1 if colors else 0

    return colors, num_colors_used, elapsed_ms


def run_graph_coloring(sessions):
    """Stage 4 compatibility wrapper: Graph Coloring only, no timing returned."""
    colors, num_colors_used, _elapsed_ms = run_engine(ENGINES["Graph Coloring"], sessions)
    return colors, num_colors_used


def count_conflicts(sessions, colors):
    """
    Independent verification, deliberately re-implemented from scratch
    rather than reusing engine logic: scan every PAIR of sessions and
    count how many conflicting pairs (same teacher or same division)
    were still given the same color. A correct algorithm must always
    return 0 here - this function does not trust the engines, it checks
    them.
    """
    n = len(sessions)
    violations = 0
    for i in range(n):
        for j in range(i + 1, n):
            same_teacher = sessions[i]["teacher"].id == sessions[j]["teacher"].id
            same_division = sessions[i]["subject"].division_id == sessions[j]["subject"].division_id
            if (same_teacher or same_division) and colors[i] == colors[j]:
                violations += 1
    return violations


def compare_algorithms():
    """
    Stage 6: run every engine in ENGINES on the SAME real session data,
    and return measured (not made-up) results for each.

    Returns:
        list of dicts: {name, num_slots_used, elapsed_ms, conflicts, num_sessions}
        warnings: from build_sessions()
    """
    sessions, warnings = build_sessions()
    results = []

    for name, engine_path in ENGINES.items():
        colors, num_colors_used, elapsed_ms = run_engine(engine_path, sessions)
        conflicts = count_conflicts(sessions, colors)
        results.append({
            "name": name,
            "num_sessions": len(sessions),
            "num_slots_used": num_colors_used,
            "elapsed_ms": round(elapsed_ms, 4),
            "conflicts": conflicts,
        })

    return results, warnings


def build_timetable_rows(sessions, colors):
    """
    Map each session's assigned color (0, 1, 2, ...) to a real TimeSlot
    row from the database, ordered by day then start time. Color 0 = the
    first TimeSlot, color 1 = the second, and so on.

    Returns:
        rows: list of dicts ready for the template: subject, division,
              teacher, time_slot (or None if we ran out of real slots).
        slot_shortage: True if more colors were used than TimeSlots exist.
    """
    available_slots = list(TimeSlot.objects.all())  # already ordered, see Meta.ordering
    slot_shortage = False

    rows = []
    for session, color in zip(sessions, colors):
        if color < len(available_slots):
            time_slot = available_slots[color]
        else:
            time_slot = None
            slot_shortage = True

        rows.append({
            "subject": session["subject"],
            "division": session["subject"].division,
            "teacher": session["teacher"],
            "time_slot": time_slot,
        })

    return rows, slot_shortage


BACKTRACKING_ENGINE = os.path.join(CPP_ENGINE_DIR, "backtracking_engine")
BACKTRACKING_TIME_LIMIT_SECONDS = 5


def find_clique_bottlenecks(sessions, num_available_slots):
    """
    Stage 8: fast, EXACT infeasibility check - no search required.

    Every session taught by the same teacher conflicts with every other
    session that teacher teaches (that's a clique - Stage 3). A clique
    of size m needs at least m distinct time slots, full stop, no matter
    which algorithm is used. The same is true for every division's total
    sessions. So if any teacher or division alone needs more sessions
    than we have time slots, we can PROVE scheduling is impossible,
    instantly, and say exactly why.

    This is a *necessary* condition, not a sufficient one: passing this
    check does not guarantee a schedule exists (other, more tangled
    combinations of conflicts could still make it impossible) - it only
    catches the simple, common, and easy-to-explain cases. That's why
    the caller falls back to actual Backtracking search when this
    passes but a definitive answer is still needed.

    Returns:
        bottlenecks: list of human-readable explanation strings. Empty
                     list means no simple bottleneck was found (not the
                     same as "definitely feasible" - see docstring above).
    """
    teacher_counts = {}
    teacher_names = {}
    teacher_subjects = {}   # teacher_id -> set of "CODE - Name (Division): H hrs/week" strings
    division_counts = {}
    division_names = {}
    division_subjects = {}  # division_id -> set of "CODE - Name: H hrs/week" strings

    for s in sessions:
        t = s["teacher"]
        subj = s["subject"]

        teacher_counts[t.id] = teacher_counts.get(t.id, 0) + 1
        teacher_names[t.id] = t.name
        teacher_subjects.setdefault(t.id, set()).add(
            f"{subj.code} - {subj.name} ({subj.division}): {subj.hours_per_week} hrs/week"
        )

        d = subj.division
        division_counts[d.id] = division_counts.get(d.id, 0) + 1
        division_names[d.id] = d.name
        division_subjects.setdefault(d.id, set()).add(
            f"{subj.code} - {subj.name}: {subj.hours_per_week} hrs/week"
        )

    bottlenecks = []

    for teacher_id, count in teacher_counts.items():
        if count > num_available_slots:
            breakdown = "; ".join(sorted(teacher_subjects[teacher_id]))
            bottlenecks.append(
                f"Teacher '{teacher_names[teacher_id]}' is assigned {count} sessions per week, "
                f"but only {num_available_slots} time slot(s) exist in total. Since one teacher "
                f"cannot teach two sessions at once, this is impossible regardless of algorithm. "
                f"Breakdown - {breakdown}. "
                f"Fix: add at least {count - num_available_slots} more Time Slot(s), reduce this "
                f"teacher's hours_per_week on some subject, or assign another qualified teacher."
            )

    for division_id, count in division_counts.items():
        if count > num_available_slots:
            breakdown = "; ".join(sorted(division_subjects[division_id]))
            bottlenecks.append(
                f"Division '{division_names[division_id]}' requires {count} sessions per week, "
                f"but only {num_available_slots} time slot(s) exist in total. Since a division "
                f"cannot attend two sessions at once, this is impossible regardless of algorithm. "
                f"Breakdown - {breakdown}. "
                f"Fix: add at least {count - num_available_slots} more Time Slot(s), or reduce "
                f"hours_per_week on one of this division's subjects."
            )

    return bottlenecks


def run_backtracking(sessions, num_available_slots, time_limit_seconds=BACKTRACKING_TIME_LIMIT_SECONDS):
    """
    Run the Backtracking engine with a HARD time limit - Stage 7 proved
    this search can take millions of steps or longer, so we never let it
    run unbounded inside a web request.

    Returns a dict:
        {"outcome": "FEASIBLE", "backtracking_calls": int}
        {"outcome": "INFEASIBLE", "backtracking_calls": int}
        {"outcome": "TIMED_OUT"}
    """
    if not sessions:
        return {"outcome": "FEASIBLE", "backtracking_calls": 0}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(f"{len(sessions)}\n")
        for s in sessions:
            f.write(f"{s['teacher'].id} {s['subject'].division_id}\n")
        input_path = f.name

    try:
        result = subprocess.run(
            [BACKTRACKING_ENGINE, input_path, str(num_available_slots)],
            capture_output=True,
            text=True,
            timeout=time_limit_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "TIMED_OUT"}
    finally:
        os.remove(input_path)

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # backtracking.cpp always prints "... calls: N" on stderr - pull N out.
    calls = None
    if "calls:" in stderr:
        calls = int(stderr.rsplit("calls:", 1)[1].strip())

    if stdout == "FAILURE":
        return {"outcome": "INFEASIBLE", "backtracking_calls": calls}
    else:
        return {"outcome": "FEASIBLE", "backtracking_calls": calls}


def diagnose_schedulability():
    """
    Stage 8: the full explanation pipeline.

        1. Build real sessions from the database (same as every other stage).
        2. Fast, exact check: any single teacher/division alone impossible? (no search)
        3. Only if that check passes: run time-limited Backtracking for a
           real yes/no answer, being honest if even that runs out of time.

    Returns a dict for the template:
        {
            "num_sessions": int,
            "num_slots": int,
            "bottlenecks": [str, ...],          # from the fast check
            "backtracking_outcome": str or None, # "FEASIBLE" / "INFEASIBLE" / "TIMED_OUT" / None (skipped)
            "backtracking_calls": int or None,
        }
    """
    sessions, warnings = build_sessions()
    num_slots = TimeSlot.objects.count()

    bottlenecks = find_clique_bottlenecks(sessions, num_slots)

    backtracking_outcome = None
    backtracking_calls = None

    if not bottlenecks:
        # The fast check found nothing - ask Backtracking for a definitive answer.
        bt_result = run_backtracking(sessions, num_slots)
        backtracking_outcome = bt_result["outcome"]
        backtracking_calls = bt_result.get("backtracking_calls")

    return {
        "num_sessions": len(sessions),
        "num_slots": num_slots,
        "warnings": warnings,
        "bottlenecks": bottlenecks,
        "backtracking_outcome": backtracking_outcome,
        "backtracking_calls": backtracking_calls,
    }
