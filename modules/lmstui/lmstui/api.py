from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from lmstui.config import Config, normalize_root_base_url
from lmstui.http_client import HttpClient
from lmstui.sse import (
    extract_delta_text,
    iter_openai_stream_chunks,
)


@dataclass(frozen=True)
class ModelItem:
    id: str
    state: Optional[str] = None
    type: Optional[str] = None
    max_context_length: Optional[int] = None
    quantization: Optional[str] = None
    owned_by: Optional[str] = None


@dataclass(frozen=True)
class ChatStreamChunk:
    text: str
    reasoning: str = ""
    raw: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ChatResult:
    text: str
    raw: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, Any]] = None
    model_info: Optional[Dict[str, Any]] = None
    runtime: Optional[Dict[str, Any]] = None
    client_metrics: Optional[Dict[str, Any]] = None


class LMStudioAPI:
    def __init__(
        self,
        target: Any = "http://127.0.0.1:1234",
        timeout_seconds: float = 60.0,
        api_key: Optional[str] = None,
        verbose: bool = False,
    ) -> None:
        if target is None or target == "":
            self._root = "http://127.0.0.1:1234"
            self._timeout = float(timeout_seconds) if timeout_seconds is not None else 60.0
            self._api_key = api_key
            self._verbose = bool(verbose)
        elif isinstance(target, Config):
            self._root = target.base_url_root
            self._timeout = target.timeout_seconds
            self._api_key = None
            self._verbose = False
        elif hasattr(target, "base_url"):
            # ClientConfig compatible
            self._root = normalize_root_base_url(target.base_url)
            self._timeout = float(getattr(target, "timeout_seconds", timeout_seconds or 60.0))
            self._api_key = getattr(target, "api_key", api_key)
            self._verbose = bool(getattr(target, "verbose", verbose))
        else:
            self._root = normalize_root_base_url(str(target))
            self._timeout = float(timeout_seconds) if timeout_seconds is not None else 60.0
            self._api_key = api_key
            self._verbose = bool(verbose)

        self._http = HttpClient(
            timeout_seconds=self._timeout,
            api_key=self._api_key,
        )

    def close(self) -> None:
        pass

    @property
    def base_url_root(self) -> str:
        return self._root

    @property
    def rest_base(self) -> str:
        return f"{self._root}/api/v0"

    @property
    def openai_base(self) -> str:
        return f"{self._root}/v1"

    def ping(self) -> Tuple[str, str]:
        """
        Check connectivity, trying REST API v0 then OpenAI v1.
        """
        try:
            res = self._http.get_json(f"{self.rest_base}/models")
            if isinstance(res, dict):
                count = len(res.get("data", []))
                return "online", f"LM Studio REST v0 responding ({count} models available)"
        except Exception:
            pass

        try:
            res = self._http.get_json(f"{self.openai_base}/models")
            if isinstance(res, dict):
                count = len(res.get("data", []))
                return "online", f"LM Studio OpenAI v1 responding ({count} models available)"
        except Exception as e:
            return "offline", str(e)

        return "offline", "Server returned unexpected response"

    def list_models(self) -> Dict[str, Any]:
        """
        Retrieve models dictionary from REST API or OpenAI API.
        """
        try:
            data = self._http.get_json(f"{self.rest_base}/models")
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        data = self._http.get_json(f"{self.openai_base}/models")
        if not isinstance(data, dict):
            raise RuntimeError(f"Expected dict from /models, got: {type(data)}")
        return data

    def list_models_rest(self) -> List[ModelItem]:
        data = self._http.get_json(f"{self.rest_base}/models")
        if not isinstance(data, dict):
            return []
        items: List[ModelItem] = []
        for m in data.get("data", []):
            if isinstance(m, dict):
                items.append(
                    ModelItem(
                        id=m.get("id", ""),
                        state=m.get("state"),
                        type=m.get("type"),
                        max_context_length=m.get("max_context_length"),
                        quantization=m.get("quantization"),
                        owned_by=m.get("owned_by"),
                    )
                )
        return items

    def list_models_openai(self) -> List[ModelItem]:
        data = self._http.get_json(f"{self.openai_base}/models")
        if not isinstance(data, dict):
            return []
        items: List[ModelItem] = []
        for m in data.get("data", []):
            if isinstance(m, dict):
                items.append(
                    ModelItem(
                        id=m.get("id", ""),
                        owned_by=m.get("owned_by"),
                    )
                )
        return items

    def get_model_rest(self, model_id: str) -> Dict[str, Any]:
        return self.model_info(model_id)

    def model_info(self, model_id: str) -> Dict[str, Any]:
        try:
            data = self._http.get_json(f"{self.rest_base}/models/{model_id}")
            if isinstance(data, dict) and data.get("id"):
                return data
        except Exception:
            pass

        models = self.list_models()
        for item in models.get("data", []):
            if isinstance(item, dict) and item.get("id") == model_id:
                return item
        raise RuntimeError(f"Model not found: {model_id}")

    def resolve_model(
        self,
        explicit_model: Optional[str] = None,
    ) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
        """
        Resolve model to use:
        - If explicit_model provided: returns (explicit_model, None, info)
        - If omitted: auto-picks loaded model deterministically.
          Warns if multiple loaded models exist.
          Raises RuntimeError if 0 loaded models exist.
        """
        if explicit_model:
            try:
                info = self.model_info(explicit_model)
            except Exception:
                info = {"id": explicit_model}
            return explicit_model, None, info

        models_data = self.list_models()
        raw_items = [m for m in models_data.get("data", []) if isinstance(m, dict)]

        # Find loaded models
        loaded = [m for m in raw_items if m.get("state") == "loaded"]
        if not loaded and raw_items:
            # If server does not report state (e.g. OpenAI endpoint), treat all listed models as candidates
            loaded = raw_items

        if not loaded:
            raise RuntimeError(
                "No loaded model found in LM Studio. Please specify -m/--model or load a model in LM Studio."
            )

        # Deterministic sort by id
        loaded_sorted = sorted(loaded, key=lambda m: str(m.get("id", "")))
        selected = loaded_sorted[0]
        selected_id = str(selected.get("id", ""))

        warning: Optional[str] = None
        if len(loaded_sorted) > 1:
            other_ids = [repr(str(m.get("id", ""))) for m in loaded_sorted[1:]]
            warning = (
                f"Warning: Multiple models loaded. Using default model '{selected_id}'. "
                f"Other loaded models: {', '.join(other_ids)}."
            )

        return selected_id, warning, selected

    def chat_completions(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Union[Dict[str, Any], Iterator[Dict[str, Any]]]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        url = f"{self.openai_base}/chat/completions"

        if stream:
            lines = self._http.stream_lines("POST", url, json_body=payload)
            return iter_openai_stream_chunks(lines)

        res = self._http.post_json(url, json_body=payload)
        if not isinstance(res, dict):
            raise RuntimeError(f"Expected dict response from {url}, got: {type(res)}")
        return res

    def chat_rest(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = False,
    ) -> Union[Dict[str, Any], Iterator[str]]:
        """
        Backwards compatibility method for cli.py and repl.py.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens

        url = f"{self.rest_base}/chat/completions"
        try:
            if stream:
                return self._http.stream_lines("POST", url, json_body=payload)
            return self._http.post_json(url, json_body=payload)
        except Exception:
            # Fallback to OpenAI base
            url_v1 = f"{self.openai_base}/chat/completions"
            if stream:
                return self._http.stream_lines("POST", url_v1, json_body=payload)
            return self._http.post_json(url_v1, json_body=payload)

    def iter_stream_text_from_lines(self, lines: Iterator[str]) -> Iterator[str]:
        """
        Backwards compatibility helper: converts raw SSE lines into text chunks.
        """
        for chunk in iter_openai_stream_chunks(lines):
            delta = extract_delta_text(chunk)
            if delta:
                yield delta

    def responses(
        self,
        model: str,
        input_text: str,
        temperature: float = 0.7,
        max_output_tokens: Optional[int] = None,
        stream: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Union[Dict[str, Any], Iterator[Dict[str, Any]]]:
        payload: Dict[str, Any] = {
            "model": model,
            "input": input_text,
            "temperature": temperature,
            "stream": stream,
        }
        if max_output_tokens is not None and max_output_tokens > 0:
            payload["max_output_tokens"] = max_output_tokens
        if extra:
            payload.update(extra)

        url = f"{self.openai_base}/responses"
        if stream:
            lines = self._http.stream_lines("POST", url, json_body=payload)
            return iter_openai_stream_chunks(lines)

        res = self._http.post_json(url, json_body=payload)
        if not isinstance(res, dict):
            raise RuntimeError(f"Expected dict response from {url}, got: {type(res)}")
        return res

    def embeddings_rest(self, model: str, text: str) -> Dict[str, Any]:
        return self.embeddings(model=model, inputs=[text])

    def embeddings(self, model: str, inputs: List[str]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "input": inputs if len(inputs) > 1 else inputs[0],
        }
        try:
            return self._http.post_json(f"{self.rest_base}/embeddings", json_body=payload)
        except Exception:
            return self._http.post_json(f"{self.openai_base}/embeddings", json_body=payload)


# Compatibility aliases
LmStudioApi = LMStudioAPI
LMStudioClient = LMStudioAPI
