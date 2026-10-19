from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_FILEPATH = Path(__file__).resolve().parent / "defaults.json"


def parse_default_val(val_str: str) -> Any:
    """
    Parse a string value into boolean, int, float, json, or raw string.
    """
    v = val_str.strip()
    v_lower = v.lower()
    if v_lower in ("true", "1", "yes", "on"):
        return True
    if v_lower in ("false", "0", "no", "off"):
        return False
    if v_lower in ("none", "null"):
        return None

    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        pass

    try:
        return json.loads(v)
    except Exception:
        pass

    return v


def load_defaults(filepath: Optional[Path] = None) -> Dict[str, Any]:
    path = filepath or DEFAULT_FILEPATH
    if not path.exists():
        return {"global": {}, "models": {}}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("global", {})
                data.setdefault("models", {})
                return data
    except Exception:
        pass

    return {"global": {}, "models": {}}


def save_defaults(data: Dict[str, Any], filepath: Optional[Path] = None) -> None:
    path = filepath or DEFAULT_FILEPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_effective_defaults(
    model: Optional[str] = None,
    filepath: Optional[Path] = None,
) -> Dict[str, Any]:
    data = load_defaults(filepath)
    effective: Dict[str, Any] = dict(data.get("global", {}))
    if model:
        models = data.get("models", {})
        if isinstance(models, dict) and model in models:
            effective.update(models[model])
    return effective


def set_default(
    key: str,
    value: Any,
    model: Optional[str] = None,
    filepath: Optional[Path] = None,
) -> None:
    data = load_defaults(filepath)
    if model:
        models = data.setdefault("models", {})
        m_dict = models.setdefault(model, {})
        m_dict[key] = value
    else:
        g_dict = data.setdefault("global", {})
        g_dict[key] = value
    save_defaults(data, filepath)


def clear_defaults(
    model: Optional[str] = None,
    filepath: Optional[Path] = None,
) -> None:
    data = load_defaults(filepath)
    if model:
        models = data.get("models", {})
        if isinstance(models, dict) and model in models:
            del models[model]
    else:
        data["global"] = {}
        data["models"] = {}
    save_defaults(data, filepath)
