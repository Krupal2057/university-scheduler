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

    Returns:
        sessions: list of dicts, each {"subject": Subject, "teacher": Teacher}
                  The position of a dict in this list IS its session_id,
                  and must match the order written to the engine's input
                  file exactly - the engine only ever deals with plain
                  integer IDs (0, 1, 2, ...), not subject names.
        warnings: list of strings describing subjects we had to skip.
    """
    sessions = []
    warnings = []

    for subject in Subject.objects.select_related("division").prefetch_related("qualified_teachers"):
        teacher = subject.qualified_teachers.first()
        if teacher is None:
            warnings.append(
                f"Skipped '{subject}': no qualified teacher assigned."
            )
            continue

        for _ in range(subject.hours_per_week):
            sessions.append({"subject": subject, "teacher": teacher})

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
