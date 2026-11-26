# AIO line-ending harness (PR #8662)

Reusable tooling behind the second review round of bytedance/deer-flow#8662.
Nothing here ships; the fix and its regression tests live on `fix-aio-crlf`. This branch sits on the PR head the review was about (3f34c135f), so `--impl new` and the live check need the fixed branch checked out with this directory copied in.
Run everything from `backend/` with `uv run python ../hunt/aio-line-endings/<script>`.

| File | What it does |
| --- | --- |
| `offline_aio.py` | The real `AioSandbox` and `agent_sandbox` SDK over an httpx `MockTransport` that serves the AIO 1.11.0 file routes (download streams stored bytes, 404/400 errors, write keeps `\r`, read normalizes endings). `bind_tools()` points the real sandbox tools at it. |
| `fuzz_matcher.py` | Seeded fuzzing of `_replace_keeping_line_endings` against a unit-by-unit reference model, parity with `origin/main` on one-ending files, "a ranged-read snippet is never missing", and `--e2e` runs through the real tools over `offline_aio.py`. `--impl head` runs the 3f34c135f matcher for A/B. |
| `head_3f34c135f_matcher.py` | The matcher as it was at 3f34c135f (before round 2). |
| `bench_memory.py` | Peak extra memory (tracemalloc), wall time and process max RSS of the splice on newline-dense 1/10/100 MB files, head vs new. `bench-results.txt` has the numbers from an M-series Mac. |
| `bench_ranged_read.py` | Peak extra memory of one ranged read near the end of a 100 MB file: `split_file_lines` vs `slice_file_lines`. Numbers in `bench-ranged-read.txt`. |
| `live_aio_check.py` | Live check against a real AIO container: the four first-round files, the ranged-read span, both of Willem's ordering scenarios (default and `replace_all`), a CRLF snippet that must edit the CRLF copy, a ranged read at the end of an 88 MB newline-dense file, and a 110 MB file through `str_replace` and the read-before-write gate. |
| `probe_routes.py`, `probe_binary.py` | Raw HTTP probes of the AIO file routes that `offline_aio.py` emulates. |

## Results at the time of writing

- `fuzz_matcher.py --cases 200000 --e2e`, seeds 1-3: all checks passed (600k matcher cases, 30k end-to-end tool runs). `--impl head` fails the reference check on seed 1 within 20k cases.
- `live_aio_check.py` on `ghcr.io/agent-infra/sandbox` 1.11.0: 23/23 on the fixed branch. On 3f34c135f the four ordering checks fail and `write_file` overwrites the 110 MB file unread.
- `bench_memory.py`, 100 MB mixed file, one edit spanning CRLF -> LF: head 1609 MiB extra / 4.3 GiB RSS, new 292 MiB / 0.75 GiB. `replace_all` with one mixed match every two lines: head 2045 MiB / 6.4 GiB, new 260 MiB / 0.57 GiB (9 s, about 1 us per match). All-CRLF files and edits without line breaks run as one `str.replace`: 1x the file, as before.
- `bench_ranged_read.py`, last 40 lines of a 100 MB file: `split_file_lines` 0.5-2.0 GiB extra, `slice_file_lines` under 0.1 MiB.
