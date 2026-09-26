// cpp_engine/main.cpp
//
// Stage 1 placeholder.
//
// Later, this program (or programs like it) will contain the real
// algorithms: Graph Coloring, Greedy, and Backtracking for timetable
// generation. For now it only proves that:
//   1. The C++ engine compiles.
//   2. Django can run it as a separate process.
//   3. Django can read back what it prints.
//
// Design decision for this whole project:
// Django will NOT link against C++ code directly. Instead, Django will
// run the compiled C++ program as a subprocess, send it input (later:
// divisions/teachers/rooms as JSON), and read its printed output
// (later: the generated schedule as JSON). This keeps the two languages
// completely separate and easy to explain in a viva:
//
//   Django (web app) ---runs---> cpp_engine executable ---prints---> result
//
#include <iostream>

int main() {
    std::cout << "C++ engine ready" << std::endl;
    return 0;
}
