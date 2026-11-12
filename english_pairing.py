"""Find English printed in PDF artwork, including wrapped/rotated text.

The master only supplies a search target. Returned English always consists of
literal native PDF glyphs. Unknown English is never filled from the master.
"""
import re
from itertools import permutations

_SCRIPT = re.compile(r"[가-힣\u0e00-\u0e7f\u0400-\u052f\u0600-\u06ff]")
_WORD = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def _reference_english(text):
    text = str(text or "").strip()
    if not text:
        return ""
    # The reference workbook sometimes says "English or Korean". That is
    # editorial guidance, not one full English artwork sentence.
    text = re.split(r"\s+(?:or|또는)\s+", text, maxsplit=1, flags=re.I)[0]
    if _SCRIPT.search(text):
        return ""
    return text


def _pattern(value):
    """Allow line wrapping, hyphen/space differences and independent 202X years."""
    # Exact words and all numeric literals are preserved. 202X is the only
    # variable year placeholder and matches 2020–2029 independently.
    tokens = re.split(r"[-\u2010-\u2015\s]+", value.strip())
    if len(tokens) < 2:
        return None
    fragments = []
    for token in tokens:
        if not token:
            continue
        literal = re.escape(token)
        literal = literal.replace("202X", r"202\d").replace("202x", r"202\d")
        fragments.append(literal)
    if len(fragments) < 2:
        return None
    return re.compile(
        r"(?<![A-Za-z0-9])" +
        r"[-\u2010-\u2015\s]+".join(fragments) +
        r"(?![A-Za-z0-9])", re.I
    )


def _english_line(line):
    value = str(line.get("text") or "").strip()
    return bool(value and _WORD.search(value) and not _SCRIPT.search(value[:80]))


def _near(left, right):
    """Physically adjacent boxes, regardless of PDF extraction line order.

    Artwork uses rotated text and multi-column layouts. The second part can
    be located ABOVE the first part, so y must not be assumed increasing.
    """
    a, b = left.get("bbox"), right.get("bbox")
    if not a or not b or len(a) != 4 or len(b) != 4:
        return False
    xgap = max(0, float(b[0])-float(a[2]), float(a[0])-float(b[2]))
    ygap = max(0, float(b[1])-float(a[3]), float(a[1])-float(b[3]))
    # Also guard against unrelated neighboring columns and distant captions.
    center_distance_x = abs((float(a[0])+float(a[2]))/2 -
                            (float(b[0])+float(b[2]))/2)
    return xgap <= 24 and ygap <= 32 and center_distance_x <= 200


def find_english_counterpart(match, summaries):
    """Return only source-backed English observed in this file and page.

    Supports up to four nearby native PDF objects. A returned string is the
    source substring (not the normalized master string) and may contain line
    joins, which represent the printed reading order.
    """
    english = _reference_english(match.get("reference_english"))
    pattern = _pattern(english)
    if pattern is None:
        return ""
    lines = [
        line for summary in summaries
        if summary.get("file") == match.get("file")
        and int(summary.get("page", 0)) == int(match.get("page", 0))
        for line in summary.get("raw_evidence", [])
        if _english_line(line)
    ]
    for line in lines:
        result = pattern.search(line["text"])
        if result:
            return result.group(0)
    # Start only where the beginning of the reference was actually seen.
    # This prevents searching arbitrary permutations across the whole page.
    words = _WORD.findall(english)
    if not words:
        return ""
    prefix = re.compile(re.escape(words[0]), re.I)
    for start_index, start_line in enumerate(lines):
        if not prefix.search(start_line["text"]):
            continue
        neighbors = [
            (j, line) for j, line in enumerate(lines)
            if j != start_index and _near(start_line, line)
        ]
        # Keep a small bounded cluster; actual joined captions/footnotes
        # are adjacent and only occupy a few native PDF text objects.
        neighbors.sort(key=lambda item: (
            abs(float(item[1]["bbox"][1])-float(start_line.get("bbox",[0,0])[1])),
            abs(float(item[1]["bbox"][0])-float(start_line.get("bbox",[0])[0]))
        ))
        neighbors = neighbors[:9]
        for count in range(1, min(3, len(neighbors)) + 1):
            for selected in permutations(neighbors, count):
                chosen = [start_line] + [line for _, line in selected]
                # Every added line must be adjacent to an already selected
                # source box; never combine far-away, unrelated phrases.
                if any(not any(_near(line, prev) for prev in chosen[:i])
                       for i, line in enumerate(chosen) if i):
                    continue
                candidate = " ".join(line["text"].strip() for line in chosen)
                found = pattern.search(candidate)
                if found:
                    return found.group(0)
    return ""


def build_reviewer_pairs(matches, summaries, display_text):
    """Keep the same number of Korean inspection items and source IDs."""
    return [
        {
            "file": match.get("file", ""),
            "category": match.get("category") or "미분류",
            "korean_extracted": display_text(match),
            "english_extracted": find_english_counterpart(match, summaries),
            "korean_reference": match.get("reference_korean") or "",
            "english_reference": match.get("reference_english") or "",
            "match": match,
        }
        for match in matches
    ]
