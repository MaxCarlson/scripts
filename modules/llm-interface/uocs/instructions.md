# UOCS v2 — Authoring Instructions (STRICT, copy/paste-ready)

These instructions tell an LLM **exactly how to format its output** so your applier can copy it from chat in **one code block** without any stray text.

---

## ✅ Output envelope (MUST)
- The **entire reply** must be a **single fenced code block** of the form:
  - starts with <code>```json</code>
  - ends with <code>```</code>
- **Nothing** before or after the fence (no prose, no headings, no extra backticks, no emojis, no explanations).
- The content inside the fence must be **valid JSON** and **UTF‑8**.
- Do **not** include comments inside JSON (JSON has no comments).

> If your output is not inside a single <code>```json</code> block, it will be rejected.

---

## ✅ Scope of content (ONLY changes)
- Include **only operations that change the repo**: additions, replacements, deletions, renames.
- **Do NOT output** the full contents of existing files that have **no changes**.
- For `"op":"edit"` entries:
  - Include **only** the `unit_ops` you are changing within that file.
  - Do **not** include the rest of the file text anywhere.
- For `"op":"new_file"`:
  - `content` **must** contain the **entire** new file (since it does not exist yet).
- For `"op":"rename_file"` and `"op":"delete_file"`:
  - Do **not** include any code bodies or content fields.

---

## ✅ Semantics of unit operations
- Use **unit-level** edits only: `function`, `method`, `class`.
- `replace` / `insert` **must** provide full, compilable `new.code` (including its header line).
- `delete` **must not** include the body of the thing being deleted.
- Prefer selectors: `kind` + `qualified` + `sig_old`. Add `old_hash` if known.
- If you provide an `anchor`, it is **authoritative** and must be ≤ 5 lines and match **exactly once**.

---

## ✅ JSON schema (recap)
Top-level:
```json
{
  "uocs_version": "2.0",
  "meta": { "id": "string", "author": "string", "created": "ISO-8601", "description": "string" },
  "files": [ /* file ops and edit ops */ ]
}
```

File operations (changes only):
```json
{ "op": "new_file", "path": "pkg/util.py", "language": "python", "content": "<entire file>" }
{ "op": "delete_file", "path": "old/legacy.py" }
{ "op": "rename_file", "from": "a.py", "to": "b.py" }
```

Edit block (per changed file):
```json
{ "op": "edit", "path": "app/mod.py", "language": "python",
  "unit_ops": [ /* UnitOp entries for this file only */ ] }
```

Unit operations:
```json
{ "op": "replace",
  "unit": { "kind": "function", "qualified": "app.mod.foo", "class": null,
            "sig_old": "def foo(a, b):", "old_hash": "sha256:<hex>" },
  "new":  { "sig": "def foo(a, b, c=0):",
            "code": "def foo(a, b, c=0):\n    return a+b+c\n" },
  "anchor": { "by": "text", "value": "def foo(a, b):", "max_lines": 5 }
}
{ "op": "insert",
  "unit": { "kind": "function", "qualified": "app.mod.run", "class": null },
  "where": { "insert": "after_symbol", "symbol": "app.mod.foo" },
  "new": { "sig": "def run():", "code": "def run():\n    return 0\n" }
}
{ "op": "delete",
  "unit": { "kind": "function", "qualified": "app.mod.dead", "class": null,
            "sig_old": "def dead():", "old_hash": null },
  "anchor": { "by": "text", "value": "def dead():", "max_lines": 5 }
}
```

---

## ✅ Compliance checklist the LLM must satisfy
1. My entire reply is one <code>```json</code> block with valid JSON.
2. No prose or text outside the fence.
3. Every file entry is one of: `new_file`, `delete_file`, `rename_file`, or `edit`.
4. I included `content` **only** for `new_file`.
5. Each `edit` has only the `unit_ops` for changed units in that file.
6. For `replace`/`insert`, `new.code` is full and compilable; for `delete`, no body is included.
7. Any `anchor` is ≤ 5 lines and is unique in the target file.

---

## ✅ Fully compliant example (copyable as-is)

```json
{
  "uocs_version": "2.0",
  "meta": { "id": "demo-OK-1", "description": "Update foo; add run; remove dead." },
  "files": [
    { "op": "edit", "path": "app/mod.py", "language": "python",
      "unit_ops": [
        { "op": "replace",
          "unit": { "kind": "function", "qualified": "app.mod.foo",
                    "class": null, "sig_old": "def foo(a, b):" },
          "new": { "sig": "def foo(a, b, c=0):",
                   "code": "def foo(a, b, c=0):\n    return a+b+c\n" } },
        { "op": "insert",
          "unit": { "kind": "function", "qualified": "app.mod.run", "class": null },
          "where": { "insert": "after_symbol", "symbol": "app.mod.foo" },
          "new": { "sig": "def run():", "code": "def run():\n    return 0\n" } },
        { "op": "delete",
          "unit": { "kind": "function", "qualified": "app.mod.dead",
                    "class": null, "sig_old": "def dead():" },
          "anchor": { "by": "text", "value": "def dead():", "max_lines": 5 } }
      ] },
    { "op": "rename_file", "from": "old/a.py", "to": "new/a.py" },
    { "op": "new_file", "path": "pkg/util.py", "language": "python",
      "content": "#!/usr/bin/env python3\n\ndef greet(n: str) -> str:\n    return f\"Hi, {n}\" \n" }
  ]
}
```

---

## ❌ Non‑compliant examples (forbidden patterns)

Bad: prose outside the fence
```
Here is your JSON:
```json
{ "uocs_version": "2.0", "files": [] }
```
```

Bad: unchanged file content dumped in JSON (don’t include this)
```json
{ "op": "edit", "path": "a.py", "language": "python", "unit_ops": [],
  "entire_file_text": "def a():\n    pass\n" }
```
