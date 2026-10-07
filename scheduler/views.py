import os
import subprocess

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import DivisionForm, RoomForm, SubjectForm, TeacherForm, TimeSlotForm
from .models import Division, Room, Subject, Teacher, TimeSlot
from .models import Subject as SubjectModel
from .substitution_service import suggest_teacher_substitutes
from .timetable_service import (
    build_sessions,
    build_timetable_rows,
    compare_algorithms,
    diagnose_schedulability,
    run_graph_coloring,
    verify_timetable_conflicts,
)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _is_admin(request):
    return request.session.get("site_admin", False)


def _require_admin(request):
    """Return a redirect to the current page with the login modal open if not admin."""
    if not _is_admin(request):
        messages.error(request, "You must be logged in as admin to do that.")
        return False
    return True


# ─────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────

def site_login(request):
    if request.method == "POST":
        pw = request.POST.get("password", "")
        next_url = request.POST.get("next", "/")
        if pw == settings.SITE_ADMIN_PASSWORD:
            request.session["site_admin"] = True
            messages.success(request, "Admin mode enabled. You can now create, edit, and delete records.")
            return redirect(next_url)
        else:
            messages.error(request, "Incorrect password.")
            return redirect(next_url)
    return redirect("/")


def site_logout(request):
    if request.method == "POST":
        request.session.pop("site_admin", None)
        messages.success(request, "Logged out of admin mode.")
    return redirect("/")


# ─────────────────────────────────────────────────────────────
# Home / Dashboard
# ─────────────────────────────────────────────────────────────

def home(request):
    engine_path = os.path.join(settings.BASE_DIR, "cpp_engine", "engine")
    try:
        result = subprocess.run([engine_path], capture_output=True, text=True, timeout=5)
        cpp_status = "connected"
        cpp_message = result.stdout.strip()
    except FileNotFoundError:
        cpp_status = "not built"
        cpp_message = "run: g++ -O2 -o cpp_engine/engine cpp_engine/main.cpp"
    except Exception as exc:
        cpp_status = "error"
        cpp_message = str(exc)

    stats = {
        "divisions": Division.objects.count(),
        "teachers": Teacher.objects.count(),
        "subjects": Subject.objects.count(),
        "rooms": Room.objects.count(),
        "timeslots": TimeSlot.objects.count(),
    }
    return render(request, "scheduler/home.html", {
        "cpp_status": cpp_status,
        "cpp_message": cpp_message,
        "stats": stats,
    })


# ─────────────────────────────────────────────────────────────
# Timetable Generation
# ─────────────────────────────────────────────────────────────

def generate_timetable(request):
    from collections import OrderedDict

    sessions, warnings = build_sessions()

    try:
        colors, num_colors_used = run_graph_coloring(sessions)
    except RuntimeError as exc:
        warnings.append(str(exc))
        colors, num_colors_used = [], 0

    rows, slot_shortage, satisfaction = build_timetable_rows(sessions, colors)

    if slot_shortage:
        unplaced = sum(1 for r in rows if r.get("time_slot") is None)
        warnings.append(
            f"{unplaced} session(s) could not be placed — not enough free time slots exist. "
            f"Add more Time Slots or reduce subject hours."
        )

    DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    DAY_LABELS = {
        "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
        "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday",
    }

    used_slots = []
    seen = set()
    for row in rows:
        ts = row.get("time_slot")
        if ts and (ts.day, ts.start_time, ts.end_time) not in seen:
            seen.add((ts.day, ts.start_time, ts.end_time))
            used_slots.append(ts)
    used_slots.sort(key=lambda s: (DAY_ORDER.index(s.day) if s.day in DAY_ORDER else 99, s.start_time))

    time_labels = []
    seen_times = set()
    for ts in used_slots:
        label = f"{ts.start_time.strftime('%H:%M')}-{ts.end_time.strftime('%H:%M')}"
        if label not in seen_times:
            seen_times.add(label)
            time_labels.append(label)

    used_day_codes = []
    seen_days = set()
    for ts in used_slots:
        if ts.day not in seen_days:
            seen_days.add(ts.day)
            used_day_codes.append(ts.day)
    used_day_codes.sort(key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99)
    day_labels_ordered = [DAY_LABELS.get(d, d) for d in used_day_codes]

    divisions_seen = OrderedDict()
    for row in rows:
        div_name = str(row["division"])
        if div_name not in divisions_seen:
            divisions_seen[div_name] = []
        divisions_seen[div_name].append(row)

    grid_by_division = []
    for div_name, div_rows in divisions_seen.items():
        day_index = {dl: i for i, dl in enumerate(day_labels_ordered)}
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

        grid_rows = [(tl, raw_grid[tl]) for tl in time_labels]
        div_obj = div_rows[0]["division"]
        div_sat = satisfaction.get(div_obj.id, {})

        grid_by_division.append({
            "division": div_name,
            "days": day_labels_ordered,
            "grid_rows": grid_rows,
            "satisfaction": div_sat,
        })

    timetable_violations = verify_timetable_conflicts(rows)
    for v in timetable_violations:
        warnings.append(f"Conflict: {v}")

    num_labs = len(set(r["lab_id"] for r in rows if r.get("is_lab") and r.get("lab_id")))
    num_lectures = sum(1 for r in rows if not r.get("is_lab"))
    satisfaction_list = sorted(satisfaction.values(), key=lambda x: x.get("priority", 0), reverse=True)

    return render(request, "scheduler/timetable.html", {
        "rows": rows,
        "warnings": warnings,
        "num_sessions": len(sessions),
        "num_colors_used": num_colors_used,
        "num_labs": num_labs,
        "num_lectures": num_lectures,
        "grid_by_division": grid_by_division,
        "timetable_violations": timetable_violations,
        "satisfaction_list": satisfaction_list,
    })


