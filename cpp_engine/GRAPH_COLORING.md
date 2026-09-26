# Graph Coloring Engine (Stage 3)

Standalone C++ program. NOT connected to Django yet — that happens in the
next stage. This stage only proves the algorithm itself is correct.

## Build

```bash
g++ -O2 -Wall -o cpp_engine/graph_coloring_engine cpp_engine/graph_coloring.cpp
```

## Input format

A plain text file:

```
<number_of_sessions>
<teacher_id> <division_id>      <- one line per session
<teacher_id> <division_id>
...
```

Each line after the first represents one "session" — one lecture that
needs a time slot. Session IDs are just the line's position (0, 1, 2, ...).

## Output format

One line per session: `<session_id> <assigned_time_slot>`, followed by a
status line on stderr showing the total number of distinct time slots used.

## Why teacher_id / division_id and nothing else (yet)

This stage only handles the two conflict rules that make coloring
necessary: same teacher, same division. Room capacity, lab requirements,
and time-slot availability are constraints added in later stages
(they change WHICH color is valid, not whether an edge exists — so they
fit naturally on top of this same graph).

## Test cases (see test_data/)

| File                    | Setup                          | Expected result          |
|-------------------------|----------------------------------|---------------------------|
| sample_input.txt         | 4-cycle of conflicts + 1 isolated node | 2 time slots used |
| all_same_teacher.txt     | 4 sessions, same teacher, all conflict | 4 time slots used (one each) |
| no_conflicts.txt         | 4 sessions, nothing shared        | 1 time slot used (all share slot 0) |

Run any of them:
```bash
./cpp_engine/graph_coloring_engine cpp_engine/test_data/sample_input.txt
```
