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

**Where they reliably do differ, regardless of input:** execution time.
Graph Coloring does extra work up front (computing every session's
degree, then sorting) that Greedy skips entirely. On small inputs this
difference is invisible; Stage 6 will measure it precisely.
