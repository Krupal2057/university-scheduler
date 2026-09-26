"""
scheduler/timetable_service.py

Stage 4: connects the real database to the Graph Coloring C++ engine.

This file deliberately does ONE job end-to-end, in three clearly separate
steps, so that if something goes wrong you know exactly which step to
check:

  1. build_sessions()        Database rows  -> list of session dicts
  2. run_graph_coloring()    session dicts  -> C++ engine -> color per session
  3. build_timetable_rows()  colors         -> real TimeSlot objects, for display

Each step's output is plain Python data (lists/dicts), so you can test any
step on its own in the Django shell without running the whole pipeline.
"""

import os
import subprocess
import tempfile

from django.conf import settings

from .models import Subject, TimeSlot

ENGINE_PATH = os.path.join(settings.BASE_DIR, "cpp_engine", "graph_coloring_engine")


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


def run_graph_coloring(sessions):
    """
    Write `sessions` to a temp file in the engine's input format, run the
    compiled C++ engine on it, and parse its output.

    Returns:
        colors: list of ints, colors[i] = time slot color assigned to
                sessions[i]. Same length and order as `sessions`.
        num_colors_used: total distinct time slots the engine needed.
    """
    if not sessions:
        return [], 0

    # --- Step A: write the input file, exactly matching graph_coloring.cpp's
    # expected format: first line = count, then one "teacher_id division_id"
    # line per session, in the same order as the `sessions` list.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(f"{len(sessions)}\n")
        for s in sessions:
            f.write(f"{s['teacher'].id} {s['subject'].division_id}\n")
        input_path = f.name

    try:
        # --- Step B: run the compiled engine as a subprocess.
        result = subprocess.run(
            [ENGINE_PATH, input_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        os.remove(input_path)  # clean up the temp file either way

    if result.returncode != 0:
        raise RuntimeError(f"graph_coloring_engine failed: {result.stderr.strip()}")

    # --- Step C: parse "session_id assigned_slot" lines from stdout.
    colors = [None] * len(sessions)
    for line in result.stdout.strip().splitlines():
        session_id_str, color_str = line.split()
        colors[int(session_id_str)] = int(color_str)

    # The engine also prints "Total time slots used: N" to stderr.
    num_colors_used = max(colors) + 1 if colors else 0

    return colors, num_colors_used


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
