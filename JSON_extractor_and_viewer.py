import json
import io
import re
from typing import Any, Dict, List, Tuple, Union

import streamlit as st

st.set_page_config(page_title="JSON Viewer", page_icon="🧩", layout="wide")

# ============================
# Normalization & Utilities
# ============================

def looks_like_json(s: str) -> bool:
    s = s.strip()
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))

def try_json_loads_once(text: str) -> Tuple[Any, str]:
    """
    Try json.loads once; return (obj, error_msg).
    If fails, return (None, error_msg).
    """
    try:
        return json.loads(text), ""
    except Exception as e:
        return None, str(e)

def decode_escaped_json(s: str) -> Tuple[Any, str]:
    """
    Handle inputs like:
      - "{\"key\":\"AIRCRAFT\",\"value\":false,...}"
      - 0: ""{\"key\":\"AIRCRAFT\"...}""  (index + quoted/escaped blob)
    Strategy:
      1) Strip index prefixes: `^\s*\d+\s*:\s*`
      2) Trim outer quotes if present.
      3) Unescape common artifacts (double quotes, extraneous quotes).
      4) Attempt json.loads (double-pass if needed).
    """
    original = s

    # 1) Strip index prefixes like `0: ` or `12 :`
    s = re.sub(r'^\s*\d+\s*:\s*', '', s)

    # 2) Trim whitespace & outer quotes
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]

    # 3) If content is escaped JSON (contains \" and starts with { or [ after unescape)
    #    Try a double decode: first parse the string, then parse its content
    # Attempt pass #1
    obj, err = try_json_loads_once(s)
    if obj is not None:
        # Sometimes the first parse yields a string that itself is JSON -> pass #2
        if isinstance(obj, str):
            inner_obj, err2 = try_json_loads_once(obj)
            if inner_obj is not None:
                return inner_obj, ""
            else:
                # Not truly JSON inside; treat as a primitive string
                return obj, ""
        return obj, ""

    # 4) Heuristic cleanups and retry
    # Remove any stray outer quotes again
    s2 = s.strip()
    if (s2.startswith('"') and s2.endswith('"')) or (s2.startswith("'") and s2.endswith("'")):
        s2 = s2[1:-1]

    # Replace doubled quotes like ""{...}"" -> "{...}"
    s2 = re.sub(r'^\s*""(.*)""\s*$', r'"\1"', s2)

    obj2, err2 = try_json_loads_once(s2)
    if obj2 is not None:
        if isinstance(obj2, str):
            inner_obj2, err3 = try_json_loads_once(obj2)
            if inner_obj2 is not None:
                return inner_obj2, ""
            else:
                return obj2, ""
        return obj2, ""

    # Final fallback: if it looks like JSON after unescaping backslashes, try again
    s3 = s2.encode("utf-8").decode("unicode_escape")
    obj3, err3 = try_json_loads_once(s3)
    if obj3 is not None:
        if isinstance(obj3, str):
            inner_obj3, err4 = try_json_loads_once(obj3)
            if inner_obj3 is not None:
                return inner_obj3, ""
            else:
                return obj3, ""
        return obj3, ""

    return None, f"Failed to decode escaped JSON. Attempts: {err} | {err2} | {err3}"

def explode_lines(text: str) -> List[str]:
    """
    Split input into candidate JSON segments.
    - If the whole text is valid JSON, return [text].
    - Else try to split on newlines and commas safely.
    """
    t = text.strip()

    # If it's already valid JSON (object or array), keep whole
    obj, _ = try_json_loads_once(t)
    if obj is not None:
        return [t]

    # Otherwise, split lines
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines

    # Single-line but possibly multi-JSON concatenated (rare):
    # Try to split on `}\s*,\s*{` for sequences of objects
    parts = re.split(r'}\s*,\s*{', t)
    if len(parts) > 1:
        parts = [parts[0] + "}"] + ["{" + p for p in parts[1:]]
        return parts

    # Fallback: return as single segment
    return [t]

