"""URL helpers for routing and AEBN scene detection."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, parse_qsl
from typing import Dict, Optional


def is_aebn_url(url: str) -> bool:
    """Accept the apex host 'aebn.com' and any subdomain (e.g., straight.aebn.com)."""
    try:
        host = urlparse(url).netloc.lower()
        return host == "aebn.com" or host.endswith(".aebn.com")
    except Exception:
        return False


def get_url_slug(url: str) -> str:
    """
    Heuristic slug:
      - Base = last path segment, *except* if '/scene/<n>' is present, then use
        the segment immediately BEFORE 'scene' as the base (e.g., 'bar' in '/bar/scene/4').
      - Prefer fragment-based scene (e.g., '#scene-4'); don't duplicate with path scene.
      - Append query params in original order as '-key-value'.
      - If no fragment scene, append path scene index as '-scene-<n>'.
    """
    p = urlparse(url)
    segs = [s for s in Path(p.path).parts if s]
    base = Path(p.path).name or "download"
    if "scene" in segs:
        i = segs.index("scene")
        if i - 1 >= 0:
            base = segs[i - 1]

    parts = [base]

    # fragment: scene-5 or scene=5 (takes precedence)
    frag = p.fragment or ""
    frag_scene = None
    m_frag = re.search(r"(?i)\bscene[-=]([A-Za-z0-9_]+)\b", frag)
    if m_frag:
        frag_scene = m_frag.group(1)
        parts.append(f"scene-{frag_scene}")

    # query: keep order
    if p.query:
        for k, v in parse_qsl(p.query, keep_blank_values=False):
            parts.append(k + (f"-{v}" if v else ""))

    # path '/scene/N' only if no fragment scene already used
    if frag_scene is None and "scene" in segs:
        i = segs.index("scene")
        if i + 1 < len(segs):
            parts.append(f"scene-{segs[i + 1]}")

    return "-".join(parts)


def parse_aebn_scene_controls(url: str) -> Dict[str, Optional[str]]:
    """
    Detect small numeric scene index (1..200) or a large ID.
    """
    p = urlparse(url)
    frag = p.fragment or ""
    q = parse_qs(p.query)
    scene_index: Optional[str] = None

    mfrag = re.search(r"(?i)\bscene[-=]?([0-9]+)\b", frag)
    if mfrag and 1 <= int(mfrag.group(1)) <= 200:
        scene_index = mfrag.group(1)
    if not scene_index:
        segs = [s for s in Path(p.path).parts if s]
        if "scene" in segs:
            i = segs.index("scene")
            if i + 1 < len(segs):
                cand = segs[i + 1]
                if cand.isdigit() and 1 <= int(cand) <= 200:
                    scene_index = cand

    scene_id = None
    for k in ("scene", "sceneId", "scene_id"):
        if k in q and q[k]:
            scene_id = q[k][0]
    if not scene_id:
        m2 = re.search(r"(?i)\bscene[-=]([A-Za-z0-9_]+)\b", frag)
        if m2:
            scene_id = m2.group(1)

    return {"scene_index": scene_index, "scene_id": scene_id}
