"""Small comment-preserving JSONC reader/editor for OpenCode runtime config."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


@dataclass
class Token:
    kind: str
    start: int
    end: int
    value: Any = None


@dataclass
class Property:
    key: str
    key_token: Token
    value: "Node"
    comma: Token | None = None


@dataclass
class Node:
    kind: str
    start: int
    end: int
    value: Any = None
    properties: dict[str, Property] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    close: Token | None = None


def _tokens(text: str) -> list[Token]:
    result: list[Token] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("Unterminated JSONC block comment.")
            index = end + 2
            continue
        if char == '"':
            start = index
            index += 1
            escaped = False
            while index < len(text):
                current = text[index]
                index += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    break
            else:
                raise ValueError("Unterminated JSONC string.")
            raw = text[start:index]
            result.append(Token("string", start, index, json.loads(raw)))
            continue
        if char in "{}[]:,":
            result.append(Token(char, index, index + 1, char))
            index += 1
            continue
        start = index
        while index < len(text) and not text[index].isspace() and text[index] not in "{}[]:,\"":
            if text.startswith("//", index) or text.startswith("/*", index):
                break
            index += 1
        if start == index:
            raise ValueError(f"Unexpected JSONC character at offset {index}.")
        raw = text[start:index]
        result.append(Token("primitive", start, index, json.loads(raw)))
    return result


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokens(text)
        self.index = 0

    def take(self, kind: str) -> Token:
        if self.index >= len(self.tokens) or self.tokens[self.index].kind != kind:
            raise ValueError(f"Invalid JSONC configuration; expected {kind}.")
        item = self.tokens[self.index]
        self.index += 1
        return item

    def parse(self) -> Node:
        value = self.value()
        if self.index != len(self.tokens):
            raise ValueError("Unexpected data after JSONC configuration.")
        return value

    def value(self) -> Node:
        if self.index >= len(self.tokens):
            raise ValueError("Unexpected end of JSONC configuration.")
        token = self.tokens[self.index]
        if token.kind == "{":
            return self.object()
        if token.kind == "[":
            return self.array()
        self.index += 1
        return Node("scalar", token.start, token.end, token.value)

    def object(self) -> Node:
        opening = self.take("{")
        node = Node("object", opening.start, opening.end)
        if self.index < len(self.tokens) and self.tokens[self.index].kind == "}":
            node.close = self.take("}")
            node.end = node.close.end
            return node
        while True:
            key = self.take("string")
            self.take(":")
            value = self.value()
            prop = Property(key.value, key, value)
            node.properties[key.value] = prop
            node.order.append(key.value)
            if self.index < len(self.tokens) and self.tokens[self.index].kind == ",":
                prop.comma = self.take(",")
                if self.index < len(self.tokens) and self.tokens[self.index].kind == "}":
                    node.close = self.take("}")
                    node.end = node.close.end
                    return node
                continue
            node.close = self.take("}")
            node.end = node.close.end
            return node

    def array(self) -> Node:
        opening = self.take("[")
        values = []
        if self.index < len(self.tokens) and self.tokens[self.index].kind == "]":
            close = self.take("]")
            return Node("array", opening.start, close.end, values, close=close)
        while True:
            values.append(self.value())
            if self.index < len(self.tokens) and self.tokens[self.index].kind == ",":
                self.take(",")
                if self.index < len(self.tokens) and self.tokens[self.index].kind == "]":
                    close = self.take("]")
                    return Node("array", opening.start, close.end, values, close=close)
                continue
            close = self.take("]")
            return Node("array", opening.start, close.end, values, close=close)


def _to_python(node: Node) -> Any:
    if node.kind == "scalar":
        return node.value
    if node.kind == "array":
        return [_to_python(item) for item in node.value]
    return {key: _to_python(node.properties[key].value) for key in node.order}


def loads(text: str) -> dict[str, Any]:
    root = _Parser(text or "{}").parse()
    if root.kind != "object":
        raise ValueError("JSONC configuration root must be an object.")
    return _to_python(root)


def _encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


class Document:
    """Apply leaf updates while leaving existing comments and layout in place."""

    def __init__(self, text: str):
        self.text = text or "{}"

    def _root(self) -> Node:
        return _Parser(self.text).parse()

    def _parent(self, root: Node, keys: list[str]) -> Node:
        current = root
        for key in keys:
            if current.kind != "object" or key not in current.properties:
                raise ValueError(f"JSONC object path is missing: {'.'.join(keys)}")
            current = current.properties[key].value
        if current.kind != "object":
            raise ValueError("JSONC target parent is not an object.")
        return current

    def set(self, keys: list[str], value: Any) -> None:
        if not keys:
            raise ValueError("JSONC root replacement is not supported.")
        root = self._root()
        parent = self._parent(root, keys[:-1])
        key = keys[-1]
        existing = parent.properties.get(key)
        if existing:
            self.text = (
                self.text[: existing.value.start]
                + _encoded(value)
                + self.text[existing.value.end :]
            )
            return

        close = parent.close
        if close is None:
            raise ValueError("JSONC object has no closing brace.")
        close_line = self.text.rfind("\n", 0, close.start) + 1
        close_prefix = self.text[close_line : close.start]
        multiline = not close_prefix.strip() and "\n" in self.text[parent.start : close.start]
        if parent.order:
            last = parent.properties[parent.order[-1]]
            if last.comma is None:
                self.text = self.text[: last.value.end] + "," + self.text[last.value.end :]
                root = self._root()
                parent = self._parent(root, keys[:-1])
                close = parent.close
                assert close is not None
                close_line = self.text.rfind("\n", 0, close.start) + 1
                close_prefix = self.text[close_line : close.start]
                multiline = not close_prefix.strip() and "\n" in self.text[parent.start : close.start]

        encoded = _encoded(value)
        if multiline:
            parent_line = self.text.rfind("\n", 0, parent.start) + 1
            parent_indent = self.text[parent_line : parent.start]
            if parent.order:
                first = parent.properties[parent.order[0]].key_token.start
                first_line = self.text.rfind("\n", 0, first) + 1
                child_indent = self.text[first_line:first]
            else:
                child_indent = parent_indent + "  "
            insert_at = close_line if not close_prefix.strip() else close.start
            addition = f"{child_indent}{json.dumps(key)}: {encoded}\n"
        else:
            insert_at = close.start
            addition = (" " if parent.order else "") + f"{json.dumps(key)}: {encoded}"
        self.text = self.text[:insert_at] + addition + self.text[insert_at:]

    def remove(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("JSONC root removal is not supported.")
        root = self._root()
        parent = self._parent(root, keys[:-1])
        key = keys[-1]
        if key not in parent.properties:
            return
        index = parent.order.index(key)
        prop = parent.properties[key]
        if prop.comma is not None:
            start, end = prop.key_token.start, prop.comma.end
        elif index:
            previous = parent.properties[parent.order[index - 1]]
            assert previous.comma is not None
            start, end = previous.comma.start, prop.value.end
        else:
            start, end = prop.key_token.start, prop.value.end
        self.text = self.text[:start] + self.text[end:]


def update(text: str, before: Any, after: Any) -> str:
    document = Document(text)

    def apply(old: Any, new: Any, path: list[str]) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in old.keys() - new.keys():
                document.remove(path + [key])
            for key, value in new.items():
                if key not in old:
                    document.set(path + [key], value)
                else:
                    apply(old[key], value, path + [key])
            return
        if old != new:
            document.set(path, new)

    apply(before, after, [])
    return document.text
