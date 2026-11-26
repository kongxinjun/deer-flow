"""Seeded fuzzing of str_replace's line-ending matcher against a reference model.

    cd backend && uv run python ../hunt/aio-line-endings/fuzz_matcher.py [--seed N] [--cases N] [--impl new|head] [--e2e]

Checks, on random files mixing "\\r\\n", "\\n" and "\\r" and on snippets taken from
ranged reads, full reads or typed text:
  1. the matcher equals the reference model (first / every match in file order,
     bytes outside the matches unchanged, new_str in the ending of the line
     the match starts on, not found -> None);
  2. on files with one line ending, the result equals origin/main's matcher;
  3. a snippet from a ranged read is never reported missing (files without
     a line ending in several CRs);
  4. with --e2e, the real read_file/str_replace tools over the offline AIO
     SDK transport write exactly the reference bytes, and leave the file
     byte-identical when nothing matches.
Prints the first counterexample per check and exits non-zero on any failure.
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deerflow.sandbox.read_file_contract import split_file_lines  # noqa: E402

PIECES = ("a", "b", "\r\n", "\n", "\r")


def main_replace(content, old_str, new_str, replace_all):
    """origin/main's matcher (_match_line_endings + str.replace)."""

    def to_crlf(text):
        return text.replace("\r\n", "\n").replace("\n", "\r\n")

    if "\r\n" in content:
        crlf_old = to_crlf(old_str)
        if content.count("\r\n") == content.count("\n") or (old_str not in content and crlf_old in content):
            old_str, new_str = crlf_old, to_crlf(new_str)
    if not content or old_str not in content:
        return None
    return content.replace(old_str, new_str) if replace_all else content.replace(old_str, new_str, 1)


def reference(content, old_str, new_str, replace_all):
    """The documented rule on units: a CRLF in the file or in old_str is one unit."""
    if not old_str:
        return content
    if "\r\n" not in content:
        return main_replace(content, old_str, new_str, replace_all)
    units, i = [], 0
    while i < len(content):
        units.append("\r\n" if content.startswith("\r\n", i) else content[i])
        i += len(units[-1])
    needle: list[str] = []
    i = 0
    while i < len(old_str):
        needle.append("\r\n" if old_str.startswith("\r\n", i) else old_str[i])
        i += len(needle[-1])
    new_lines = new_str.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = copied = 0
    found = False
    while i + len(needle) <= len(units):
        # "\r\n" matches only a CRLF, "\n" either ending, anything else itself.
        if not all(want == u or (want == "\n" and u == "\r\n") for want, u in zip(needle, units[i : i + len(needle)])):
            i += 1
            continue
        found = True
        endings = [u for u in units[i : i + len(needle)] if u in ("\n", "\r\n")]
        if not endings:
            endings = [u for u in units[i:] if u in ("\n", "\r\n")][:1] or [u for u in units[:i] if u in ("\n", "\r\n")][-1:]
        spelled = new_lines[0] + "".join(endings[min(n, len(endings) - 1)] + line for n, line in enumerate(new_lines[1:]))
        out += units[copied:i] + [spelled]
        i = copied = i + len(needle)
        if not replace_all:
            break
    return "".join(out + units[copied:]) if found else None


def draw_case(rng, pieces=PIECES, max_len=30):
    content = "".join(rng.choices(pieces, k=rng.randint(0, max_len)))
    lines = split_file_lines(content)
    source = rng.choice(["ranged", "full", "typed"])
    if source == "ranged" and lines:
        first = rng.randrange(len(lines))
        text = "\n".join(lines[first : rng.randint(first, len(lines) - 1) + 1])
    elif source == "full":
        text = content
    else:
        text = "".join(rng.choices(PIECES, k=rng.randint(1, 6)))
    start = rng.randint(0, len(text))
    old_str = text[start : rng.randint(start, len(text))]
    new_str = "".join(rng.choices(("X", "\n", "\r\n", "\r"), k=rng.randint(0, 4)))
    return content, old_str, new_str, rng.random() < 0.5


def run(args):
    if args.impl == "head":
        from head_3f34c135f_matcher import _replace_keeping_line_endings as impl
    else:
        from deerflow.sandbox.tools import _replace_keeping_line_endings as impl
    rng = random.Random(args.seed)
    failures = {}

    def fail(check, case, got, want):
        failures.setdefault(check, (case, got, want))

    for _ in range(args.cases):
        case = draw_case(rng)
        content, old_str, new_str, replace_all = case
        got = impl(content, old_str, new_str, replace_all)
        want = reference(content, old_str, new_str, replace_all)
        if old_str and got != want:
            fail("reference", case, got, want)
        ending = rng.choice(["\n", "\r\n"])
        uni = content.replace("\r\n", "\n").replace("\r", "").replace("\n", ending)
        uni_old = old_str.replace("\r\n", "\n").replace("\r", "").replace("\n", rng.choice(["\n", "\r\n"]))
        if uni_old and impl(uni, uni_old, new_str, replace_all) != main_replace(uni, uni_old, new_str, replace_all):
            fail("main-parity", (uni, uni_old, new_str, replace_all), impl(uni, uni_old, new_str, replace_all), main_replace(uni, uni_old, new_str, replace_all))
        lines = split_file_lines(content)
        if lines and "\r\r\n" not in content:
            first = rng.randrange(len(lines))
            snippet = "\n".join(lines[first : rng.randint(first, len(lines) - 1) + 1])
            if snippet and impl(content, snippet, new_str, replace_all) is None:
                fail("ranged-read-found", (content, snippet, new_str, replace_all), None, "a match")

    if args.e2e:
        from offline_aio import bind_tools, offline_aio_sandbox

        with offline_aio_sandbox() as (sandbox, routes):
            import deerflow.sandbox.tools as tools

            runtime = bind_tools(sandbox)
            path = "/mnt/user-data/outputs/fuzz.txt"
            for _ in range(max(1, args.cases // 20)):
                case = draw_case(rng)
                content, old_str, new_str, replace_all = case
                if not old_str:
                    continue
                routes.files[path] = content.encode()
                result = tools.str_replace_tool.func(runtime=runtime, description="fuzz", path=path, old_str=old_str, new_str=new_str, replace_all=replace_all)
                want = reference(content, old_str, new_str, replace_all)
                after = routes.files[path]
                if (want is None and (not result.startswith("Error: String to replace not found") or after != content.encode())) or (want is not None and (result != "OK" or after != want.encode())):
                    fail("e2e-offline-aio", case, (result, after), want)

    for check, (case, got, want) in failures.items():
        print(f"FAIL {check}: case={case!r}\n     got ={got!r}\n     want={want!r}")
    print(f"{args.impl}: {args.cases} cases, seed {args.seed}: {'all checks passed' if not failures else f'{len(failures)} check(s) failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cases", type=int, default=100_000)
    parser.add_argument("--impl", choices=["new", "head"], default="new")
    parser.add_argument("--e2e", action="store_true")
    sys.exit(run(parser.parse_args()))
