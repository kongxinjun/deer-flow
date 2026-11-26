"""str_replace matcher of PR #8662 at 3f34c135f (before the second review round), for A/B runs."""

import bisect, re
def _to_crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def _match_line_endings(content: str, old_str: str, new_str: str) -> tuple[str, str]:
    """Spell ``old_str`` and ``new_str`` with the CRLF line endings ``content`` uses.

    Full reads return line endings as stored, but the model tends to write
    ``\\n`` (and ranged reads join lines with ``\\n``), so a multi-line
    ``old_str`` would never match a CRLF file and inserted lines would be LF.
    A CRLF-only file takes both strings in CRLF; a mixed file does so only
    when the LF spelling is absent and the CRLF one is present.
    """
    if "\r\n" not in content:
        return old_str, new_str
    crlf_old = _to_crlf(old_str)
    if content.count("\r\n") == content.count("\n") or (old_str not in content and crlf_old in content):
        return crlf_old, _to_crlf(new_str)
    return old_str, new_str


def _replace_across_line_endings(content: str, old_str: str, new_str: str, replace_all: bool) -> str | None:
    """Replace a multi-line ``old_str`` whose span mixes CRLF and LF lines.

    A ranged read of a mixed file joins lines with ``\\n``, so the snippet
    matches neither its literal nor its all-CRLF spelling. Match it against the
    file with CRLF read as LF and replace only the original span, so line
    endings outside it stay as stored. ``new_str`` takes the ending of the
    span's first line break.
    """
    flat_old = old_str.replace("\r\n", "\n")
    if "\r\n" not in content or "\n" not in flat_old:
        return None
    flat = content.replace("\r\n", "\n")
    index = flat.find(flat_old)
    if index < 0:
        return None
    # Where each CRLF's "\n" sits in flat: flat offset i starts in content at
    # i plus the number of CRLFs before it.
    flat_crlf = [m.start() - k for k, m in enumerate(re.finditer("\r\n", content))]
    pieces: list[str] = []
    copied = 0
    while index >= 0:
        flat_end = index + len(flat_old)
        start = index + bisect.bisect_left(flat_crlf, index)
        end = flat_end + bisect.bisect_left(flat_crlf, flat_end)
        span = content[start:end]
        crlf = "\r\n" in span[: span.index("\n") + 1]
        pieces += [content[copied:start], _to_crlf(new_str) if crlf else new_str.replace("\r\n", "\n")]
        copied = end
        index = flat.find(flat_old, flat_end) if replace_all else -1
    pieces.append(content[copied:])
    return "".join(pieces)


def _replace_keeping_line_endings(content: str, old_str: str, new_str: str, replace_all: bool) -> str | None:
    """Return ``content`` with ``old_str`` replaced, or None when it is absent."""
    old_str, new_str = _match_line_endings(content, old_str, new_str)
    if old_str in content:
        return content.replace(old_str, new_str) if replace_all else content.replace(old_str, new_str, 1)
    return _replace_across_line_endings(content, old_str, new_str, replace_all)
