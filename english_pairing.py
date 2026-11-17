"""Source-backed English phrase retrieval across fragmented PDF artwork text.

The master is a *search template*, not extracted content. Every returned
character must originate from literal PDF text. Unicode format marks,
punctuation/spacing variation, and independent 202X year placeholders are
handled without inventing actual wording or numbers.
"""
import re
import unicodedata

_SCRIPT = re.compile(r"[가-힣\u0e00-\u0e7f\u0400-\u052f\u0600-\u06ff]")
_WORD = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
_NUMERIC_FRAGMENT = re.compile(r"^(?:\(?\d{1,4}(?:[.,]\d+)?%?\)?|\d{1,3}\s*[Xx]|N[°º]?\d+)$", re.I)


def _reference_english(text):
    text = str(text or "").strip()
    if not text:
        return ""
    text = re.split(r"\s+(?:or|또는)\s+", text, maxsplit=1, flags=re.I)[0]
    # Editorial notes in the ledger cell are not printed copy.
    text = re.sub(r"\s*\((?:in a|please|e\.g)[^)]*\)", "", text, flags=re.I).strip()
    if _SCRIPT.search(text):
        return ""
    return text


def _compact_with_offsets(text):
    """Normalized search characters and their original text offsets."""
    normalized, offsets = [], []
    for pos, ch in enumerate(str(text or "")):
        if unicodedata.category(ch) == "Cf":
            continue  # Zero-width marks in the workbook and PDF
        # Keep alphabetic text and numeric values; punctuation is a
        # formatting separator, except percent which is a meaningful unit.
        for letter in unicodedata.normalize("NFKC", ch).casefold():
            if letter.isascii() and (letter.isalnum() or letter == "%"):
                normalized.append(letter)
                offsets.append(pos)
    return "".join(normalized), offsets


def _variables(escaped):
    """Ledger placeholders: 202X = a year, 'UP TO YX' = a printed multiplier."""
    return escaped.replace("202x", r"202\d").replace("uptoyx", r"upto\d{1,2}x")


def _target_pattern(reference):
    compact, _ = _compact_with_offsets(reference)
    if len(compact) < 5:
        return None
    return re.compile(_variables(re.escape(compact)), re.I)


def _source_match(raw, pattern, reference=""):
    compact, offsets = _compact_with_offsets(raw)
    m = pattern.search(compact)
    if not (m and offsets):
        return ""
    begin, end = offsets[m.start()], offsets[m.end()-1]+1
    # Preserve punctuation physically printed at the boundaries: '(1)' at
    # the beginning of a footnote and the final period in a source citation.
    ref = str(reference or "").strip()
    if ref.startswith("(") and begin > 0 and raw[begin-1] == "(":
        begin -= 1
    if ref.endswith((".", ")")) and end < len(raw) and raw[end] == ref[-1]:
        end += 1
    return raw[begin:end].strip()


def _source_prefix(raw, reference):
    """Get a prefix of the visible text starting at the reference beginning."""
    compact, offsets = _compact_with_offsets(raw)
    target, _ = _compact_with_offsets(reference)
    if len(target) < 5 or not compact:
        return ""
    start = compact.find(target[:min(4, len(target), len(compact))])
    if start < 0:
        return ""
    return raw[offsets[start]:]


def _english_line(line):
    value = str(line.get("text") or "").strip()
    return bool(value and not _SCRIPT.search(value) and
                (_WORD.search(value) or _NUMERIC_FRAGMENT.fullmatch(value)))


def _near(left, right):
    """Connected PDF glyph boxes, irrespective of rotation or extraction order."""
    a,b=left.get("bbox"),right.get("bbox")
    if not a or not b or len(a)!=4 or len(b)!=4:
        return False
    xgap = max(0, float(b[0])-float(a[2]), float(a[0])-float(b[2]))
    ygap = max(0, float(b[1])-float(a[3]), float(a[1])-float(b[3]))
    center_x = abs((float(a[0])+float(a[2]))/2-(float(b[0])+float(b[2]))/2)
    return xgap <= 24 and ygap <= 34 and center_x <= 200


def _is_prefix(candidate, target):
    """Accept a valid partial reference or a complete reference with suffix."""
    have,_ = _compact_with_offsets(candidate)
    expected,_ = _compact_with_offsets(target)
    if not have or not expected:
        return False
    full = re.compile(_variables(re.escape(expected)))
    if full.match(have):
        return True  # PDF line may continue with unrelated translated content
    if len(have) > len(expected):
        return False
    projected = expected[:len(have)]
    return bool(re.fullmatch(
        _variables(re.escape(projected)), have
    ))


