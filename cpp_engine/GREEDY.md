# Greedy Engine (Stage 5)

Standalone C++ program, same input/output format as the Graph Coloring
engine (see `GRAPH_COLORING.md`), so the two can be fed identical data
for comparison in Stage 6.

## Build

```bash
g++ -O2 -Wall -o cpp_engine/greedy_engine cpp_engine/greedy.cpp
```

## How it differs from Graph Coloring

| | Graph Coloring | Greedy |
|---|---|---|
| Processing order | Sorted by degree (most conflicts first) | Fixed input order, no sorting |
| Extra work per session | None beyond checking neighbors | None beyond checking neighbors |
| Preprocessing | O(n log n) sort + O(n^2) degree count | None |

Both use the same core rule once an order is chosen: "give this session
the smallest time slot not already taken by a session it conflicts
with." The only difference is which order they process sessions in.

## Honest test results

We ran both engines on identical inputs. Here's what we found and why —
this is worth understanding for your viva, not just quoting the numbers.

| Test case | Conflict structure | Graph Coloring result | Greedy result |
|---|---|---|---|
| `sample_input.txt` | 4-node cycle + 1 isolated | 2 slots | 2 slots |
| `all_same_teacher.txt` | 4-node clique (everyone conflicts) | 4 slots | 4 slots |
| `no_conflicts.txt` | No edges at all | 1 slot | 1 slot |
| `order_sensitive.txt` | 6-node cycle, all equal degree | 3 slots | 3 slots |
| `unequal_degrees.txt` | Triangle + low-conflict chain | 3 slots | 3 slots |

**Every test tied.** This is not a bug — it's an accurate reflection of a
real property of this problem:

- On a **clique** (everyone conflicts with everyone), any processing
  order needs exactly as many colors as there are sessions in the
  clique. Order can't help or hurt.
- On the **cycle** test case, every session has the *same* number of
  conflicts (degree 2). Graph Coloring's "sort by most conflicts first"
  trick only changes anything when sessions have genuinely *different*
  conflict counts — with a tie, there's nothing to sort by, so both
  algorithms end up in essentially the same processing order.
- Even the "unequal degrees" test, which does have different degrees,
  still had a clique (the triangle) forcing the same minimum regardless.

**Where they will actually diverge:** with a large, messy, real dataset
— many teachers with different numbers of overlapping classes, many
divisions of different sizes — Graph Coloring's degree-based ordering
generally uses time slots at least as efficiently as Greedy's fixed
order, and often more efficiently, precisely because real timetable
data has sessions with very different numbers of conflicts (some
teachers overloaded, some rooms rarely used). Stage 6 will run both
engines on your actual database data and measure this directly, instead
of guessing from small hand-built examples.

## Stage 6 update: measured comparison on real and stress-test data

With the two engines wired into Django (`timetable_service.compare_algorithms()`),
we ran both on real database sessions and on synthetic stress-test data at
increasing scale. Results (measured, not estimated):

| Sessions (n) | Graph Coloring: slots / time | Greedy: slots / time |
|---|---|---|
| 55 (real DB data)  | 12 slots / 2.09 ms | 12 slots / 3.24 ms |
| 50 (synthetic)     | 7 slots / 2.14 ms  | 7 slots / 2.87 ms  |
| 200 (synthetic)    | 8 slots / 3.70 ms  | 8 slots / 3.42 ms  |
| 800 (synthetic)    | 12 slots / 7.58 ms | 12 slots / 3.56 ms |

**Two honest conclusions:**

1. **Below a few hundred sessions, timing differences are just noise** —
   process-launch overhead (starting the C++ program at all) dwarfs any
   O(n^2) computation happening inside it. This itself is a valid
   complexity-analysis point: Big-O describes *asymptotic* behavior, and
   at small n, constant-factor overhead (like process startup) can
   dominate the "theoretically slower" algorithm's actual runtime.

2. **At n = 800, the predicted pattern appears clearly**: Graph Coloring
   takes roughly twice as long as Greedy, because it does extra O(n^2)
   work up front — computing every session's degree, then sorting by
   it — before it even starts coloring. Greedy skips straight to
   coloring. Both still found the same number of time slots on this
   data, so here the real, measurable tradeoff is **speed**, not
   **schedule quality** — worth stating plainly in your report rather
   than claiming Graph Coloring is simply "better."

