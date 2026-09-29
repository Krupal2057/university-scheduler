import os
import subprocess

from django.conf import settings
from django.shortcuts import render

from .models import Subject
from .substitution_service import suggest_teacher_substitutes
from .timetable_service import (
    build_sessions,
    build_timetable_rows,
    compare_algorithms,
    diagnose_schedulability,
    run_graph_coloring,
    verify_timetable_conflicts,
)


def home(request):
    """
    Stage 1 homepage.

    This view does two things:
      1. Renders the dashboard page.
      2. Calls the compiled C++ engine as a subprocess, to prove that
         Django and C++ can talk to each other. Later stages will send
         real scheduling data in and read a real schedule back out,
         using this exact same mechanism.
    """
    engine_path = os.path.join(settings.BASE_DIR, "cpp_engine", "engine")

    try:
        result = subprocess.run(
            [engine_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        cpp_status = "connected"
        cpp_message = result.stdout.strip()
    except FileNotFoundError:
        cpp_status = "not built yet"
        cpp_message = "run: g++ -O2 -o cpp_engine/engine cpp_engine/main.cpp"
    except Exception as exc:  # keep Stage 1 simple: show any error plainly
        cpp_status = "error"
        cpp_message = str(exc)

    return render(request, "scheduler/home.html", {
        "cpp_status": cpp_status,
        "cpp_message": cpp_message,
    })


def generate_timetable(request):
    """
    Stage 4: the real pipeline.

        Subjects/Teachers/Divisions in the database
            --> build_sessions()        (Python)
            --> run_graph_coloring()    (Python writes a file, C++ engine runs)
            --> build_timetable_rows()  (Python maps colors back to real TimeSlots)
            --> rendered as a table

    Kept as three separate function calls (not inlined) on purpose: if the
    page ever shows a wrong answer, you can reproduce and check each step
    by itself in `python manage.py shell`, e.g.:

        from scheduler.timetable_service import build_sessions
        sessions, warnings = build_sessions()
        print(sessions)
    """
    from collections import OrderedDict
    from .models import TimeSlot as TS

    sessions, warnings = build_sessions()

    try:
        colors, num_colors_used = run_graph_coloring(sessions)
    except RuntimeError as exc:
        warnings.append(str(exc))
        colors, num_colors_used = [], 0

    rows, slot_shortage = build_timetable_rows(sessions, colors)

    if slot_shortage:
        unplaced = sum(1 for r in rows if r.get("time_slot") is None)
        warnings.append(
            f"{unplaced} session(s) could not be placed — not enough free time slots exist "
            f"in the database after accounting for teacher, division, and room constraints. "
            f"Add more Time Slots in the admin panel, or reduce subject hours."
        )

    # ------------------------------------------------------------------ #
    # Build per-division weekly grid for the visual timetable view.        #
    # grid_by_division: list of                                            #
    #   { "division": str, "days": [day_label, ...],                      #
    #     "slots": [time_label, ...],                                      #
    #     "grid": { time_label: { day_label: cell | None } } }            #
    # ------------------------------------------------------------------ #
    DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    DAY_LABELS = {
        "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
        "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday",
    }

    # Collect all unique (day, start, end) combinations that actually appear
    used_slots = []
    seen = set()
    for row in rows:
        ts = row.get("time_slot")
        if ts and (ts.day, ts.start_time, ts.end_time) not in seen:
            seen.add((ts.day, ts.start_time, ts.end_time))
            used_slots.append(ts)
    # Sort: day order first, then start time
    used_slots.sort(key=lambda s: (DAY_ORDER.index(s.day) if s.day in DAY_ORDER else 99, s.start_time))

    # Unique time ranges (ignoring day) for rows of the grid
    time_labels = []
    seen_times = set()
    for ts in used_slots:
        label = f"{ts.start_time.strftime('%H:%M')}-{ts.end_time.strftime('%H:%M')}"
        if label not in seen_times:
            seen_times.add(label)
            time_labels.append(label)

    # Unique days that appear, in correct order
    used_day_codes = []
    seen_days = set()
    for ts in used_slots:
        if ts.day not in seen_days:
            seen_days.add(ts.day)
            used_day_codes.append(ts.day)
    used_day_codes.sort(key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99)
    day_labels_ordered = [DAY_LABELS.get(d, d) for d in used_day_codes]

    # Group rows by division
    divisions_seen = OrderedDict()
    for row in rows:
        div_name = str(row["division"])
        if div_name not in divisions_seen:
            divisions_seen[div_name] = []
        divisions_seen[div_name].append(row)

    grid_by_division = []
    for div_name, div_rows in divisions_seen.items():
        # Build grid as 2-D list: grid_rows[i] = (slot_label, [cell|None, cell|None, ...])
        # where cells are indexed in the same order as day_labels_ordered.
        day_index = {dl: i for i, dl in enumerate(day_labels_ordered)}

        # Start with all cells empty
        raw_grid = {tl: [None] * len(day_labels_ordered) for tl in time_labels}

        for row in div_rows:
            ts = row.get("time_slot")
            if ts:
                tl = f"{ts.start_time.strftime('%H:%M')}-{ts.end_time.strftime('%H:%M')}"
                dl = DAY_LABELS.get(ts.day, ts.day)
                if tl in raw_grid and dl in day_index:
                    raw_grid[tl][day_index[dl]] = {
                        "subject_name": row["subject"].name,
                        "subject_code": row["subject"].code,
                        "teacher": str(row["teacher"]),
                        "room": row.get("room"),
                        "is_lab": row.get("is_lab", False),
                        "session_type": row.get("session_type", "LECTURE"),
                        "duration_slots": row.get("duration_slots", 1),
                        "part_index": row.get("part_index", 1),
                        "lab_id": row.get("lab_id"),
                    }

        # Convert to ordered list for the template
        grid_rows = [(tl, raw_grid[tl]) for tl in time_labels]

        grid_by_division.append({
            "division": div_name,
            "days": day_labels_ordered,
            "grid_rows": grid_rows,   # list of (slot_label, [cell|None, ...])
        })

    timetable_violations = verify_timetable_conflicts(rows)
    for v in timetable_violations:
        warnings.append(f"Conflict: {v}")

    num_labs = len(set(r["lab_id"] for r in rows if r.get("is_lab") and r.get("lab_id")))
    num_lectures = sum(1 for r in rows if not r.get("is_lab"))

    return render(request, "scheduler/timetable.html", {
        "rows": rows,
        "warnings": warnings,
        "num_sessions": len(sessions),
        "num_colors_used": num_colors_used,
        "num_labs": num_labs,
        "num_lectures": num_lectures,
        "grid_by_division": grid_by_division,
        "timetable_violations": timetable_violations,
    })


def compare_view(request):
    """
    Stage 6: run every algorithm in timetable_service.ENGINES on the SAME
    real database sessions, and show the measured results side by side.

    Nothing here is a hardcoded/assumed number - every value in the table
    comes from actually running the compiled C++ engines on your data
    (see compare_algorithms() and its docstring for exactly how).
    """
    results, warnings = compare_algorithms()

    return render(request, "scheduler/compare.html", {
        "results": results,
        "warnings": warnings,
    })


def diagnose_view(request):
    """
    Stage 8: "why did/would scheduling fail?" - see
    timetable_service.diagnose_schedulability() for the full explanation
    of the two-step approach (fast exact check, then time-limited search).
    """
    diagnosis = diagnose_schedulability()
    return render(request, "scheduler/diagnose.html", diagnosis)


def substitute_view(request):
    """
    Stage 9: pick any Subject, see who else could teach it if the
    currently assigned teacher became unavailable, and why.
    """
    all_subjects = Subject.objects.select_related("division").order_by("division__name", "code")

    subject_id = request.GET.get("subject_id")
    result = None
    if subject_id:
        result = suggest_teacher_substitutes(subject_id)

    return render(request, "scheduler/substitute.html", {
        "all_subjects": all_subjects,
        "selected_subject_id": subject_id,
        "result": result,
    })
