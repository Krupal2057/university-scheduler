from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("generate/", views.generate_timetable, name="generate_timetable"),
    path("compare/", views.compare_view, name="compare"),
]
