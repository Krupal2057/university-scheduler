from django.contrib import admin

from .models import Division, Room, Subject, Teacher, TimeSlot


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = (
        "name", "year", "strength", "performance_percentage",
        "scheduling_priority", "preferred_shift", "preferred_lab_timing", "preferred_light_day",
    )
    fieldsets = (
        ("Basic Info", {
            "fields": ("name", "year", "strength", "performance_percentage"),
        }),
        ("Schedule Preferences (Student / Class-Rep Input)", {
            "description": (
                "Set the preferred schedule style for this division. "
                "Higher-priority divisions get first pick of slots matching their preferences. "
                "Leave 'Scheduling Priority' at 0 to auto-derive from Year + Performance %."
            ),
            "fields": (
                "scheduling_priority",
                "preferred_shift",
                "preferred_lab_timing",
                "preferred_light_day",
            ),
        }),
    )


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "room_type", "capacity")
    list_filter = ("room_type",)


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "max_hours_per_week", "is_available")
    list_filter = ("is_available",)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "division", "hours_per_week", "requires_lab", "lab_sessions_per_week", "lab_duration_slots")
    list_filter = ("division", "requires_lab")
    filter_horizontal = ("qualified_teachers",)


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ("day", "start_time", "end_time")
    list_filter = ("day",)
    ordering = ("day", "start_time")
