from django.db import models


class Division(models.Model):
    """
    A class/batch of students, e.g. "TE-A" (Third Year, Division A).

    Preference-Guided Priority Scheduler (Stage 11):
    Divisions register their schedule preferences (shift, lab timing, light
    day). Higher-priority divisions get first pick of slots that match
    their preferences. The scheduler uses these as soft constraints inside
    a weighted cost function — hard resource constraints (teacher/room
    clashes) always win.
    """

    class PreferredShift(models.TextChoices):
        MORNING  = "MORNING",  "Morning Focus (09:00–12:00)"
        BALANCED = "BALANCED", "Balanced / Standard"
        AFTERNOON = "AFTERNOON", "Afternoon / Late Start (11:00+)"

    class PreferredLabTiming(models.TextChoices):
        MORNING   = "MORNING",   "Morning Labs"
        AFTERNOON = "AFTERNOON", "Post-Lunch Labs"
        NO_PREF   = "NO_PREF",   "No Preference"

    class LightDay(models.TextChoices):
        MONDAY    = "MON", "Monday"
        TUESDAY   = "TUE", "Tuesday"
        WEDNESDAY = "WED", "Wednesday"
        THURSDAY  = "THU", "Thursday"
        FRIDAY    = "FRI", "Friday"
        SATURDAY  = "SAT", "Saturday"
        NONE      = "NONE", "No Light Day"

    name = models.CharField(max_length=50, unique=True)
    year = models.PositiveSmallIntegerField(help_text="e.g. 1, 2, 3, 4")
    strength = models.PositiveIntegerField(help_text="Number of students")
    performance_percentage = models.FloatField(
        default=0.0,
        help_text="Previous semester average %. Higher % → higher scheduling priority.",
    )

    # ── Preference fields (student / class-rep input) ──────────────────────
    scheduling_priority = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Scheduling priority (higher wins first pick of preferred slots). "
            "Automatically derived from year + performance, but can be overridden."
        ),
    )
    preferred_shift = models.CharField(
        max_length=10,
        choices=PreferredShift.choices,
        default=PreferredShift.BALANCED,
        help_text="Does this division prefer morning, afternoon, or balanced sessions?",
    )
    preferred_lab_timing = models.CharField(
        max_length=10,
        choices=PreferredLabTiming.choices,
        default=PreferredLabTiming.NO_PREF,
        help_text="Does this division prefer morning or afternoon lab sessions?",
    )
    preferred_light_day = models.CharField(
        max_length=4,
        choices=LightDay.choices,
        default=LightDay.NONE,
        help_text="Which day should have fewer/lighter sessions? (e.g. Friday)",
    )

    @property
    def effective_priority(self):
        """
        If scheduling_priority has been manually set (> 0), use it directly.
        Otherwise auto-derive from year (higher year = higher priority) and
        performance_percentage (better performance = higher priority):
            priority = year * 100 + round(performance_percentage)
        """
        if self.scheduling_priority > 0:
            return self.scheduling_priority
        return self.year * 100 + round(self.performance_percentage)

    def __str__(self):
        return self.name


class Room(models.Model):
    """A physical room: a classroom, lab, or seminar hall."""

    class RoomType(models.TextChoices):
        CLASSROOM = "CLASSROOM", "Classroom"
        LAB = "LAB", "Lab"
        SEMINAR_HALL = "SEMINAR_HALL", "Seminar Hall"

    name = models.CharField(max_length=50, unique=True)
    capacity = models.PositiveIntegerField()
    room_type = models.CharField(max_length=20, choices=RoomType.choices)

    def __str__(self):
        return f"{self.name} ({self.get_room_type_display()}, cap {self.capacity})"


class Teacher(models.Model):
    """A faculty member who can teach one or more subjects."""

    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    max_hours_per_week = models.PositiveIntegerField(
        default=18,
        help_text="Workload cap, used as a constraint by the scheduler.",
    )
    is_available = models.BooleanField(
        default=True,
        help_text="Uncheck to mark this teacher temporarily unavailable (e.g. on leave). "
                   "The scheduler will automatically look for a qualified substitute.",
    )

    def __str__(self):
        return self.name


class Subject(models.Model):
    """
    A subject taught to one division, e.g. "Data Structures" for TE-A.

    `requires_lab` marks subjects that must be scheduled into a Room
    with room_type=LAB rather than an ordinary classroom.

    `qualified_teachers` is which teachers are allowed to teach this
    subject — this is exactly the "teacher compatibility" constraint
    described in the project brief, and it's also what the substitute-
    teacher suggestion feature will search through later.
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    division = models.ForeignKey(Division, on_delete=models.CASCADE, related_name="subjects")
    hours_per_week = models.PositiveIntegerField(
        help_text="How many time slots per week this subject needs."
    )
    requires_lab = models.BooleanField(default=False)
    lab_sessions_per_week = models.PositiveIntegerField(
        default=1,
        help_text="Number of lab sessions per week (default 1 if requires_lab is True).",
    )
    lab_duration_slots = models.PositiveIntegerField(
        default=2,
        help_text="Duration in continuous time slots per lab session (e.g. 2 hours).",
    )
    qualified_teachers = models.ManyToManyField(Teacher, related_name="subjects_taught")

    @property
    def effective_lab_sessions(self):
        return self.lab_sessions_per_week if self.requires_lab else 0

    @property
    def total_lab_slots(self):
        return self.effective_lab_sessions * self.lab_duration_slots

    @property
    def lecture_slots(self):
        if not self.requires_lab or self.effective_lab_sessions == 0:
            return self.hours_per_week
        if self.hours_per_week >= self.total_lab_slots:
            return self.hours_per_week - self.total_lab_slots
        # Bug 2 fix: lab slots exceed total hours — no lectures left, not hours_per_week.
        return 0

    def __str__(self):
        lab_tag = f" [LAB: {self.effective_lab_sessions}x{self.lab_duration_slots}h]" if self.requires_lab else ""
        return f"{self.code} - {self.name} ({self.division}){lab_tag}"


class TimeSlot(models.Model):
    """
    One bookable period, e.g. "Monday 10:00-11:00".

    We store slots as concrete rows (rather than just start/end times)
    because the scheduling algorithms will treat each TimeSlot as one
    unit / one "color" in the Graph Coloring formulation — simplest
    possible model for that purpose.
    """

    class Day(models.TextChoices):
        MONDAY = "MON", "Monday"
        TUESDAY = "TUE", "Tuesday"
        WEDNESDAY = "WED", "Wednesday"
        THURSDAY = "THU", "Thursday"
        FRIDAY = "FRI", "Friday"
        SATURDAY = "SAT", "Saturday"

    day = models.CharField(max_length=3, choices=Day.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        unique_together = ("day", "start_time", "end_time")
        ordering = ["day", "start_time"]

    def __str__(self):
        return f"{self.get_day_display()} {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}"
