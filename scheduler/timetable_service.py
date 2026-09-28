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

        for _ in range(subject.hours_per_week):
            sessions.append({"subject": subject, "teacher": chosen})
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


def _spread_sessions_across_days(sessions, colors, available_slots):
    """
    Priority 1 - Step 3: DAY-AWARE COLOR-TO-SLOT ASSIGNMENT

    The C++ engine assigns abstract integer colors (0, 1, 2, ...).  With the
    interleaved slot ordering from Step 2, color 0 = Mon-P1, color 5 = Mon-P2,
    color 10 = Mon-P3, etc.  A division with 5 sessions might get colors
    0, 5, 10, 15, 20 -- all mapping to Monday, still stacked on one day.

    Fix: for each division, when we see a color that belongs to period block B
    (e.g. the 09:00-10:00 block), we can freely pick ANY day from that block
    for this division -- because same-division sessions have DIFFERENT colors
    (guaranteed by the engine) and therefore land in DIFFERENT period blocks.
    So the only freedom we have is WHICH DAY within each block.

    We use a greedy least-used-day rule per division:
      - Sort the division's sessions by color (= by period block).
      - For each period block, pick the day with the fewest sessions already
        assigned to this division (breaking ties by day order Mon->Fri).

    Returns: list of TimeSlot objects (one per session, parallel to sessions).
             None for sessions where color >= available slots.
    """
    if not colors or not available_slots:
        return [None] * len(sessions)

    n = len(sessions)
    num_slots = len(available_slots)

    # Detect days_per_block from the interleaved structure:
    # count how many slots share the same start_time as slot[0].
    first_start = available_slots[0].start_time
    days_per_block = sum(1 for s in available_slots if s.start_time == first_start)
    if days_per_block == 0:
        days_per_block = 1

    # Build period blocks: block[b] = [slot, slot, ...] (one per available day).
    num_blocks = (num_slots + days_per_block - 1) // days_per_block
    blocks = []
    for b in range(num_blocks):
        start = b * days_per_block
        end = min(start + days_per_block, num_slots)
        blocks.append(available_slots[start:end])

    # Group sessions by division.
    from collections import defaultdict
    div_sessions = defaultdict(list)  # division_id -> [(session_idx, color)]
    for idx, (session, color) in enumerate(zip(sessions, colors)):
        div_sessions[session["subject"].division_id].append((idx, color))

    # Result array: session_idx -> TimeSlot
    assigned = [None] * n

    DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]

    for div_id, idx_color_pairs in div_sessions.items():
        # Sort by color so we handle earlier period blocks first.
        idx_color_pairs.sort(key=lambda x: x[1])

        # Track: day_code -> number of sessions placed on that day for this division.
        day_usage = defaultdict(int)
        # Track: block_idx -> set of day_codes already used in that block.
        block_taken = defaultdict(set)

        for sess_idx, color in idx_color_pairs:
            if color >= num_slots:
                assigned[sess_idx] = None
                continue

            block_idx = color // days_per_block
            if block_idx >= len(blocks):
                assigned[sess_idx] = None
                continue

            block_slots = blocks[block_idx]

            # Prefer days not yet taken in this block AND least used overall.
            free_in_block = [s for s in block_slots if s.day not in block_taken[block_idx]]
            candidates = free_in_block if free_in_block else list(block_slots)

            # Sort candidates: first by ascending day_usage (least used day),
            # then by DAY_ORDER for a stable tie-break.
            candidates.sort(key=lambda s: (
                day_usage[s.day],
                DAY_ORDER.index(s.day) if s.day in DAY_ORDER else 99
            ))

            best = candidates[0]
            assigned[sess_idx] = best
            block_taken[block_idx].add(best.day)
            day_usage[best.day] += 1

    return assigned


def build_timetable_rows(sessions, colors):
    """
    Map each session's assigned color (0, 1, 2, ...) to a real TimeSlot
    row from the database.

    Priority 1 enhancements applied here:
      - Step 2: slots are ordered INTERLEAVED (round-robin across days)
        so adjacent color numbers fall on different days.
      - Step 3: day-aware assignment picks, for each division's sessions,
        the least-used day from the appropriate period block so lectures
        are spread evenly Mon-Fri rather than clustering on one day.

    Returns:
        rows: list of dicts ready for the template: subject, division,
              teacher, time_slot (or None if we ran out of real slots).
        slot_shortage: True if more colors were used than TimeSlots exist.
    """
    # Step 2: use round-robin interleaved ordering instead of day-clustered.
    available_slots = _make_interleaved_slots()

    # Step 3: day-aware assignment -- returns [TimeSlot|None] parallel to sessions.
    assigned_slots = _spread_sessions_across_days(sessions, colors, available_slots)

    num_colors_used = max(colors) + 1 if colors else 0
    slot_shortage = num_colors_used > len(available_slots)

    rows = []
    for session, time_slot in zip(sessions, assigned_slots):
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
