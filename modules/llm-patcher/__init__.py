"""
llm_patcher

A safe applier for LLM Edit Protocol v1 (LEP/v1).

Note:
- This project’s directory name includes a hyphen (`llm-patcher`), which prevents
  Python from importing it as package `llm_patcher`. During pytest collection,
  the root `__init__.py` may be imported as a plain module. Therefore we must
  avoid relative imports here.
"""

from applier import apply_from_text, extract_json_from_possible_fenced, parse_lep  # absolute imports

__all__ = [
    "apply_from_text",
    "extract_json_from_possible_fenced",
    "parse_lep",
]
