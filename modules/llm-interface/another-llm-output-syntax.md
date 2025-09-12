Awesome idea. Here’s a compact, robust spec you can hand to any LM so it emits a single, machine-parsable change script that updates functions/classes across many files—without dumping entire files.


---

Code Edit Script (CES) v1 — function/class–level changes

CES is a human-readable DSL (with a canonical JSON twin) for expressing repository edits at the unit level (functions, methods, classes). It’s designed to be:

Selector-robust: match by qualified name, signature, and an optional AST fingerprint.

Language-agnostic: fields exist for language and qualified_name.

Idempotent & safe: includes original signatures and optional fingerprints to avoid wrong targets.

Batchable: many files and units in one output.


Why this design: line diffs (unified/patch) are brittle across formatting; AST/unit-level changes align with modern refactoring/codemod approaches (LSP CodeActions, LibCST/jscodeshift, tree-sitter). 


---

1) DSL syntax (authoritative text form)

CES 1.0
[BEGIN CHANGESET]
meta: id=<uuid>; author=<string>; created=<ISO-8601>; description=<free text>

# ---------- file operations ----------
[NEW FILE] path=<rel/path.ext>; language=<lang>
<<<CONTENT
<entire file contents>
>>>CONTENT
[END FILE]

[DELETE FILE] path=<rel/path.ext>

[RENAME FILE] from=<old/rel/path.ext> to=<new/rel/path.ext>

[EDIT FILE] path=<rel/path.ext>; language=<lang>

  # ----- unit operations inside an EDIT FILE -----

  [INSERT FUNCTION]
  qualified_name=<module_or_class.func>; signature="<def …>"
  strategy=name|name+sig|fingerprint
  <<<BODY
  <full function definition including signature>
  >>>BODY
  [END INSERT]

  [REPLACE FUNCTION]
  qualified_name=<module_or_class.func>
  original_signature="<def …>"        # prior signature (as seen on disk)
  new_signature="<def …>"              # new signature (must match BODY)
  fingerprint=<sha256_of_normalized_ast_optional>
  strategy=name+sig|fingerprint|best-effort
  <<<BODY
  <full replacement function definition>
  >>>BODY
  [END REPLACE]

  [DELETE FUNCTION]
  qualified_name=<module_or_class.func>
  original_signature="<def …>"
  fingerprint=<sha256_optional>
  [END DELETE]

  [INSERT CLASS]
  qualified_name=<module.ClassName>
  strategy=name
  <<<BODY
  <full class definition>
  >>>BODY
  [END INSERT]

  [REPLACE CLASS]
  qualified_name=<module.ClassName>
  original_header="class ClassName(<bases>):"
  fingerprint=<sha256_optional>
  <<<BODY
  <full replacement class definition>
  >>>BODY
  [END REPLACE]

  [DELETE CLASS]
  qualified_name=<module.ClassName>
  original_header="class ClassName(<bases>):"
  fingerprint=<sha256_optional>
  [END DELETE]

  # ----- method ops (scoped to an existing class) -----
  [INSERT METHOD]
  class_qualified_name=<module.ClassName>
  method_name=<name>; signature="<def …>"
  strategy=name|name+sig
  <<<BODY
  <full method definition>
  >>>BODY
  [END INSERT]

  [REPLACE METHOD]
  class_qualified_name=<module.ClassName>
  method_name=<name>
  original_signature="<def …>"
  new_signature="<def …>"
  fingerprint=<sha256_optional>
  strategy=name+sig|fingerprint
  <<<BODY
  <full replacement method definition>
  >>>BODY
  [END REPLACE]

  [DELETE METHOD]
  class_qualified_name=<module.ClassName>
  method_name=<name>
  original_signature="<def …>"
  fingerprint=<sha256_optional>
  [END DELETE]

[END EDIT FILE]

[END CHANGESET]

Selector & safety rules

qualified_name must be fully qualified (e.g., package.module.func, package.module.Class.method). For languages without packages, use file-relative module.

strategy chooses matching priority. Recommended order: fingerprint (if given) → name+sig → name.

fingerprint: SHA-256 of a normalized AST for that unit (language-specific, e.g., LibCST or tree-sitter S-expr), excluding comments/whitespace; enables surgical, format-proof matches. 

When a selector fails, the applier must refuse that unit and report a precise error.



---

2) Canonical JSON (machine form)

Every CES DSL file must be convertible to the JSON form below (use this as your parser target):

{
  "ces_version": "1.0",
  "meta": {
    "id": "7e5f7e1b-9b3b-4a88-9d2a-1f4f7d6f2d77",
    "author": "LM",
    "created": "2025-09-12T19:45:00Z",
    "description": "Refactor foo(), add Project class, remove legacy bar()."
  },
  "operations": [
    { "op": "new_file", "path": "src/util/new_helpers.py", "language": "python",
      "content": "...\n" },
    { "op": "delete_file", "path": "old/legacy.txt" },
    { "op": "rename_file", "from": "a.py", "to": "b.py" },
    { "op": "edit_file", "path": "pkg/mod.py", "language": "python",
      "units": [
        { "op": "replace_function",
          "qualified_name": "pkg.mod.function2",
          "original_signature": "def function2(arg1, agr2):",
          "new_signature": "def function2(args):",
          "fingerprint": "sha256:…",
          "strategy": "name+sig",
          "body": "def function2(args):\n    ...\n    return True\n"
        },
        { "op": "insert_function",
          "qualified_name": "pkg.mod.function_new",
          "signature": "def function_new(args):",
          "strategy": "name",
          "body": "def function_new(args):\n    return ...\n"
        },
        { "op": "replace_method",
          "class_qualified_name": "pkg.mod.Project",
          "method_name": "save",
          "original_signature": "def save(self, path: str) -> None:",
          "new_signature": "def save(self, path: str, *, overwrite: bool=False) -> None:",
          "strategy": "name+sig",
          "body": "def save(self, path: str, *, overwrite: bool=False) -> None:\n    ...\n"
        }
      ]
    }
  ]
}