def normalize_input_to_json(text: str) -> Tuple[Union[Dict, List, None], List[Any], List[str]]:
    """
    Normalize arbitrary input into:
      - a single JSON object/array if possible
      - otherwise a list of parsed JSON entries
    Returns: (single_json, list_entries, errors)
    """
    errors = []
    single_json = None
    entries = []

    # If clean JSON, done
    if looks_like_json(text):
        obj, err = try_json_loads_once(text)
        if obj is not None:
            single_json = obj
            return single_json, entries, errors
        else:
            errors.append(f"Parse error: {err}")

    # Explode into candidate segments
    segments = explode_lines(text)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # If segment looks like JSON, parse directly
        if looks_like_json(seg):
            obj, err = try_json_loads_once(seg)
            if obj is None:
                # Try decode escaped JSON as fallback
                obj, err = decode_escaped_json(seg)
            if obj is not None:
                entries.append(obj)
            else:
                errors.append(f"Segment failed: {err}\nSegment: {seg[:200]}")
        else:
            # Try decode escaped/quoted JSON (e.g., 0: ""{\"k\":\"v\"}"" )
            obj, err = decode_escaped_json(seg)
            if obj is not None:
                entries.append(obj)
            else:
                errors.append(f"Segment failed: {err}\nSegment: {seg[:200]}")

    # If we parsed multiple entries, wrap into an array
    if entries and single_json is None:
        single_json = entries if len(entries) > 1 else entries[0]

    return single_json, entries, errors


def type_label(v: Any) -> str:
    if isinstance(v, dict):
        return f"object • {len(v)} key(s)"
    if isinstance(v, list):
        return f"array • {len(v)} item(s)"
    if isinstance(v, str):
        return "string"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if v is None:
        return "null"
    return type(v).__name__


def render_tree(node: Any):
    if isinstance(node, dict):
        for k, v in node.items():
            with st.expander(f'🔹 "{k}"  ({type_label(v)})', expanded=False):
                render_tree(v)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            with st.expander(f"🔸 [{i}]  ({type_label(v)})", expanded=False):
                render_tree(v)
    else:
        col1, col2 = st.columns([2, 1])
        with col1:
            st.write(node)
        with col2:
            st.caption(type_label(node))


def search_json(node: Any, query: str, path: str = "") -> List[str]:
    hits = []
    q = query.lower()
    if isinstance(node, dict):
        for k, v in node.items():
            k_path = f'{path}.{k}' if path else k
            if q in str(k).lower():
                hits.append(k_path)
            if isinstance(v, (dict, list)):
                hits.extend(search_json(v, q, k_path))
            else:
                if q in str(v).lower():
                    hits.append(k_path)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            i_path = f"{path}[{i}]"
            if isinstance(v, (dict, list)):
                hits.extend(search_json(v, q, i_path))
            else:
                if q in str(v).lower():
                    hits.append(i_path)
    # unique preserve order
    seen = set()
    out = []
    for h in hits:
        if h not in seen:
            out.append(h)
            seen.add(h)
    return out


def extract_by_path(node: Any, path: str) -> Any:
    if not path:
        return node
    tokens = []
    for segment in path.split("."):
        parts = re.findall(r"[^\[\]]+|\[\d+\]", segment)
        tokens.extend(parts)
    cur = node
    for tok in tokens:
        if tok.startswith("["):
            idx = int(tok[1:-1])
            if not isinstance(cur, list) or idx >= len(cur):
                raise KeyError(f"Index out of range at {tok}")
            cur = cur[idx]
        else:
            if not isinstance(cur, dict) or tok not in cur:
                raise KeyError(f"Key not found: {tok}")
            cur = cur[tok]
    return cur


def count_nodes(node: Any) -> Dict[str, int]:
    stats = {"objects": 0, "arrays": 0, "strings": 0, "numbers": 0, "booleans": 0, "nulls": 0, "total_nodes": 0}
    def _walk(n: Any):
        stats["total_nodes"] += 1
        if isinstance(n, dict):
            stats["objects"] += 1
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            stats["arrays"] += 1
            for v in n:
                _walk(v)
        elif isinstance(n, str):
            stats["strings"] += 1
        elif isinstance(n, (int, float)):
            stats["numbers"] += 1
        elif isinstance(n, bool):
            stats["booleans"] += 1
        elif n is None:
            stats["nulls"] += 1
        else:
            stats["strings"] += 1
    _walk(node)
    return stats

# ============================
# UI
# ============================

st.title("🧩 JSON Viewer & Normalizer")
st.caption("Paste tricky JSON (escaped strings, indexed lines) — it will decode & parse automatically.")

