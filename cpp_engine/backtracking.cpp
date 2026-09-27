// cpp_engine/backtracking.cpp
//
// Stage 7: Backtracking search for a K-limited timetable.
//
// PROBLEM (different question than Stages 3 and 5!)
// -----------------------------------------------------
// Graph Coloring and Greedy both ask: "assign colors so nothing
// conflicts, using AS MANY colors as turns out to be necessary."
// Backtracking asks a stricter question instead:
//
//     "Can every session be assigned one of exactly K time slots,
//      with zero conflicts? If not, say so."
//
// This matters in practice: a real college only HAS a fixed number of
// usable time slots per week. Graph Coloring can't tell you whether
// your actual slot count is enough - it just reports however many IT
// decided to use. Backtracking can.
//
// ALGORITHM: Depth-first search with backtracking
// --------------------------------------------------
// Process sessions 0, 1, 2, ... in order. For session i, try giving it
// time slot 0, then 1, then 2, ... up to K-1:
//   - If a slot doesn't conflict with any ALREADY-DECIDED earlier
//     session, tentatively assign it and recurse to session i+1.
//   - If that recursive call eventually fails (some later session had
//     no valid slot left), UNDO this assignment ("backtrack") and try
//     the next slot for session i instead.
//   - If NONE of the K slots work for session i, report failure back
//     up to session i-1, which then tries ITS next option.
// If we successfully assign all n sessions, we've found a valid
// schedule using only K slots. If session 0 runs out of options, no
// valid schedule exists with K slots - period.
//
// This is the classic "constraint satisfaction via search" pattern:
// try -> check -> recurse -> undo-if-stuck. The same shape reappears
// in Sudoku solvers, N-Queens, and (later in this project) more
// detailed constraint checking with rooms and labs.
//
// COMPLEXITY
// ----------
// Worst case: at every one of n sessions, we may try all K slots
// before finding (or failing to find) one that works, and recurse
// into each -> O(K^n) in the absolute worst case. This is why
// Backtracking is only practical when most branches get pruned early
// (a conflict is detected quickly, before going deep) - which is
// exactly why we count and print how many recursive calls actually
// happened, instead of just asserting "it's exponential" without
// evidence.
//
// Space: O(n) for the recursion stack (depth = number of sessions) plus
// O(n) to store the current assignment.

#include <fstream>
#include <iostream>
#include <vector>

struct Session {
    int teacher_id;
    int division_id;
};

int n;
int K;
std::vector<Session> sessions;
std::vector<int> slot;          // slot[i] = time slot assigned to session i so far (-1 = unassigned)
long long backtrack_calls = 0;  // how many times solve() was invoked - our honesty check

bool conflicts(int i, int j) {
    return sessions[i].teacher_id == sessions[j].teacher_id
        || sessions[i].division_id == sessions[j].division_id;
}

// Returns true if session `idx` can be given `candidate_slot` without
// clashing with any EARLIER session that has already been assigned.
bool is_safe(int idx, int candidate_slot) {
    for (int j = 0; j < idx; j++) {
        if (slot[j] == candidate_slot && conflicts(idx, j)) {
            return false;
        }
    }
    return true;
}

// Try to assign sessions idx, idx+1, ..., n-1. Returns true if a
// complete, valid assignment was found (it will be sitting in `slot`).
bool solve(int idx) {
    backtrack_calls++;

    if (idx == n) {
        return true;  // every session has a valid slot - done
    }

    for (int candidate = 0; candidate < K; candidate++) {
        if (is_safe(idx, candidate)) {
            slot[idx] = candidate;       // tentatively choose
            if (solve(idx + 1)) {
                return true;             // this choice worked all the way through
            }
            slot[idx] = -1;              // undo ("backtrack") - this choice didn't pan out
        }
    }

    return false;  // no candidate slot worked for this session
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: ./backtracking_engine <input_file> <K>" << std::endl;
        return 1;
    }

    std::ifstream in(argv[1]);
    if (!in) {
        std::cerr << "Error: could not open input file " << argv[1] << std::endl;
        return 1;
    }
    K = std::stoi(argv[2]);

    in >> n;
    sessions.resize(n);
    for (int i = 0; i < n; i++) {
        in >> sessions[i].teacher_id >> sessions[i].division_id;
    }
    slot.assign(n, -1);

    bool found = solve(0);

    if (found) {
        for (int i = 0; i < n; i++) {
            std::cout << i << " " << slot[i] << std::endl;
        }
        std::cerr << "SUCCESS using K=" << K << " time slots. "
                   << "Backtracking calls: " << backtrack_calls << std::endl;
    } else {
        std::cout << "FAILURE" << std::endl;
        std::cerr << "No valid schedule exists with only K=" << K << " time slots. "
                   << "Backtracking calls: " << backtrack_calls << std::endl;
    }

    return 0;
}
