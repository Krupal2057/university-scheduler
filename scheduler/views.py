import os
import subprocess

from django.conf import settings
from django.shortcuts import render


def home(request):
    """
    Stage 1 homepage.

    This view does two things:
      1. Renders the dashboard page.
      2. Calls the compiled C++ engine as a subprocess, to prove that
         Django and C++ can talk to each other. Later stages will send
         real scheduling data in and read a real schedule back out,
         using this exact same mechanism.
    """
    engine_path = os.path.join(settings.BASE_DIR, "cpp_engine", "engine")

    try:
        result = subprocess.run(
            [engine_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        cpp_status = "connected"
        cpp_message = result.stdout.strip()
    except FileNotFoundError:
        cpp_status = "not built yet"
        cpp_message = "run: g++ -O2 -o cpp_engine/engine cpp_engine/main.cpp"
    except Exception as exc:  # keep Stage 1 simple: show any error plainly
        cpp_status = "error"
        cpp_message = str(exc)

    return render(request, "scheduler/home.html", {
        "cpp_status": cpp_status,
        "cpp_message": cpp_message,
    })
