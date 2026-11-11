"""Reviewer-facing display labels; never replace source filenames in exports or matching keys."""
TYPE_KO = {
    "SAUCEPAN": "편수냄비", "STEWPOT": "양수냄비", "FRYPAN": "프라이팬",
    "WOK": "볶음팬", "PANCAKE": "팬케이크팬", "SET": "세트",
}

def product_title(metadata):
    """Use PDF-derived details only. Missing values remain explicitly unknown."""
    name = str(metadata.get("range_name") or "").strip()
    if name.upper() in {"UNKNOWN", "NONE", "N/A"}:
        name = ""
    code = str(metadata.get("product_type_standard") or "").upper()
    kind = TYPE_KO.get(code, "")
    size = metadata.get("size_cm")
    size_text = f"{int(size)}cm" if isinstance(size, (float, int)) and size > 0 else ""
    parts = [x for x in (name, kind, size_text) if x]
    return " · ".join(parts) if parts else "제품정보 확인 필요"

def product_labels(metadata, filenames):
    """Keep products distinguishable even when their extracted names coincide."""
    by_file = {m["file"]: product_title(m) for m in metadata}
    titles = {file: by_file.get(file, "제품정보 확인 필요") for file in filenames}
    count = {}
    out = {}
    for file in sorted(titles):
        title = titles[file]
        count[title] = count.get(title, 0) + 1
        out[file] = f"{title} (파일 {count[title]})" if list(titles.values()).count(title) > 1 else title
    return out

def display_file_table(records, labels, file_key="file", label="제품"):
    """Return presentation copies. Source records remain untouched."""
    return [{label: labels.get(r.get(file_key), "제품정보 확인 필요"),
             **{k:v for k,v in r.items() if k != file_key}}
            for r in records]
