"""Peak extra memory of slicing one ranged read out of a downloaded file: split_file_lines vs slice_file_lines.

    cd backend && uv run python ../hunt/aio-line-endings/bench_ranged_read.py {split|slice} {a-crlf|lf|log}
"""

import sys
import time
import tracemalloc

from deerflow.sandbox.read_file_contract import slice_file_lines, split_file_lines

which, kind = sys.argv[1], sys.argv[2]
unit = {"a-crlf": "a\r\n", "lf": "\n", "log": "2026-11-26 12:00:00 INFO ok\r\n"}[kind]
content = unit * (100 * 2**20 // len(unit))
total = content.count("\n")
start, end = total - 40, total - 1


def run():
    if which == "split":
        lines = split_file_lines(content)
        return "\n".join(lines[start - 1 : end])
    return slice_file_lines(content, start, end)


tracemalloc.start()
t = time.perf_counter()
out = run()
dt = time.perf_counter() - t
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
print(f"{which:5} {kind:6} lines={total:>10,} peak_extra={peak / 2**20:8.1f} MiB time={dt:5.2f}s (tracemalloc on) out={len(out)} chars")
