from django.db import models


class Division(models.Model):
    """
    A class/batch of students, e.g. "TE-A" (Third Year, Division A).

    `performance_percentage` is used later (Stage: Performance-Based
    Division Priority) as a soft preference input to the optimizer.
    It is NOT used yet — storing it here now avoids a migration later.
    """
    name = models.CharField(max_length=50, unique=True)
    year = models.PositiveSmallIntegerField(help_text="e.g. 1, 2, 3, 4")
    strength = models.PositiveIntegerField(help_text="Number of students")
    performance_percentage = models.FloatField(
        default=0.0,
        help_text="Previous semester average %, used as a soft scheduling preference later.",
    )

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
    qualified_teachers = models.ManyToManyField(Teacher, related_name="subjects_taught")

    def __str__(self):
        return f"{self.code} - {self.name} ({self.division})"


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
