from django.contrib import admin

from .models import Division, Room, Subject, Teacher, TimeSlot


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "strength", "performance_percentage")


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
    list_display = ("code", "name", "division", "hours_per_week", "requires_lab")
    list_filter = ("division", "requires_lab")
    filter_horizontal = ("qualified_teachers",)


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ("day", "start_time", "end_time")
    list_filter = ("day",)
    ordering = ("day", "start_time")