This mirrors LSP “textDocument/codeAction” intentions but operates at semantic units instead of raw ranges. 


---

3) Minimal EBNF (for the DSL)

CES           ::= "CES" WS VERSION NL "[BEGIN CHANGESET]" NL META OPS "[END CHANGESET]"
META          ::= "meta:" WS KVPAIR (";" WS KVPAIR)* NL
OPS           ::= (FILE_OP | EDIT_BLOCK)*
FILE_OP       ::= NEW_FILE | DELETE_FILE | RENAME_FILE
NEW_FILE      ::= "[NEW FILE]" WS "path=" PATH ";" WS "language=" LANG NL
                   "<<<CONTENT" NL ANY* NL ">>>CONTENT" NL "[END FILE]" NL
DELETE_FILE   ::= "[DELETE FILE]" WS "path=" PATH NL
RENAME_FILE   ::= "[RENAME FILE]" WS "from=" PATH WS "to=" PATH NL
EDIT_BLOCK    ::= "[EDIT FILE]" WS "path=" PATH ";" WS "language=" LANG NL UNIT_OPS "[END EDIT FILE]" NL
UNIT_OPS      ::= (INSERT_FN | REPLACE_FN | DELETE_FN | INSERT_CLASS | REPLACE_CLASS | DELETE_CLASS | INSERT_METHOD | REPLACE_METHOD | DELETE_METHOD)*
# (Unit statements follow the shapes shown in section 1)


---

4) Example (matching your idea)

CES 1.0
[BEGIN CHANGESET]
meta: id=5b2d1d2f-3a1e-4f3f-a7ef-1122aa33bb44; author=Max; created=2025-09-12T19:45:00Z; description=Retool project open/print flows

[EDIT FILE] path=scripts/km/cli.py; language=python

  [REPLACE FUNCTION]
  qualified_name=scripts.km.cli.create_local_project
  original_signature="def create_local_project(name: str, *, open_after: bool=True) -> int:"
  new_signature="def create_local_project(name: str, *, open_after: bool=True, ext: str = \".kproj\") -> int:"
  strategy=name+sig
  <<<BODY
  def create_local_project(name: str, *, open_after: bool=True, ext: str = ".kproj") -> int:
      # new implementation...
      return 0
  >>>BODY
  [END REPLACE]

  [INSERT FUNCTION]
  qualified_name=scripts.km.cli.print_project
  signature="def print_project(name: str, *, all: bool=False) -> int:"
  strategy=name
  <<<BODY
  def print_project(name: str, *, all: bool=False) -> int:
      # prints titles with indentation; mirrors UI list
      return 0
  >>>BODY
  [END INSERT]

[END EDIT FILE]

[NEW FILE] path=scripts/km/project_link.py; language=python
<<<CONTENT
# module to resolve .kproj links to DB pages
>>>CONTENT
[END FILE]

[DELETE FILE] path=scripts/km/old_print.py

[END CHANGESET]


---

5) Applier behavior (how your script should execute CES)

1. Parse DSL → build JSON model.


2. For each operation:

new_file: fail if path exists (unless overwrite=true future flag).

delete_file: verify path exists; delete.

rename_file: verify from exists, to absent; move.

edit_file: load source; for each unit op:

Locate target via strategy:

1. fingerprint (if provided): compute normalized AST (tree-sitter/libcst or language-native), match hash.


2. name+sig: match fully qualified name + exact signature text.


3. name: last resort.



Apply replacement/insert/delete at AST level, then pretty-print back to source.




3. After all edits, format + import-fix (language toolchain).


4. Emit a report for each unit: applied | skipped | failed (reason).



References for underlying techniques: unified diffs (why we avoided line fragility), LSP CodeActions (edit intents), codemods (LibCST/jscodeshift), incremental parsing (tree-sitter). 


---

6) Authoring rules for LMs (paste these straight into a system prompt)

Output exactly one CES changeset. No prose outside the block.

Always include: fully-qualified names, original and new signatures (for replacements), and the full body of any inserted/replaced unit.

Never mix partial bodies or ellipses inside bodies—bodies must be compilable.

Prefer strategy=name+sig; add a fingerprint when you can (normalized AST of the original).

If you rename a file or class, emit the matching RENAME FILE/REPLACE CLASS and fix all references in separate unit edits.

Group all edits for the same file inside one [EDIT FILE] block.

If you must touch both a class and its methods, prefer a method-level change unless the whole class needs replacement.

Keep language accurate (e.g., python, cpp, go, java).

If any target cannot be found with your selector, the applier will skip it—so be precise.



---

7) Optional extensions (reserved fields)

guards: (e.g., require Python ≥3.12 or Go module path match).

post_run: lint/format commands to run per language (e.g., ruff --fix, gofmt, clang-format).

conflicts: declare mutually exclusive ops to help the applier resolve order.



---

If you want, I can also deliver a reference applier (Python) using LibCST for Python and tree-sitter for other languages, plus pytest coverage and a JSON⇄DSL converter.
