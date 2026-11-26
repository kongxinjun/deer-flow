"""Live check of str_replace / read_file / write_file line endings against a real AIO sandbox.

Usage: uv run python live_aio_check.py [base_url]   (default http://localhost:18080)
Start one with: docker run -d --rm --name aio --security-opt seccomp=unconfined -p 18080:8080 ghcr.io/agent-infra/sandbox:1.11.0
DeerFlow mounts /mnt/user-data into the container; stand in for the mount with:
  docker exec aio sh -c 'mkdir -p /mnt/user-data/outputs && chown -R gem:gem /mnt/user-data'
"""

import sys
from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

import deerflow.sandbox.tools as tools
from deerflow.agents.middlewares.read_before_write_middleware import WRITE_BLOCK_KEY, ReadBeforeWriteMiddleware
from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:18080"
sandbox = AioSandbox(id="live", base_url=BASE)
tools.ensure_sandbox_initialized = lambda runtime: sandbox
tools.ensure_thread_directories_exist = lambda runtime: None
tools.is_local_sandbox = lambda runtime: False
runtime = SimpleNamespace(state={"sandbox": {"sandbox_id": "live"}}, context={"thread_id": "live"})
ROOT = "/mnt/user-data/outputs/crlf-live"
failures = 0


def put(path: str, data: bytes) -> None:
    sandbox.update_file(path, data) if hasattr(sandbox, "update_file") else sandbox.write_file(path, data.decode())


def stored(path: str) -> bytes:
    return sandbox.download_file(path)


def check(name: str, got, want) -> None:
    global failures
    ok = got == want
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (want {want!r})"))


def str_replace(path, old, new, replace_all=False):
    return tools.str_replace_tool.func(runtime=runtime, description="live", path=path, old_str=old, new_str=new, replace_all=replace_all)


def ranged(path, start, end):
    return tools.read_file_tool.func(runtime=runtime, path=path, start_line=start, end_line=end)


sandbox.execute_command(f"rm -rf {ROOT} && mkdir -p {ROOT}")

# The four files from the first round: a one-word edit keeps every byte else.
for name, data, want in [
    ("crlf", b"@echo off\r\nset NAME=old\r\necho %NAME%\r\n", b"@echo off\r\nset NAME=new\r\necho %NAME%\r\n"),
    ("cr-only", b"one\rtwo old\rthree\r", b"one\rtwo new\rthree\r"),
    ("mixed", b"one\r\ntwo old\nthree\rfour", b"one\r\ntwo new\nthree\rfour"),
    ("lf", b"one\ntwo old\nthree\n", b"one\ntwo new\nthree\n"),
]:
    path = f"{ROOT}/{name}.txt"
    put(path, data)
    check(f"full read of {name} returns stored bytes", sandbox.read_file(path).encode(), data)
    check(f"str_replace on {name}", (str_replace(path, "old", "new"), stored(path)), ("OK", want))

# Round 1: a ranged read spanning CRLF -> LF.
path = f"{ROOT}/span.txt"
put(path, b"a\r\nb\r\nc\r\nd\ne\n")
old = ranged(path, 3, 5)
check("ranged read 3-5", old, "c\nd\ne")
check("str_replace of the ranged read", (str_replace(path, old, old.upper()), stored(path)), ("OK", b"a\r\nb\r\nC\r\nD\nE\n"))

# Round 2 (Willem): the mixed span comes first; the same text recurs with LF only / CRLF only.
for label, data, first, every in [
    ("later LF-only", b"a\r\nb\nc\nsep\na\nb\nc\n", b"A\r\nB\nC\nsep\na\nb\nc\n", b"A\r\nB\nC\nsep\nA\nB\nC\n"),
    ("later CRLF-only", b"a\r\nb\nc\nsep\na\r\nb\r\nc\r\n", b"A\r\nB\nC\nsep\na\r\nb\r\nc\r\n", b"A\r\nB\nC\nsep\nA\r\nB\r\nC\r\n"),
]:
    path = f"{ROOT}/order.txt"
    put(path, data)
    old = ranged(path, 1, 3)
    check(f"{label}: ranged read", old, "a\nb\nc")
    check(f"{label}: default edit changes the first match", (str_replace(path, old, old.upper()), stored(path)), ("OK", first))
    put(path, data)
    check(f"{label}: replace_all changes every match", (str_replace(path, old, old.upper(), True), stored(path)), ("OK", every))

# A snippet with CRLF (only a full read shows one) edits the CRLF copy, not an earlier LF one.
path = f"{ROOT}/verbatim.txt"
put(path, b"x\ny\nx\r\ny\n")
check("CRLF snippet edits the CRLF copy", (str_replace(path, "x\r\ny", "Q"), stored(path)), ("OK", b"x\ny\nQ\n"))

# A ranged read near the end of an 88 MB newline-dense CRLF file.
dense = f"{ROOT}/dense.txt"
sandbox.execute_command(f"seq 1 10000000 | sed 's/$/\\r/' > {dense}")
check("ranged read of lines 9999998-10000000", ranged(dense, 9999998, 10000000), "9999998\n9999999\n10000000")

# Oversized file: read_file and str_replace fail, the gate blocks write_file, the file is unchanged.
huge = f"{ROOT}/huge.log"
sandbox.execute_command(f"head -c 110000000 /dev/zero | tr '\\0' 'a' > {huge} && echo read >> {huge} && md5sum {huge} > {huge}.md5")
before = sandbox.execute_command(f"md5sum {huge}")
check("str_replace on >100 MB file", str_replace(huge, "read", "x").startswith("Error: "), True)
gate = ReadBeforeWriteMiddleware()
for name, args in [
    ("write_file", {"path": huge, "content": "replaced"}),
    ("write_file", {"path": huge, "content": "more", "append": True}),
    ("str_replace", {"path": huge, "old_str": "read", "new_str": "x"}),
]:
    tool = {"write_file": tools.write_file_tool, "str_replace": tools.str_replace_tool}[name]
    request = ToolCallRequest(tool_call={"name": name, "args": args, "id": "c1"}, tool=None, state={"messages": []}, runtime=runtime)
    result = gate.wrap_tool_call(request, lambda req: ToolMessage(content=tool.func(runtime=runtime, **req.tool_call["args"]), tool_call_id="c1", name=name))
    check(f"gate blocks {name}{' (append)' if args.get('append') else ''} on >100 MB file", (result.status, WRITE_BLOCK_KEY in result.additional_kwargs), ("error", True))
check(">100 MB file unchanged", sandbox.execute_command(f"md5sum {huge}"), before)

print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
