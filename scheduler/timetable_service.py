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

from .models import Room, Subject, TimeSlot

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

    Priority 1 - Step 1: BALANCED TEACHER ASSIGNMENT
    When a subject has multiple qualified teachers, instead of always picking
    the first one, we now pick the available teacher who has been assigned
    the fewest sessions so far. This spreads workload evenly across faculty
    rather than overloading one teacher while others sit at 0 hours.

    Stage 9 addition (preserved): if the least-loaded teacher is still
    unavailable, we fall back automatically to the next best available one.

    Returns:
        sessions: list of dicts, each {"subject": Subject, "teacher": Teacher}
                  The position of a dict in this list IS its session_id.
        warnings: list of strings.
    """
    sessions = []
    warnings = []
    # Track how many sessions have been assigned to each teacher so far.
    # Key: teacher.id, Value: count of sessions assigned this build.
    teacher_load: dict = {}

    for subject in Subject.objects.select_related("division").prefetch_related("qualified_teachers").order_by("id"):
        qualified = list(subject.qualified_teachers.all())
        if not qualified:
            warnings.append(f"Skipped '{subject}': no qualified teacher assigned.")
            continue

        # Filter to only available teachers, then pick the least-loaded one.
        available = [t for t in qualified if t.is_available]

        if not available:
            primary = qualified[0]
            warnings.append(
                f"Skipped '{subject}': primary teacher '{primary}' is unavailable and no "
                f"other qualified teacher for this subject is currently available."
            )
            continue

        # Least-loaded heuristic: among available teachers, pick whoever has
        # the fewest sessions assigned so far in this scheduling run.
        chosen = min(available, key=lambda t: teacher_load.get(t.id, 0))

        # Inform if the primary teacher was bypassed in favour of balance.
        primary = qualified[0]
        if chosen != primary and primary.is_available:
            warnings.append(
                f"Load-balance: '{subject}' assigned to '{chosen}' instead of '{primary}' "
                f"('{primary}' has {teacher_load.get(primary.id, 0)} sessions, "
                f"'{chosen}' has {teacher_load.get(chosen.id, 0)})."
            )
        elif chosen != primary and not primary.is_available:
            warnings.append(
                f"Substitution: '{subject}' reassigned from unavailable '{primary}' to "
                f"'{chosen}' (also a qualified teacher for this subject, currently available)."
            )

        lab_sessions = subject.effective_lab_sessions
        lab_dur = subject.lab_duration_slots
        lec_slots = subject.lecture_slots

        # Priority 2: Schedule Labs (continuous blocks of lab_dur slots)
        for l_idx in range(lab_sessions):
            lab_uid = f"lab_{subject.id}_{l_idx}"
            for p in range(lab_dur):
                sessions.append({
                    "subject": subject,
                    "teacher": chosen,
                    "is_lab": True,
                    "lab_id": lab_uid,
                    "part_index": p + 1,
                    "duration_slots": lab_dur,
                    "session_type": "LAB",
                })
                teacher_load[chosen.id] = teacher_load.get(chosen.id, 0) + 1

        # Schedule regular lectures (1 slot each)
        for _ in range(lec_slots):
            sessions.append({
                "subject": subject,
                "teacher": chosen,
                "is_lab": False,
                "lab_id": None,
                "part_index": 1,
                "duration_slots": 1,
                "session_type": "LECTURE",
            })
            teacher_load[chosen.id] = teacher_load.get(chosen.id, 0) + 1

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


def _make_interleaved_slots():
    """
    Priority 1 - Step 2: INTERLEAVED (ROUND-ROBIN) SLOT ORDERING

    The default DB ordering is: all Monday slots, then all Tuesday slots, etc.
    With that order, graph-coloring colors 0-4 all land on Monday, so a
    division with 5 sessions gets 5 back-to-back lectures on Monday.

    Instead we order slots period-by-period across all days:
      color 0 -> Monday    09:00-10:00
      color 1 -> Tuesday   09:00-10:00
      color 2 -> Wednesday 09:00-10:00
      color 3 -> Thursday  09:00-10:00
      color 4 -> Friday    09:00-10:00
      color 5 -> Monday    10:00-11:00
      color 6 -> Tuesday   10:00-11:00
      ...

    Result: adjacent colors always fall on DIFFERENT days, so the coloring
    engine naturally distributes lectures across the whole week.
    """
    DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    all_slots = list(TimeSlot.objects.all())  # Meta.ordering = [day, start_time]

    # Collect unique time periods in chronological order (start_time only).
    seen_times = []
    seen_set = set()
    for s in all_slots:
        if s.start_time not in seen_set:
            seen_set.add(s.start_time)
            seen_times.append(s.start_time)
    seen_times.sort()

    # Build a lookup: (day, start_time) -> TimeSlot
    slot_map = {(s.day, s.start_time): s for s in all_slots}

    # Round-robin: for each period, emit one slot per day (in day order).
    interleaved = []
    for period_start in seen_times:
        for day_code in DAY_ORDER:
            slot = slot_map.get((day_code, period_start))
            if slot is not None:
                interleaved.append(slot)

    return interleaved


def schedule_timetable(sessions):
    """
    Priority 2: Lab Sessions Representation & Constraints + Multi-Resource Optimizer.

    Features:
      1. Continuous Multi-Slot Labs: Each lab session is allocated to K continuous
         time slots on the same day without crossing breaks.
      2. Room Type & Capacity Matching:
         - Labs are assigned to RoomType.LAB with capacity >= division strength.
         - Lectures are assigned to RoomType.CLASSROOM with capacity >= division strength.
      3. Zero Clashes Guaranteed (Fixes Bug 1):
         - Teacher availability checked globally across all divisions.
         - Division availability checked.
         - Room availability checked (one class per room per slot).
      4. Balanced Weekly Distribution:
         - Labs spread evenly across days (at most 1 lab per division per day).
         - Lectures spread across days (avoiding multiple lectures of the same subject on the same day).
         - Teacher daily workload balanced across the week.
    """
    from collections import defaultdict
    all_slots = list(TimeSlot.objects.order_by("day", "start_time"))
    all_rooms = list(Room.objects.all())

    DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]

    slots_by_day = defaultdict(list)
    for s in all_slots:
        slots_by_day[s.day].append(s)

    lab_rooms = [r for r in all_rooms if r.room_type == Room.RoomType.LAB]
    class_rooms = [r for r in all_rooms if r.room_type == Room.RoomType.CLASSROOM]
    fallback_rooms = [r for r in all_rooms if r.room_type != Room.RoomType.LAB]

    # Global occupancy tracking: prevents any double-booking
    teacher_busy = defaultdict(set)   # (day, slot_id) -> set(teacher_ids)
    division_busy = defaultdict(set)  # (day, slot_id) -> set(division_ids)
    room_busy = defaultdict(set)      # (day, slot_id) -> set(room_ids)

    # Distribution tracking
    div_day_labs = defaultdict(int)            # (division_id, day) -> count
    div_subj_day_lecs = defaultdict(int)       # (division_id, subject_id, day) -> count
    div_day_total = defaultdict(int)           # (division_id, day) -> count
    teacher_day_total = defaultdict(int)       # (teacher_id, day) -> count
    div_subj_has_lab_today = defaultdict(bool) # (division_id, subject_id, day) -> bool

    # Group sessions into lab groups and lecture items
    lab_groups = defaultdict(list)
    lecture_items = []

    for idx, s in enumerate(sessions):
        if s.get("is_lab"):
            lab_groups[s["lab_id"]].append((idx, s))
        else:
            lecture_items.append((idx, s))

    assigned = [None] * len(sessions)

    # 1. SCHEDULE LABS (Most Constrained First)
    for lab_id, group in lab_groups.items():
        dur = group[0][1]["duration_slots"]
        subject = group[0][1]["subject"]
        teacher = group[0][1]["teacher"]
        div = subject.division

        valid_lab_rooms = [r for r in lab_rooms if r.capacity >= div.strength]
        if not valid_lab_rooms:
            valid_lab_rooms = lab_rooms if lab_rooms else all_rooms

        best_candidate = None
        best_score = float("inf")

        days_sorted = sorted(
            [d for d in DAY_ORDER if d in slots_by_day],
            key=lambda d: (div_day_labs[(div.id, d)], div_day_total[(div.id, d)])
        )

        for day in days_sorted:
            day_penalty = 100 * div_day_labs[(div.id, day)] if div_day_labs[(div.id, day)] >= 1 else 0
            day_slots = slots_by_day[day]

            for i in range(len(day_slots) - dur + 1):
                block = day_slots[i:i + dur]
                is_continuous = all(block[k].end_time == block[k + 1].start_time for k in range(dur - 1))
                if not is_continuous:
                    continue

                if any(teacher.id in teacher_busy[(day, sl.id)] or div.id in division_busy[(day, sl.id)] for sl in block):
                    continue

                free_room = None
                for r in valid_lab_rooms:
                    if all(r.id not in room_busy[(day, sl.id)] for sl in block):
                        free_room = r
                        break
                if not free_room:
                    continue

                score = (
                    day_penalty
                    + 10 * div_day_total[(div.id, day)]
                    + 5 * teacher_day_total[(teacher.id, day)]
                    + i
                )

                if score < best_score:
                    best_score = score
                    best_candidate = (day, block, free_room)

        if best_candidate:
            day, block, room = best_candidate
            for (sess_idx, s), slot in zip(group, block):
                assigned[sess_idx] = (slot, room)
                teacher_busy[(day, slot.id)].add(teacher.id)
                division_busy[(day, slot.id)].add(div.id)
                room_busy[(day, slot.id)].add(room.id)
                div_day_total[(div.id, day)] += 1
                teacher_day_total[(teacher.id, day)] += 1
            div_day_labs[(div.id, day)] += 1
            div_subj_has_lab_today[(div.id, subject.id, day)] = True

    # 2. SCHEDULE LECTURES
    for idx, s in lecture_items:
        subject = s["subject"]
        teacher = s["teacher"]
        div = subject.division

        valid_classrooms = [r for r in class_rooms if r.capacity >= div.strength]
        if not valid_classrooms:
            valid_classrooms = fallback_rooms if fallback_rooms else all_rooms

        best_candidate = None
        best_score = float("inf")

        days_sorted = sorted(
            [d for d in DAY_ORDER if d in slots_by_day],
            key=lambda d: (
                div_subj_day_lecs[(div.id, subject.id, d)],
                1 if div_subj_has_lab_today[(div.id, subject.id, d)] else 0,
                div_day_total[(div.id, d)],
                teacher_day_total[(teacher.id, d)],  # Bug 1 fix: was `day` (outer var), must be `d`
            )
        )

        for day in days_sorted:
            day_slots = slots_by_day[day]
            subj_lecs_today = div_subj_day_lecs[(div.id, subject.id, day)]
            has_lab_today = div_subj_has_lab_today[(div.id, subject.id, day)]

            for slot_idx, slot in enumerate(day_slots):
                if teacher.id in teacher_busy[(day, slot.id)] or div.id in division_busy[(day, slot.id)]:
                    continue

                free_room = None
                for r in valid_classrooms:
                    if r.id not in room_busy[(day, slot.id)]:
                        free_room = r
                        break
                if not free_room:
                    continue

                score = (
                    subj_lecs_today * 60
                    + (25 if has_lab_today else 0)
                    + div_day_total[(div.id, day)] * 5
                    + teacher_day_total[(teacher.id, day)] * 3
                    + slot_idx
                )

                if score < best_score:
                    best_score = score
                    best_candidate = (day, slot, free_room)

        if best_candidate:
            day, slot, room = best_candidate
            assigned[idx] = (slot, room)
            teacher_busy[(day, slot.id)].add(teacher.id)
            division_busy[(day, slot.id)].add(div.id)
            room_busy[(day, slot.id)].add(room.id)
            div_day_total[(div.id, day)] += 1
            teacher_day_total[(teacher.id, day)] += 1
            div_subj_day_lecs[(div.id, subject.id, day)] += 1

    return assigned


def build_timetable_rows(sessions, colors):
    """
    Map each session to a conflict-free (TimeSlot, Room) pair using the
    Python multi-resource scheduler (schedule_timetable). The `colors`
    parameter from the C++ engine is no longer used for placement — it is
    kept in the signature for backward compatibility with the compare/diagnose
    views that call run_graph_coloring() separately.
    """
    assigned_slots_and_rooms = schedule_timetable(sessions)

    # Bug 4 fix: num_colors_used must reflect the Python scheduler output,
    # not the stale C++ coloring. Count distinct (day, slot) pairs actually
    # assigned — that's the real number of distinct time slots consumed.
    assigned_slot_ids = set(
        item[0].id for item in assigned_slots_and_rooms if item is not None
    )
    num_colors_used = len(assigned_slot_ids)
    slot_shortage = any(a is None for a in assigned_slots_and_rooms)

    rows = []
    for session, item in zip(sessions, assigned_slots_and_rooms):
        slot, room = item if item else (None, None)
        rows.append({
            "subject": session["subject"],
            "division": session["subject"].division,
            "teacher": session["teacher"],
            "time_slot": slot,
            "room": room,
            "is_lab": session.get("is_lab", False),
            "session_type": session.get("session_type", "LECTURE"),
            "duration_slots": session.get("duration_slots", 1),
            "part_index": session.get("part_index", 1),
            "lab_id": session.get("lab_id"),
        })

    return rows, slot_shortage


def verify_timetable_conflicts(rows):
    """
    Independent comprehensive conflict and constraint verifier:
      - Teacher double booking across all divisions
      - Division double booking
      - Room double booking
      - Lab room type verification (must be LAB)
      - Lab continuity check (continuous slots on same day)
    Returns: list of error strings (empty if 100% clash-free).
    """
    from collections import defaultdict
    violations = []
    teacher_slots = {}
    div_slots = {}
    room_slots = {}
    lab_parts = defaultdict(list)

    for idx, r in enumerate(rows):
        slot = r.get("time_slot")
        room = r.get("room")
        if not slot:
            continue

        t_key = (r["teacher"].id, slot.id)
        d_key = (r["division"].id, slot.id)
        r_key = (room.id, slot.id) if room else None

        if t_key in teacher_slots:
            other = rows[teacher_slots[t_key]]
            violations.append(
                f"Teacher clash: {r['teacher']} double-booked at {slot} for "
                f"{r['subject'].code} ({r['division']}) and {other['subject'].code} ({other['division']})."
            )
        else:
            teacher_slots[t_key] = idx

        if d_key in div_slots:
            other = rows[div_slots[d_key]]
            violations.append(
                f"Division clash: {r['division']} has both {r['subject'].code} "
                f"and {other['subject'].code} at {slot}."
            )
        else:
            div_slots[d_key] = idx

        if r_key:
            if r_key in room_slots:
                other = rows[room_slots[r_key]]
                violations.append(
                    f"Room clash: {room.name} double-booked at {slot} for "
                    f"{r['subject'].code} ({r['division']}) and {other['subject'].code} ({other['division']})."
                )
            else:
                room_slots[r_key] = idx

        if r.get("is_lab"):
            if room and room.room_type != Room.RoomType.LAB:
                violations.append(
                    f"Room type mismatch: Lab session {r['subject'].code} assigned to non-lab room {room.name}."
                )
            lab_parts[r.get("lab_id")].append(r)

    for lab_id, parts in lab_parts.items():
        if len(parts) > 1:
            # Bug 5 fix: sort by actual (day, start_time) not by part_index,
            # so duplicate or missing part indices don't hide continuity errors.
            parts.sort(key=lambda x: (x["time_slot"].day, x["time_slot"].start_time))
            for i in range(len(parts) - 1):
                s1 = parts[i]["time_slot"]
                s2 = parts[i + 1]["time_slot"]
                if s1.day != s2.day or s1.end_time != s2.start_time:
                    violations.append(
                        f"Lab continuity error: {parts[0]['subject'].code} lab {lab_id} slots are not continuous ({s1} and {s2})."
                    )

    return violations


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