# ─────────────────────────────────────────────────────────────
# Compare / Diagnose / Substitute  (unchanged logic, new template)
# ─────────────────────────────────────────────────────────────

def compare_view(request):
    results, warnings = compare_algorithms()
    return render(request, "scheduler/compare.html", {"results": results, "warnings": warnings})


def diagnose_view(request):
    diagnosis = diagnose_schedulability()
    return render(request, "scheduler/diagnose.html", diagnosis)


def substitute_view(request):
    all_subjects = SubjectModel.objects.select_related("division").order_by("division__name", "code")
    subject_id = request.GET.get("subject_id")
    result = None
    if subject_id:
        result = suggest_teacher_substitutes(subject_id)
    return render(request, "scheduler/substitute.html", {
        "all_subjects": all_subjects,
        "selected_subject_id": subject_id,
        "result": result,
    })


# ─────────────────────────────────────────────────────────────
# Data Management — generic helpers
# ─────────────────────────────────────────────────────────────

def _data_list(request, model, form_class, template, extra_ctx=None):
    """Generic list + inline-create view."""
    objects = model.objects.all()
    form = form_class()
    if request.method == "POST":
        if not _require_admin(request):
            return redirect(request.path)
        form = form_class(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"{model.__name__} created successfully.")
            return redirect(request.path)
    ctx = {"objects": objects, "form": form}
    if extra_ctx:
        ctx.update(extra_ctx)
    return render(request, template, ctx)


def _data_edit(request, model, form_class, pk, redirect_url, template):
    """Generic edit view."""
    obj = get_object_or_404(model, pk=pk)
    if not _is_admin(request):
        messages.error(request, "Admin login required to edit records.")
        return redirect(redirect_url)
    form = form_class(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{model.__name__} updated successfully.")
        return redirect(redirect_url)
    return render(request, template, {"form": form, "obj": obj})


def _data_delete(request, model, pk, redirect_url):
    """Generic delete view (POST only)."""
    if not _require_admin(request):
        return redirect(redirect_url)
    obj = get_object_or_404(model, pk=pk)
    if request.method == "POST":
        name = str(obj)
        obj.delete()
        messages.success(request, f"Deleted: {name}")
    return redirect(redirect_url)


# ─────────────────────────────────────────────────────────────
# Divisions
# ─────────────────────────────────────────────────────────────

def data_divisions(request):
    return _data_list(request, Division, DivisionForm, "scheduler/data/divisions.html")


def data_division_edit(request, pk):
    return _data_edit(request, Division, DivisionForm, pk,
                      redirect_url="/data/divisions/",
                      template="scheduler/data/division_form.html")


def data_division_delete(request, pk):
    return _data_delete(request, Division, pk, redirect_url="/data/divisions/")


# ─────────────────────────────────────────────────────────────
# Teachers
# ─────────────────────────────────────────────────────────────

def data_teachers(request):
    return _data_list(request, Teacher, TeacherForm, "scheduler/data/teachers.html")


def data_teacher_edit(request, pk):
    return _data_edit(request, Teacher, TeacherForm, pk,
                      redirect_url="/data/teachers/",
                      template="scheduler/data/teacher_form.html")


def data_teacher_delete(request, pk):
    return _data_delete(request, Teacher, pk, redirect_url="/data/teachers/")


# ─────────────────────────────────────────────────────────────
# Subjects
# ─────────────────────────────────────────────────────────────

def data_subjects(request):
    objects = Subject.objects.select_related("division").prefetch_related("qualified_teachers")
    form = SubjectForm()
    if request.method == "POST":
        if not _require_admin(request):
            return redirect(request.path)
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Subject created successfully.")
            return redirect(request.path)
    return render(request, "scheduler/data/subjects.html", {"objects": objects, "form": form})


def data_subject_edit(request, pk):
    return _data_edit(request, Subject, SubjectForm, pk,
                      redirect_url="/data/subjects/",
                      template="scheduler/data/subject_form.html")


def data_subject_delete(request, pk):
    return _data_delete(request, Subject, pk, redirect_url="/data/subjects/")


# ─────────────────────────────────────────────────────────────
# Rooms
# ─────────────────────────────────────────────────────────────

def data_rooms(request):
    return _data_list(request, Room, RoomForm, "scheduler/data/rooms.html")


def data_room_edit(request, pk):
    return _data_edit(request, Room, RoomForm, pk,
                      redirect_url="/data/rooms/",
                      template="scheduler/data/room_form.html")


def data_room_delete(request, pk):
    return _data_delete(request, Room, pk, redirect_url="/data/rooms/")


# ─────────────────────────────────────────────────────────────
# Time Slots
# ─────────────────────────────────────────────────────────────

def data_timeslots(request):
    return _data_list(request, TimeSlot, TimeSlotForm, "scheduler/data/timeslots.html")


def data_timeslot_edit(request, pk):
    return _data_edit(request, TimeSlot, TimeSlotForm, pk,
                      redirect_url="/data/timeslots/",
                      template="scheduler/data/timeslot_form.html")


def data_timeslot_delete(request, pk):
    return _data_delete(request, TimeSlot, pk, redirect_url="/data/timeslots/")