def _observed_reference_hint(korean):
    """Narrow bilingual search hints for printed master-unregistered claims.

    A hint is never output directly. The returned text must be independently
    found in the original PDF native evidence before being displayed.
    """
    korean = str(korean or "")
    if re.search(r"견고한\s*손잡이|안정적인\s*견고한\s*손잡이", korean):
        return "UP TO 100KG - ROBUST HANDLE"
    coating = re.search(r"테팔\s*기본\s*코팅\s*대비\s*최대\s*(\d{1,2})\s*배", korean)
    if coating:
        return f"UP TO {coating.group(1)}X MORE RESISTANT THAN TEFAL BASIC COATING"
    if re.search(r"편수냄비\s*\(?\s*뚜껑\s*포함\s*\)?", korean):
        return "SAUCEPAN WITH LID"
    if re.search(r"양수냄비\s*\(?\s*뚜껑\s*포함\s*\)?", korean):
        return "STEWPOT WITH LID"
    # Storage footnote: the printed counts decide the English wording.
    pots = re.search(r"(편수|양수)냄비\s*(\d+)\s*개\s*(?:,|및)?\s*뚜껑\s*(\d+)\s*개", korean)
    if pots:
        kind = "SAUCEPANS" if pots.group(1) == "편수" else "STEWPOTS"
        return (f"TESTED ON {pots.group(2)} {kind} AND {pots.group(3)} LIDS"
                " BETWEEN A PREVIOUS TEFAL RANGE AND A NEW GENERATION RANGE")
    years = re.search(r"(\d{1,2})\s*년\s*품질\s*보증", korean)
    if years:
        return f"{years.group(1)} YEARS GUARANTEE"
    return ""


def find_english_counterpart(match, summaries):
    """Find source English on the correct PDF page; never use master as fallback.

    Handles up to six geometrically connected PDF text objects. Search is
    prefix-pruned and bounded; unrelated neighboring sentences are excluded.
    """
    tried=[]
    hint=_observed_reference_hint(match.get("extracted"))
    # A long hint may run past what is printed; fall back to its first clause.
    short_hint=re.split(r"\s+BETWEEN\s+", hint)[0] if hint else ""
    for reference in (_reference_english(match.get("reference_english")), hint, short_hint):
        if reference and reference not in tried:
            tried.append(reference)
            found=_find_reference(match, summaries, reference)
            if found:
                return _tidy(found)
    # 'UP TO YX': the multiplier is often a large graphic numeral with no
    # text layer, which breaks the chain. Find the printed words on each side
    # and mark the unreadable number with □ (never fill it in).
    for reference in tried:
        split=re.split(r"(?i)\s*\bUP\s+TO\s+Y\s*X\b\s*", reference)
        if len(split)==2 and all(split):
            head=_find_reference(match, summaries, split[0].strip()+" UP TO")
            tail=_find_reference(match, summaries, split[1].strip())
            if head and tail:
                return _tidy(f"{head} □ {tail}")
    return ""


def _tidy(text):
    """Curved lettering comes out as 1–2 letter pieces ('FR YP AN')."""
    parts=text.split()
    if len(parts)>1 and all(len(p)<=2 and p.isalpha() for p in parts):
        return "".join(parts)
    return text


def _find_reference(match, summaries, reference):
    pattern=_target_pattern(reference)
    if not pattern:
        return ""
    lines=[
        entry for summary in summaries
        if summary.get("file")==match.get("file")
        and int(summary.get("page",0))==int(match.get("page",0))
        for entry in summary.get("raw_evidence",[])
        if _english_line(entry)
    ]
    for entry in lines:
        found=_source_match(entry["text"],pattern,reference)
        if found:
            return found
    # Only start at a PDF line containing the beginning of the reference.
    # A numeric-only line cannot initiate an unrelated match.
    max_nodes=6
    for start_index,entry in enumerate(lines):
        beginning=_source_prefix(entry["text"],reference)
        if not beginning:
            continue
        if not _is_prefix(beginning,reference):
            continue
        stack=[(beginning,(start_index,))]
        visited=set()
        while stack:
            current, selected=stack.pop()
            if (selected,_compact_with_offsets(current)[0]) in visited:
                continue
            visited.add((selected,_compact_with_offsets(current)[0]))
            found=_source_match(current,pattern,reference)
            if found:
                return found
            if len(selected)>=max_nodes:
                continue
            tail=lines[selected[-1]]
            options=[]
            for ix,newline in enumerate(lines):
                if ix in selected or not _near(tail,newline):
                    continue
                # The next text object must advance the observed phrase.
                candidate=current.rstrip()+" "+newline["text"].lstrip()
                if not _is_prefix(candidate,reference):
                    continue
                options.append((ix,candidate))
            # deterministic search order; the shortest resulting chain wins
            for ix,candidate in reversed(options):
                stack.append((candidate,selected+(ix,)))
    return ""


def build_reviewer_pairs(matches,summaries,display_text):
    return [{
        "file":m.get("file",""),"category":m.get("category") or "미분류",
        "korean_extracted":display_text(m),
        "english_extracted":find_english_counterpart(m,summaries),
        "korean_reference":m.get("reference_korean") or "",
        "english_reference":m.get("reference_english") or "",
        "match":m,
    } for m in matches]
