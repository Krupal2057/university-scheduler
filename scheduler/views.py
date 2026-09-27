import os
import subprocess

from django.conf import settings
from django.shortcuts import render

from .timetable_service import build_sessions, build_timetable_rows, compare_algorithms, run_graph_coloring


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
    sessions, warnings = build_sessions()

    try:
        colors, num_colors_used = run_graph_coloring(sessions)
    except RuntimeError as exc:
        warnings.append(str(exc))
        colors, num_colors_used = [], 0

    rows, slot_shortage = build_timetable_rows(sessions, colors)

    if slot_shortage:
        warnings.append(
            f"The algorithm needed {num_colors_used} distinct time slots, but "
            f"fewer than that exist in the database. Add more Time Slots in "
            f"the admin panel. Rows below with a blank time slot could not "
            f"be placed."
        )

    return render(request, "scheduler/timetable.html", {
        "rows": rows,
        "warnings": warnings,
        "num_sessions": len(sessions),
        "num_colors_used": num_colors_used,
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
