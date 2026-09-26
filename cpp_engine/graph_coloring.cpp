// cpp_engine/graph_coloring.cpp
//
// Stage 3: Graph Coloring algorithm for conflict-free time-slot assignment.
//
// PROBLEM
// -------
// We have a list of "sessions" - each session is one lecture that needs
// to be assigned to a time slot. Two sessions CONFLICT (cannot share the
// same time slot) if:
//   - they have the same teacher (a teacher can't teach two classes at once), OR
//   - they have the same division (a division can't attend two classes at once)
//
// This is exactly the Graph Coloring problem:
//   - Each session   = one graph node
//   - An edge        = a conflict between two sessions
//   - A "color"      = a time slot
//   - A valid coloring = an assignment of colors to nodes such that no
//     two connected nodes share a color
//   - Fewer colors used = fewer distinct time slots needed = a more
//     compact timetable
//
// ALGORITHM: Greedy coloring (Welsh-Powell style)
// ------------------------------------------------
// 1. Compute the degree (number of conflicts) of every session.
// 2. Sort sessions by degree, highest first. (Coloring the most
//    constrained sessions first tends to use fewer total colors overall.)
// 3. For each session in that order, assign the SMALLEST color index
//    not already used by any of its already-colored neighbors.
//
// This is a greedy approximation, not an exact solver. Finding the
// mathematically minimum number of colors is NP-hard in general, but
// this greedy approach is fast and produces good, usable timetables for
// realistic input sizes.
//
// COMPLEXITY (n = number of sessions)
// ------------------------------------
// - Building the conflict graph: every pair of sessions is compared
//   once -> O(n^2) time.
// - Sorting sessions by degree: O(n log n).
// - Greedy coloring: for each node, scan its row in the conflict matrix
//   to find neighbors' colors -> O(n) per node -> O(n^2) overall.
// - Space: O(n^2), for the adjacency (conflict) matrix.
//
// Overall: O(n^2) time, O(n^2) space.
// (For very large inputs, an adjacency LIST instead of a matrix would
// reduce space to O(n + e), where e = number of conflicts. Not needed
// at college-timetable scale - a few hundred sessions at most.)

#include <algorithm>
#include <fstream>
#include <iostream>
#include <numeric>
#include <vector>

struct Session {
    int teacher_id;
    int division_id;
};

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: ./graph_coloring_engine <input_file>" << std::endl;
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

    // Step 1: build the conflict graph as an adjacency matrix.
    std::vector<std::vector<bool>> conflict(n, std::vector<bool>(n, false));
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            bool same_teacher  = sessions[i].teacher_id  == sessions[j].teacher_id;
            bool same_division = sessions[i].division_id == sessions[j].division_id;
            if (same_teacher || same_division) {
                conflict[i][j] = true;
                conflict[j][i] = true;
            }
        }
    }

    // Step 2: compute each node's degree, then sort nodes by degree
    // descending (most-constrained-first heuristic).
    std::vector<int> degree(n, 0);
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            if (conflict[i][j]) degree[i]++;

    std::vector<int> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        return degree[a] > degree[b];
    });

    // Step 3: greedy coloring. color[i] = the time slot assigned to session i.
    std::vector<int> color(n, -1);
    for (int idx : order) {
        std::vector<bool> used_by_neighbors(n, false);
        for (int j = 0; j < n; j++) {
            if (conflict[idx][j] && color[j] != -1) {
                used_by_neighbors[color[j]] = true;
            }
        }
        int c = 0;
        while (c < n && used_by_neighbors[c]) c++;
        color[idx] = c;
    }

    int num_colors_used = *std::max_element(color.begin(), color.end()) + 1;

    // Output: one line per session -> "session_id assigned_time_slot"
    for (int i = 0; i < n; i++) {
        std::cout << i << " " << color[i] << std::endl;
    }
    std::cerr << "Total time slots used: " << num_colors_used << std::endl;

    return 0;
}
