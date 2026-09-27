// cpp_engine/greedy.cpp
//
// Stage 5: Greedy algorithm for time-slot assignment.
//
// SAME PROBLEM as graph_coloring.cpp: assign each session a time slot
// (an integer "color") so that no two conflicting sessions (same
// teacher or same division) share a slot.
//
// DIFFERENT METHOD
// -----------------
// Graph Coloring (graph_coloring.cpp) looks at the WHOLE conflict graph
// first: it computes every session's degree, sorts the most-constrained
// sessions to the front, and colors those first. That extra work is
// exactly why it tends to use fewer total time slots.
//
// Greedy does none of that lookahead. It processes sessions in the
// order they were given (session 0, then 1, then 2, ...) and, for each
// one, picks the SMALLEST time slot that doesn't clash with anything
// already assigned. No sorting, no degree calculation - just "first
// available slot, right now."
//
// This is a classic Design and Analysis of Algorithms comparison point:
// Greedy is simpler and faster to reason about, but its quality depends
// entirely on the input order. A bad order can force it to use more
// time slots than Graph Coloring needed for the exact same problem.
// (Stage 6 will run both on the same input and show this side by side.)
//
// COMPLEXITY (n = number of sessions)
// ------------------------------------
// - No preprocessing (no sorting, no degree counting).
// - For each session i, check all EARLIER sessions (0..i-1) to see
//   which slots are already taken by a conflicting session -> O(n) work
//   per session -> O(n^2) overall.
// - Space: O(n) to store each session's assigned slot, plus O(n) to
//   track "which slots are taken by conflicts of session i" per step
//   (reused each iteration, not stored all at once).
//
// Overall: O(n^2) time, O(n) space.
// (Notice: same time complexity as Graph Coloring's greedy step, but
// LESS space, since it skips building the full conflict matrix - it
// only ever compares session i against sessions before it, in an
// input-order pass. The tradeoff for that savings is that it can use
// MORE distinct time slots than Graph Coloring, because it never
// reorders sessions to color the hardest ones first.)

#include <fstream>
#include <iostream>
#include <vector>

struct Session {
    int teacher_id;
    int division_id;
};

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: ./greedy_engine <input_file>" << std::endl;
        return 1;
    }

    std::ifstream in(argv[1]);
    if (!in) {
        std::cerr << "Error: could not open input file " << argv[1] << std::endl;
        return 1;
    }

    int n;
    in >> n;
    std::vector<Session> sessions(n);
    for (int i = 0; i < n; i++) {
        in >> sessions[i].teacher_id >> sessions[i].division_id;
    }

    std::vector<int> slot(n, -1);

    // Process sessions strictly in input order - no sorting, no lookahead.
    for (int i = 0; i < n; i++) {
        std::vector<bool> taken(n, false);

        // Check every EARLIER session for a conflict, and if one exists
        // and it's already been assigned a slot, mark that slot as taken.
        for (int j = 0; j < i; j++) {
            bool same_teacher  = sessions[i].teacher_id  == sessions[j].teacher_id;
            bool same_division = sessions[i].division_id == sessions[j].division_id;
            if ((same_teacher || same_division) && slot[j] != -1) {
                taken[slot[j]] = true;
            }
        }

        // Pick the first free slot.
        int s = 0;
        while (s < n && taken[s]) s++;
        slot[i] = s;
    }

    int num_slots_used = 0;
    for (int i = 0; i < n; i++) {
        std::cout << i << " " << slot[i] << std::endl;
        if (slot[i] + 1 > num_slots_used) num_slots_used = slot[i] + 1;
    }
    std::cerr << "Total time slots used: " << num_slots_used << std::endl;

    return 0;
}
