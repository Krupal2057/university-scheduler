# University Timetable Optimization Using Graph Coloring, Greedy and Backtracking Algorithms

A centralized university campus scheduling and optimization system, built as a
2-member DAA (Design and Analysis of Algorithms) project.

## Stage 1: Project Foundation (current stage)

At this stage the project is just a working skeleton, proving that all three
technologies talk to each other correctly:

- **Django** serves a web page.
- **C++** is compiled separately into its own program (`cpp_engine/engine`).
- Django **runs the C++ program as a subprocess** and displays its output.

No scheduling logic exists yet — that comes in later stages.

## Why C++ runs as a separate program, not a library

Rather than linking C++ directly into Python (which requires extra tools like
pybind11 and adds complexity), the C++ engine is a **standalone executable**.
Django sends it input and reads its printed output. This is simple to set up,
simple to test on its own (you can run `./cpp_engine/engine` directly from the
terminal), and simple to explain in a viva:

```
Django (web app, database, UI)  --runs-->  cpp_engine executable  --prints-->  result
```

Later stages will replace the placeholder message with real JSON data:
divisions, subjects, teachers, rooms, and time slots going in; a generated
timetable coming out.

## Folder structure

```
university-scheduler/
├── manage.py                  # Django's command-line entry point
├── requirements.txt           # Python dependencies
├── scheduler_project/         # Django project settings & URL routing
├── scheduler/                 # Django app: views, models, templates
│   └── templates/scheduler/home.html
└── cpp_engine/                # C++ algorithm engine (compiled separately)
    └── main.cpp
```

## How to run it

### 1. Python / Django side

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Then open http://127.0.0.1:8000/ in a browser.

### 2. C++ side

```bash
g++ -O2 -o cpp_engine/engine cpp_engine/main.cpp
```

Run this once before starting the Django server (or whenever you change
`main.cpp`). The compiled `engine` file is intentionally left out of Git
(see `.gitignore`) — everyone builds it locally from the source.

## Roadmap (later stages)

1. ~~Project foundation~~ ✅ (this stage)
2. Data models: divisions, subjects, teachers, rooms, time slots
3. Graph Coloring algorithm for basic conflict-free timetabling
4. Greedy algorithm and comparison against Graph Coloring
5. Backtracking for constraint satisfaction
6. Constraint conflict explanation
7. Resource substitution suggestions
8. Exam scheduling
9. Event scheduling
10. Dynamic re-scheduling
11. Performance-based division priority (soft preference)
12. Algorithm comparison dashboard
13. Complexity analysis writeup
14. Google Calendar integration (optional, if time permits)
