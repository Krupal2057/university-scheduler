from django import forms
from .models import Division, Teacher, Subject, Room, TimeSlot

# CSS classes applied to every widget type
_text_attrs  = {"class": "form-control"}
_num_attrs   = {"class": "form-control"}
_sel_attrs   = {"class": "form-select"}
_msel_attrs  = {"class": "form-select"}
_time_attrs  = {"class": "form-control", "type": "time"}


def _add_class(widget, css_class):
    """Merge a CSS class into an existing widget attrs dict."""
    existing = widget.attrs.get("class", "")
    widget.attrs["class"] = f"{existing} {css_class}".strip()
    return widget


class DivisionForm(forms.ModelForm):
    class Meta:
        model = Division
        fields = [
            "name", "year", "strength", "performance_percentage",
            "scheduling_priority", "preferred_shift",
            "preferred_lab_timing", "preferred_light_day",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. TE-A", "class": "form-control"}),
            "year": forms.NumberInput(attrs={"placeholder": "e.g. 3", "min": 1, "max": 4, "class": "form-control"}),
            "strength": forms.NumberInput(attrs={"placeholder": "e.g. 60", "class": "form-control"}),
            "performance_percentage": forms.NumberInput(
                attrs={"placeholder": "0–100", "step": "0.1", "min": 0, "max": 100, "class": "form-control"}
            ),
            "scheduling_priority": forms.NumberInput(
                attrs={"placeholder": "0 = auto-derive", "min": 0, "class": "form-control"}
            ),
            "preferred_shift": forms.Select(attrs={"class": "form-select"}),
            "preferred_lab_timing": forms.Select(attrs={"class": "form-select"}),
            "preferred_light_day": forms.Select(attrs={"class": "form-select"}),
        }


class TeacherForm(forms.ModelForm):
    class Meta:
        model = Teacher
        fields = ["name", "email", "max_hours_per_week", "is_available"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Full name", "class": "form-control"}),
            "email": forms.EmailInput(attrs={"placeholder": "teacher@university.edu", "class": "form-control"}),
            "max_hours_per_week": forms.NumberInput(attrs={"min": 1, "max": 40, "class": "form-control"}),
        }


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = [
            "name", "code", "division", "hours_per_week",
            "requires_lab", "lab_sessions_per_week", "lab_duration_slots",
            "qualified_teachers",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Data Structures", "class": "form-control"}),
            "code": forms.TextInput(attrs={"placeholder": "e.g. CS301", "class": "form-control"}),
            "division": forms.Select(attrs={"class": "form-select"}),
            "hours_per_week": forms.NumberInput(attrs={"min": 1, "max": 20, "class": "form-control"}),
            "lab_sessions_per_week": forms.NumberInput(attrs={"min": 0, "class": "form-control"}),
            "lab_duration_slots": forms.NumberInput(attrs={"min": 1, "max": 6, "class": "form-control"}),
            "qualified_teachers": forms.SelectMultiple(attrs={"size": 6, "class": "form-select"}),
        }


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name", "capacity", "room_type"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Lab-101", "class": "form-control"}),
            "capacity": forms.NumberInput(attrs={"min": 1, "placeholder": "e.g. 60", "class": "form-control"}),
            "room_type": forms.Select(attrs={"class": "form-select"}),
        }


class TimeSlotForm(forms.ModelForm):
    class Meta:
        model = TimeSlot
        fields = ["day", "start_time", "end_time"]
        widgets = {
            "day": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
        }
