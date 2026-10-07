from django.urls import path
from . import views

urlpatterns = [
    # ── Core pages ────────────────────────────────────────────────────────────
    path("",              views.home,               name="home"),
    path("generate/",     views.generate_timetable, name="generate_timetable"),
    path("compare/",      views.compare_view,        name="compare"),
    path("diagnose/",     views.diagnose_view,       name="diagnose"),
    path("substitute/",   views.substitute_view,     name="substitute"),

    # ── Auth ──────────────────────────────────────────────────────────────────
    path("auth/login/",   views.site_login,          name="site_login"),
    path("auth/logout/",  views.site_logout,         name="site_logout"),

    # ── Data Management ───────────────────────────────────────────────────────
    path("data/divisions/",              views.data_divisions,       name="data_divisions"),
    path("data/divisions/<int:pk>/edit/",views.data_division_edit,  name="data_division_edit"),
    path("data/divisions/<int:pk>/del/", views.data_division_delete, name="data_division_delete"),

    path("data/teachers/",               views.data_teachers,        name="data_teachers"),
    path("data/teachers/<int:pk>/edit/", views.data_teacher_edit,    name="data_teacher_edit"),
    path("data/teachers/<int:pk>/del/",  views.data_teacher_delete,  name="data_teacher_delete"),

    path("data/subjects/",               views.data_subjects,        name="data_subjects"),
    path("data/subjects/<int:pk>/edit/", views.data_subject_edit,    name="data_subject_edit"),
    path("data/subjects/<int:pk>/del/",  views.data_subject_delete,  name="data_subject_delete"),

    path("data/rooms/",                  views.data_rooms,           name="data_rooms"),
    path("data/rooms/<int:pk>/edit/",    views.data_room_edit,       name="data_room_edit"),
    path("data/rooms/<int:pk>/del/",     views.data_room_delete,     name="data_room_delete"),

    path("data/timeslots/",              views.data_timeslots,       name="data_timeslots"),
    path("data/timeslots/<int:pk>/edit/",views.data_timeslot_edit,   name="data_timeslot_edit"),
    path("data/timeslots/<int:pk>/del/", views.data_timeslot_delete, name="data_timeslot_delete"),
]
