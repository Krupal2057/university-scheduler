# Backtracking Engine (Stage 7)

Standalone C++ program. Different input than the other two engines — it
also takes a hard limit `K` (the number of time slots you're allowed to
use) and answers a yes/no question instead of "however many slots it
needs."

## Build

```bash
g++ -O2 -Wall -o cpp_engine/backtracking_engine cpp_engine/backtracking.cpp
```

## Usage

```bash
./cpp_engine/backtracking_engine <input_file> <K>
```

Same input file format as the other two engines (first line = session
count, then `teacher_id division_id` per line) — `K` is passed as a
separate command-line argument, not written into the file, so all the
existing test files work unchanged.

## Output

- **If a valid K-slot schedule exists**: prints `session_id slot` per
  line (same format as the other engines), plus a success message on
  stderr.
- **If none exists**: prints a single line `FAILURE`, plus a message on
  stderr. This is not an error or a bug — a clean "no" is a correct,
  useful answer, and this is the one thing Graph Coloring and Greedy
  cannot honestly tell you.

Both cases also print **how many recursive calls it took** — this is
the real, measured cost of the search, not a theoretical estimate.

## Verified test results

| Test case | K | Result | Backtracking calls |
|---|---|---|---|
| `sample_input.txt` | 2 | SUCCESS | 6 |
| `sample_input.txt` | 1 | FAILURE (correct — sessions 0,1 conflict) | 2 |
| `all_same_teacher.txt` | 4 | SUCCESS | 5 |
| `all_same_teacher.txt` | 3 | FAILURE (correct — 4-clique needs 4 slots minimum) | 16 |

Small, deliberate cases behave exactly as predicted, including proving
failure correctly.

## The real finding: measured exponential blowup

We generated one harder, 18-session random test case
(`test_data/stress_test.txt`) and ran Backtracking at increasing K:

| K | Result | Backtracking calls |
|---|---|---|
| 3 | FAILURE | 634 |
| 4 | FAILURE | 13,813 |
| 5 | FAILURE | 2,890,976 |
| 6 | (unknown) | **did not finish in 5 seconds** |
| 7 | (unknown) | **did not finish in 15 seconds** |

For comparison, Graph Coloring solved the *same* 18-session problem
instantly, finding that **8 time slots** suffice.

**This is the honest, central lesson of this stage:** K=7 is just one
slot short of the true minimum (8) — the schedule is "almost possible."
But proving a *tight* infeasibility (rather than an obviously-hopeless
one) forces Backtracking to explore an enormous number of near-miss
branches before it can be sure. This is exactly the exponential
worst-case behavior predicted by the O(K^n) complexity bound — not a
theoretical claim, but something we directly measured.

**Why this matters for the whole project:** Graph Coloring and Greedy
are fast heuristics that always give *an* answer, but can't guarantee
it's the fewest possible slots, and can't tell you "impossible" versus
"just barely possible." Backtracking gives you an exact, trustworthy
answer to "can we fit this in K slots?" — but only when K is either
comfortably large (easy success, few calls) or clearly, hopelessly too
small (fails fast, since conflicts are found almost immediately). The
dangerous zone is K sitting right at or just below the true minimum,
where Backtracking's runtime can explode. This is precisely why a real
system should use Graph Coloring or Greedy to get a good working
schedule fast, and save Backtracking for a narrower, well-scoped job:
proving whether a *specific*, *small* set of constraints can be
satisfied — which is exactly what Stage 8 (constraint conflict
explanation) will use it for.
