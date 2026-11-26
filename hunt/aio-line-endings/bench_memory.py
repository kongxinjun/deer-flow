"""Peak extra memory (tracemalloc), wall time and process max RSS of the str_replace splice.

    cd backend && uv run python ../hunt/aio-line-endings/bench_memory.py {head|new} {MB} {case}

Run one case per process so max RSS belongs to it. Cases: mixed-span-at-end,
mixed-span-at-start, mixed-replace-all, crlf-replace-all, crlf-one-edit.
"""
import gc, sys, time, tracemalloc, importlib.util
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deerflow.sandbox.tools import _replace_keeping_line_endings as new_impl
spec = importlib.util.spec_from_file_location("head_helper", os.path.join(os.path.dirname(os.path.abspath(__file__)), "head_3f34c135f_matcher.py"))
head = importlib.util.module_from_spec(spec); spec.loader.exec_module(head)
impls = {"head": head._replace_keeping_line_endings, "new": new_impl}

def case(mb, kind):
    n = mb * 1024 * 1024 // 3
    if kind == "mixed-span-at-end":      # one edit whose span crosses CRLF -> LF, at the end
        return "x\r\n" * n + "y\nz\n", "x\ny\nz", "Z", False
    if kind == "mixed-span-at-start":    # the same span at the start of the file
        return "x\r\ny\nz\n" + "x\r\n" * n, "x\ny\nz", "Z", False
    if kind == "mixed-replace-all":      # replace_all, one mixed span every two lines
        return "x\r\ny\n" * (n * 3 // 5), "x\ny\nx", "Z\nZ", True
    if kind == "crlf-replace-all":       # replace_all, one match per line, all CRLF
        return "x\r\n" * n, "x\n", "z\n", True
    if kind == "crlf-one-edit":
        return "x\r\n" * n + "y\r\n", "x\ny", "Z", False
    raise ValueError(kind)

which = sys.argv[1]; mb = int(sys.argv[2]); kind = sys.argv[3]
content, old, new, ra = case(mb, kind)
import resource
gc.collect()
t = time.perf_counter()
out = impls[which](content, old, new, ra)
dt = time.perf_counter() - t
assert out is not None
del out
gc.collect()
tracemalloc.start()
out = impls[which](content, old, new, ra)
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # macOS: bytes
print(f"{which:4} {mb:4} MB {kind:20} peak_extra={peak/2**20:8.1f} MiB  time={dt:7.3f}s  process_max_rss={rss:7.1f} MiB  input={len(content)/2**20:.1f} MiB")