src = st.sidebar.radio("Input source", ["Upload file", "Paste"], index=1)
uploaded = None
pasted = None

if src == "Upload file":
    uploaded = st.sidebar.file_uploader("Choose a file", type=["json", "txt", "log"])
else:
    pasted = st.sidebar.text_area(
        "Paste JSON or JSON-like text",
        height=220,
        placeholder='Examples:\n'
                    '1) {"key":"AIRCRAFT","value":false,"metadata":{"score":2.779960632324219E-4}}\n'
                    '2) 0: ""{\\"key\\":\\"AIRCRAFT\\",\\"value\\":false,\\"metadata\\":{\\"score\\":2.779960632324219E-4}}""\n'
                    '3) One JSON object per line',
    )

pretty_download = st.sidebar.checkbox("Pretty download", value=True)

errors = []
json_obj = None
list_entries: List[Any] = []

if uploaded:
    try:
        content = uploaded.read().decode("utf-8-sig", errors="replace")
        json_obj, list_entries, errors = normalize_input_to_json(content)
    except Exception as e:
        errors.append(f"Failed to read file: {e}")
elif pasted:
    json_obj, list_entries, errors = normalize_input_to_json(pasted)

if json_obj is None and not errors:
    st.info("Provide input to begin. You can paste raw JSON, escaped JSON strings, or logs with indices.")
elif json_obj is not None:
    st.success("JSON parsed successfully.")
    tabs = st.tabs(["Tree", "Raw", "Search", "Path Extract", "Stats", "Download"])

    with tabs[0]:
        st.subheader("Tree View")
        render_tree(json_obj)

    with tabs[1]:
        st.subheader("Raw JSON")
        pretty = st.toggle("Pretty print", value=True)
        if pretty:
            st.code(json.dumps(json_obj, indent=2, ensure_ascii=False), language="json")
        else:
            st.code(json.dumps(json_obj, separators=(",", ":"), ensure_ascii=False), language="json")

    with tabs[2]:
        st.subheader("Search")
        q = st.text_input("Search keys/values (case-insensitive)")
        if q:
            hits = search_json(json_obj, q)
            st.caption(f"Matches: {len(hits)}")
            if hits:
                for h in hits[:500]:
                    with st.expander(h, expanded=False):
                        try:
                            st.write(extract_by_path(json_obj, h))
                        except Exception as e:
                            st.warning(f"Extraction error: {e}")
            else:
                st.info("No matches found.")

    with tabs[3]:
        st.subheader("Path Extract")
        path = st.text_input("Path (e.g., metadata.score or items[0].id)")
        if st.button("Extract", type="primary"):
            if path.strip():
                try:
                    val = extract_by_path(json_obj, path.strip())
                    st.success(f"Value at `{path}`:")
                    st.write(val)
                except Exception as e:
                    st.error(str(e))
            else:
                st.warning("Enter a path.")

    with tabs[4]:
        st.subheader("Stats")
        stats = count_nodes(json_obj)
        colA, colB, colC = st.columns(3)
        with colA:
            st.metric("Objects", stats["objects"])
            st.metric("Arrays", stats["arrays"])
        with colB:
            st.metric("Strings", stats["strings"])
            st.metric("Numbers", stats["numbers"])
        with colC:
            st.metric("Booleans", stats["booleans"])
            st.metric("Nulls", stats["nulls"])
        st.caption(f"Total nodes traversed: {stats['total_nodes']}")

    with tabs[5]:
        st.subheader("Download JSON")
        buf = io.BytesIO(
            json.dumps(json_obj, indent=2 if pretty_download else None, ensure_ascii=False).encode("utf-8")
        )
        st.download_button("Download JSON", data=buf, file_name="data.json", mime="application/json")

if errors:
    st.error("Normalization/parse errors:\n\n" + "\n\n".join(errors))

with st.expander("ℹ️ Tips"):
    st.markdown(
        """
        - **Escaped string inputs** like `"{\\\"key\\\":\\\"232\\\"...}"` will be **double-decoded** automatically.
        - **Indexed lines** like `0: ""{...}""` will strip the index and decode the inner JSON.
        - **Multiple records** (one per line) are collected into an **array** automatically.
        - Use **Path Extract** with dotted keys and `[index]` for arrays.
        """
    )
