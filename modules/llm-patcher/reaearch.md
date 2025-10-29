A System for Robust, LLM-Driven Multi-File Code Patching
Deconstruction of an Advanced Agentic Patching System: The codex-cli Protocol
An analysis of existing AI-driven code patching systems is essential for designing a new, robust protocol. The codex-cli repository, a sophisticated developer tool, contains an advanced agentic patching system centered around a custom tool named apply_patch. By examining its architecture, syntax, parsing logic, and the instructions provided to the Large Language Model (LLM), it is possible to derive a set of foundational principles and identify critical design patterns necessary for a safe and effective system.
The apply_patch Tool: Architecture and Invocation
The design of the apply_patch tool within the codex-cli ecosystem reveals a deliberate architectural choice to treat code modification as a specialized, first-class capability rather than a generic shell operation. This is evident in its implementation as a dedicated Rust crate, codex-rs/apply-patch/, which provides a modular and self-contained unit of functionality. The crate's structure, with distinct main.rs and lib.rs files, indicates a dual role: it can function as a standalone command-line binary and as a library that can be integrated directly into other parts of the system. This modularity is a key architectural strength, allowing the patching logic to be tested, maintained, and invoked independently of the main agent loop.
The core invocation flow demonstrates a sophisticated interception mechanism that prioritizes safety and verification. When the agent's LLM generates a command, it does not execute it blindly. Instead, the handle_container_exec_with_params function within codex-rs/core/src/tools/mod.rs serves as a central dispatch point. This function calls maybe_parse_apply_patch_verified, a critical pre-processing step that attempts to detect if a given command is, in fact, an apply_patch invocation. If it is, the system intercepts the command, parses its custom patch format, and routes it through a dedicated internal engine instead of a standard shell. This design pattern is fundamental to the system's safety model; it prevents the agent from performing arbitrary file modifications via generic shell commands like sed or echo > file.txt when a structured patch is intended, thereby reducing the risk of unintended side effects.
Furthermore, the protocol is built around an explicit safety and approval mechanism. File system modifications are categorized as high-risk operations that necessitate either a pre-configured policy decision or direct user consent. The system defines protocol events such as ApplyPatchApprovalRequestEvent, which are handled by components like codex-rs/mcp-server/src/codex_tool_runner.rs and codex-rs/core/src/apply_patch.rs. When the agent proposes a patch that falls outside the current sandbox policy, the system pauses execution and sends a request to the client, presenting the proposed changes for user review. The user can then approve or deny the patch. This approval gate is a non-negotiable feature for any trustworthy AI developer tool, ensuring that the user remains in ultimate control of their codebase. This principle of explicit, verifiable consent for file system modifications must be a cornerstone of any newly designed patching system.
The Custom Patch Syntax: A Format for LLM Generation
The codex-cli system employs a custom patch syntax specifically engineered for generation by an LLM. An analysis of the test cases within codex-rs/apply-patch/src/lib.rs provides a clear specification of this format, which is designed to be both expressive for the agent and relatively straightforward for the machine to parse.
The syntactic structure is defined by clear delimiters and headers. The entire patch payload is encapsulated within *** Begin Patch and *** End Patch markers, providing an unambiguous boundary for the parser. Within this envelope, file-level operations are declared using explicit headers:
 * *** Add File: <path>: Signals the creation of a new file.
 * *** Delete File: <path>: Signals the deletion of an existing file.
 * *** Update File: <path>: Signals the modification of an existing file.
This header-based approach eliminates ambiguity about the intended operation for each file. The system also supports atomic file renaming combined with an update. An Update File header can be immediately followed by an optional *** Move to: <new_path> header, instructing the patch engine to apply the changes and rename the file in a single, cohesive operation.
For Update File operations, changes are organized into "hunks," each introduced by an @@ marker. This is conceptually similar to the unified diff format. Lines within a hunk are prefixed with one of three characters: + for an added line, - for a deleted line, and a single space for a context line, which must match an existing line in the file. The inclusion of context lines is crucial for reliably locating the precise position within the file where the patch should be applied.
A notable feature of this syntax is its flexible context specification. The @@ hunk marker can be optionally followed by descriptive text, such as a class or function name (e.g., @@ class BaseClass). This semantic context is used by the seek_sequence logic, implemented in codex-rs/apply-patch/src/seek_sequence.rs, to enhance the reliability of locating the patch site. This is a powerful affordance for an LLM, which can reason about code structure and provide semantic anchors that are more resilient to minor file changes than simple line-based context alone. Additionally, the syntax includes a special marker, *** End of File, to unambiguously signal an addition at the very end of a file, as demonstrated in the test_unified_diff_insert_at_eof test case. This handles a common edge case where trailing newlines can create ambiguity.
The Parser: Balancing Formality and Leniency
The parsing strategy of the codex-cli system embodies a crucial design principle for interacting with LLMs: the duality of formalism and leniency. On one hand, the system provides a formal grammar to guide the LLM's output. The presence of a file named codex-rs/core/src/tools/handlers/tool_apply_patch.lark strongly suggests the use of the Lark parsing toolkit to define a strict, unambiguous grammar for the apply_patch tool's invocation. This grammar serves as part of the "API contract" with the LLM, defining the ideal structure of a valid patch.
On the other hand, the system's developers recognized that LLM outputs, while often structurally correct, can contain minor, non-substantive deviations from a strict format. To accommodate this, the Rust-based parser in codex-rs/apply-patch/src/parser.rs implements a ParseMode::Lenient. This mode explicitly instructs the parser to be tolerant of common LLM-generated imperfections, such as extra whitespace around markers or inconsistent casing. This robustness is a critical feature of a production-grade system; a parser that fails on minor syntactic noise would be brittle and lead to frequent, frustrating failures for the end-user.
The parser's leniency extends to handling different invocation styles. The check_patch_boundaries_lenient function within parser.rs is specifically designed to detect and strip shell heredoc markers (e.g., <<'EOF'). This indicates that the system is robust to the various ways an LLM might choose to construct a shell command to deliver the patch payload. The LLM might pass the patch as a direct string argument or embed it within a heredoc; the parser is designed to handle both cases gracefully. This pragmatic approach—defining a formal target while accepting near-misses—is a key takeaway for designing any system that consumes structured data from an LLM.
LLM Instructions: Guiding the Generator
The codex-cli system treats the LLM's prompt not as a mere suggestion but as a core part of the system's API contract. The repository contains extensive instruction files, such as prompt.md and gpt_5_codex_prompt.md, which provide detailed documentation for the LLM on how, when, and why to use the apply_patch tool. This practice of embedding detailed tool documentation directly into the system prompt is fundamental to achieving reliable and predictable behavior from the model.
These instructions go beyond simple syntax definitions; they establish a set of behavioral rules and guardrails. For instance, the prompts contain explicit negative constraints, such as instructions on when not to use apply_patch (e.g., for running code formatters like gofmt, where a simple shell command is more appropriate) and critical safety rules like "NEVER revert existing changes you did not make". These rules are essential for constraining the LLM's powerful but sometimes unpredictable reasoning, guiding it toward safe and effective actions. The level of detail in these prompts demonstrates that successful integration of LLM-driven tools requires a co-design of the tool's software implementation and the natural language instructions that govern its use. The prompt itself must be treated as a primary software artifact—versioned, tested, and maintained alongside the code that executes the tool's logic.
The LLM-Native Patch Syntax (LLMPS v1): A Protocol for Robust Code Modification
Drawing upon the analysis of the codex-cli system, this section specifies a new custom patch syntax, designated the LLM-Native Patch Syntax v1 (LLMPS). This protocol is engineered from the ground up to meet the specific needs of an LLM-driven code modification workflow. The primary design goals are to maximize clarity and eliminate ambiguity for the parsing engine, while maintaining a structure that is simple and intuitive for a Large Language Model to generate reliably.
Design Principles
The development of LLMPS v1 is guided by four core principles:
 * Explicitness over Implicitness: Every component of the patch, from file operations to content blocks, is marked with clear, keyword-based headers. This design avoids reliance on positional context or subtle syntactic cues, thereby minimizing the potential for parsing ambiguity.
 * Stream-Friendly Parsing: The format is designed to be processed line-by-line using a simple state machine. This allows a parser to handle very large patches efficiently without needing to load the entire content into memory, making the system scalable and responsive.
 * Human Readability: While the primary consumer of this format is a machine, the syntax is designed to be reasonably intuitive for a human developer to read and debug. This is crucial for troubleshooting, manual patch creation, and building user trust in the system.
 * YAML-inspired Block Structure: The syntax uses indentation to denote blocks of code within a hunk (e.g., lines to be added or removed). This is a familiar pattern in languages like Python and is a structure that LLMs are adept at generating, aligning the format with both the implementation language and the generating model's natural tendencies.
Formal Specification of LLMPS v1
The LLMPS v1 protocol is defined by the following structural rules:
 * Root Structure: An entire patch is represented as a single block of text. Individual file operations within the patch are separated by a distinct delimiter line containing only three hyphens (---). This allows for the unambiguous composition of multi-file changes into a single document.
 * File Operation Block: Each section of the patch begins with a file operation header. The header consists of a keyword, a colon, and the relevant file path(s). The supported headers are:
   * CREATE-FILE: path/to/new_file.ext: Specifies the creation of a new file at the given path.
   * DELETE-FILE: path/to/old_file.ext: Specifies the deletion of an existing file at the given path.
   * UPDATE-FILE: path/to/existing_file.ext: Specifies the modification of an existing file.
   * RENAME-FILE: path/to/source.ext TO path/to/destination.ext: Specifies the renaming of a file. This is a standalone operation and cannot be combined with content modifications in the same block.
 * Content Blocks for CREATE-FILE: For a CREATE-FILE operation, the header is immediately followed by a CONTENT: marker on a new line. All subsequent lines that are indented relative to the CONTENT: marker are treated as the literal content of the new file.
 * Hunk Blocks for UPDATE-FILE: An UPDATE-FILE block must contain one or more HUNK: blocks. Each HUNK: block is an indented section that defines a single, contiguous change within the file. A hunk is composed of the following mandatory and optional sub-blocks:
   * BEFORE:: A mandatory, indented block containing one or more lines of code. These lines serve as the primary context and must exist in the target file exactly as specified, immediately preceding the location of the change.
   * REMOVE:: An optional, indented block containing the lines of code to be removed from the file.
   * ADD:: An optional, indented block containing the lines of code to be added to the file. The lines from the ADD block will replace the lines from the REMOVE block.
   * AFTER:: An optional, indented block containing one or more lines of code that must appear immediately after the change. This provides additional context for more precise anchoring of the patch.
At least one of REMOVE or ADD must be present in a hunk. All content within BEFORE, REMOVE, ADD, and AFTER blocks must maintain its original indentation relative to the start of the line.
Example LLMPS v1 Patch
The following example demonstrates a multi-file patch that modifies one Python file and creates another, adhering to the LLMPS v1 specification.
UPDATE-FILE: src/main.py
  HUNK:
    BEFORE:
      def main():
        print("Hello, old world!")
    REMOVE:
      print("Hello, old world!")
    ADD:
      # A new greeting
      print("Hello, new world!")
---
CREATE-FILE: src/utils.py
  CONTENT:
    def helper_function():
      """This is a new helper."""
      return True
---
DELETE-FILE: docs/old_notes.txt
---
RENAME-FILE: app/config.yml TO app/settings.yml

This patch instructs the application engine to perform four distinct operations: first, update src/main.py by replacing a print statement; second, create a new file src/utils.py with specified content; third, delete docs/old_notes.txt; and fourth, rename app/config.yml.
Comparative Analysis
The design of LLMPS v1 is a deliberate trade-off between several competing concerns. The following table compares it against the standard Unified Diff Format (as used by git diff) and the custom format observed in the codex-cli tool.
| Feature | git diff (Unified Format) | codex-cli Format | LLMPS v1 (Proposed) |
|---|---|---|---|
| LLM Generatability | Moderate. Format is strict and includes line numbers and metadata (--- a/, +++ b/) that can be challenging for LLMs to generate correctly and consistently. | High. Designed for LLMs with clear, keyword-based headers (*** Add File:). Lacks rigid structural requirements like indentation, which can lead to minor LLM errors. | Very High. Uses natural language keywords and an indentation-based structure that aligns well with how LLMs process and generate code, reducing the likelihood of syntactic errors. |
| Parsing Complexity | High. Requires a complex state machine to parse hunk headers (@@ -l,s +l,s @@), context, additions, and deletions. | Moderate. The parser must be lenient to handle LLM variations in whitespace and casing around *** markers. Ambiguity is possible if markers are malformed. | Low. The use of strict keywords, indentation for blocks, and a --- separator allows for a simple, highly deterministic line-by-line state machine parser. |
| Ambiguity | Low. The format is highly specified, though parsing edge cases (e.g., no newline at end of file) can be tricky. | Moderate. Leniency in parsing can introduce ambiguity. For example, a malformed @@ line could be misinterpreted as content. | Very Low. Keywords like BEFORE:, ADD:, and CONTENT: are unambiguous. Indentation clearly delineates code blocks, preventing content from being mistaken for syntax. |
| Context Specificity | Low. Context is purely line-based and relative to the change. It provides no semantic information. | High. Supports optional semantic context in the @@ header (e.g., function name), which helps anchor patches more robustly. | High. The mandatory BEFORE: block and optional AFTER: block provide explicit, multi-line context anchors that are both easy to parse and generate. |
| Multi-File Support | Native. A single diff can contain changes for multiple files, each with its own diff --git header. | Native. Multiple ***... File: blocks can be included between the main Begin/End Patch delimiters. | Native. File operations are explicitly separated by the --- delimiter, making multi-file patches a core feature of the syntax. |
| Human Readability | High. It is the industry standard and instantly recognizable to developers. | Moderate to High. The keyword-based headers are clear, but the intermingling of +, -, and context lines can be dense. | High. The block-based structure with explicit BEFORE, REMOVE, and ADD keywords makes the intent of each hunk exceptionally clear at a glance. |
This comparison demonstrates that LLMPS v1 occupies a favorable position in the design space. It prioritizes low parsing complexity and low ambiguity, which are critical for building a reliable automated system, while retaining the high generatability and context specificity that make the codex-cli format effective for LLM agents.
Prompt Engineering for Reliable Patch Generation
To ensure a Large Language Model can reliably and accurately generate patches in the LLMPS v1 format, a carefully engineered system prompt is required. This prompt serves as the primary API, defining the model's task, constraints, and expected output format. It combines a clear persona, a structured thought process, a formal syntax definition, and a rich set of examples to guide the model's behavior.
The Core System Prompt
The system prompt is the foundation of the interaction and must be comprehensive. It is structured to provide the LLM with all necessary context and instructions in a single message.
 * Persona and Goal: The prompt begins by establishing the LLM's role and objective. This frames the task and sets the tone for the interaction.
   > You are an expert software engineer and a master of code refactoring. Your primary task is to understand user requests for code changes and translate them into a precise, machine-readable patch using the LLM-Native Patch Syntax (LLMPS) format. You must generate a complete patch that accomplishes the user's goal.
   > 
 * Chain-of-Thought Instruction: To encourage more robust and accurate outputs, the prompt explicitly instructs the model to follow a step-by-step reasoning process before generating the final patch. This makes the model's intermediate thinking process more transparent and often leads to better results.
   > Before generating the patch, you must think step-by-step. First, identify all the files that need to be created, deleted, renamed, or modified to fulfill the user's request. For each modification, determine the exact lines of code that must be changed. Critically, you must identify a stable and unique block of context lines that appear immediately before the change to use in the BEFORE block. Once you have a clear and complete plan, generate the entire patch in a single code block.
   > 
 * Formal Syntax Definition: The prompt must contain the complete and unambiguous specification for LLMPS v1. This ensures the model has a direct reference for the required format, minimizing the chance of hallucinating or deviating from the syntax. This technique is directly inspired by the codex-cli system, which embeds tool documentation within its prompts.
   > LLM-Native Patch Syntax (LLMPS) v1 Specification
   > You must generate a patch that strictly adheres to the following format:
   >  * File Operations: Each file operation is a separate block. Blocks are separated by a line containing only ---.
   >  * Headers: Each block must start with one of the following headers:
   >    * CREATE-FILE: path/to/file.ext
   >    * DELETE-FILE: path/to/file.ext
   >    * UPDATE-FILE: path/to/file.ext
   >    * RENAME-FILE: path/to/source.ext TO path/to/destination.ext
   >  * Content for CREATE-FILE:
   >    * The header is followed by a CONTENT: line.
   >    * All subsequent lines must be indented to indicate they are the content of the new file.
   >  * Hunks for UPDATE-FILE:
   >    * An UPDATE-FILE block contains one or more HUNK: blocks.
   >    * Each HUNK: is indented and contains the following sub-blocks:
   >      * BEFORE: (mandatory): An indented block of context lines that appear immediately before the change.
   >      * REMOVE: (optional): An indented block of lines to be removed.
   >      * ADD: (optional): An indented block of lines to be added.
   >      * AFTER: (optional): An indented block of context lines that appear immediately after the change.
   >    * At least one REMOVE or ADD block must be present in each hunk.
   > 
 * Rules and Guardrails: To further constrain the model's output and enforce best practices, a set of explicit rules is provided.
   > Rules and Constraints
   >  * Context is Key: Always provide at least three lines of context in the BEFORE block. This is crucial for accurately locating the change.
   >  * No Line Numbers: Do not include line numbers in the patch. The patch must be applied based on text context only.
   >  * Indentation is Significant: Preserve the exact original indentation of all lines within the BEFORE, REMOVE, ADD, and AFTER blocks.
   >  * Completeness: Ensure the patch is complete and addresses the user's entire request. If multiple files are affected, include a block for each one, separated by ---.
   > 
In-Context Examples (Few-Shot Learning)
To solidify the model's understanding of the LLMPS v1 format, the prompt includes several complete examples. These few-shot examples demonstrate the correct application of the syntax across a variety of common scenarios, providing concrete patterns for the model to follow.
 * Example 1: Single-file, single-hunk update.
   > User Request: "In main.py, change the greeting from 'Hello' to 'Greetings'."
   > UPDATE-FILE: main.py
   >   HUNK:
   >     BEFORE:
   >       def greet():
   >         # Print a greeting
   >         message = "Hello, World!"
   >     REMOVE:
   >       message = "Hello, World!"
   >     ADD:
   >       message = "Greetings, World!"
   >     AFTER:
   >       print(message)
   > 
   > 
 * Example 2: Multi-hunk update in a single file.
   > User Request: "In config.py, set DEBUG to False and change the PORT from 8000 to 8080."
   > UPDATE-FILE: config.py
   >   HUNK:
   >     BEFORE:
   >       # Application settings
   >       # Turn off debug mode for production
   >       DEBUG = True
   >     REMOVE:
   >       DEBUG = True
   >     ADD:
   >       DEBUG = False
   >   HUNK:
   >     BEFORE:
   >       # Network configuration
   >       HOST = "0.0.0.0"
   >       PORT = 8000
   >     REMOVE:
   >       PORT = 8000
   >     ADD:
   >       PORT = 8080
   > 
   > 
 * Example 3: Multi-file refactoring (move a function).
   > User Request: "Move the calculate_sum function from main.py to a new file called utils.py and import it back into main.py."
   > UPDATE-FILE: main.py
   >   HUNK:
   >     BEFORE:
   >       import os
   >     ADD:
   >       from utils import calculate_sum
   >   HUNK:
   >     BEFORE:
   >       # End of imports
   > 
   >       def calculate_sum(a, b):
   >         return a + b
   > 
   >       def main():
   >     REMOVE:
   >       def calculate_sum(a, b):
   >         return a + b
   > ---
   > CREATE-FILE: utils.py
   >   CONTENT:
   >     def calculate_sum(a, b):
   >       """Calculates the sum of two numbers."""
   >       return a + b
   > 
   > 
 * Example 4: File deletion.
   > User Request: "Please delete the temporary file scratch.txt."
   > DELETE-FILE: scratch.txt
   > 
   > 
The Complete Prompt
This subsection consolidates all the above elements into the final, complete system prompt, ready for use.
You are an expert software engineer and a master of code refactoring. Your primary task is to understand user requests for code changes and translate them into a precise, machine-readable patch using the LLM-Native Patch Syntax (LLMPS) format. You must generate a complete patch that accomplishes the user's goal.
Before generating the patch, you must think step-by-step. First, identify all the files that need to be created, deleted, renamed, or modified to fulfill the user's request. For each modification, determine the exact lines of code that must be changed. Critically, you must identify a stable and unique block of context lines that appear immediately before the change to use in the BEFORE block. Once you have a clear and complete plan, generate the entire patch in a single code block.
LLM-Native Patch Syntax (LLMPS) v1 Specification
You must generate a patch that strictly adheres to the following format:
 * File Operations: Each file operation is a separate block. Blocks are separated by a line containing only ---.
 * Headers: Each block must start with one of the following headers:
   * CREATE-FILE: path/to/file.ext
   * DELETE-FILE: path/to/file.ext
   * UPDATE-FILE: path/to/file.ext
   * RENAME-FILE: path/to/source.ext TO path/to/destination.ext
 * Content for CREATE-FILE:
   * The header is followed by a CONTENT: line.
   * All subsequent lines must be indented to indicate they are the content of the new file.
 * Hunks for UPDATE-FILE:
   * An UPDATE-FILE block contains one or more HUNK: blocks.
   * Each HUNK: is indented and contains the following sub-blocks:
     * BEFORE: (mandatory): An indented block of context lines that appear immediately before the change.
     * REMOVE: (optional): An indented block of lines to be removed.
     * ADD: (optional): An indented block of lines to be added.
     * AFTER: (optional): An indented block of context lines that appear immediately after the change.
   * At least one REMOVE or ADD block must be present in each hunk.
Rules and Constraints
 * Context is Key: Always provide at least three lines of context in the BEFORE block. This is crucial for accurately locating the change.
 * No Line Numbers: Do not include line numbers in the patch. The patch must be applied based on text context only.
 * Indentation is Significant: Preserve the exact original indentation of all lines within the BEFORE, REMOVE, ADD, and AFTER blocks.
 * Completeness: Ensure the patch is complete and addresses the user's entire request. If multiple files are affected, include a block for each one, separated by ---.
Examples
Example 1: Single-file, single-hunk update.
User Request: "In main.py, change the greeting from 'Hello' to 'Greetings'."llmps
UPDATE-FILE: main.py
HUNK:
BEFORE:
def greet():
# Print a greeting
message = "Hello, World!"
REMOVE:
message = "Hello, World!"
ADD:
message = "Greetings, World!"
AFTER:
print(message)

**Example 2: Multi-hunk update in a single file.**
**User Request:** "In `config.py`, set `DEBUG` to `False` and change the `PORT` from 8000 to 8080."

```llmps
UPDATE-FILE: config.py
  HUNK:
    BEFORE:
      # Application settings
      # Turn off debug mode for production
      DEBUG = True
    REMOVE:
      DEBUG = True
    ADD:
      DEBUG = False
  HUNK:
    BEFORE:
      # Network configuration
      HOST = "0.0.0.0"
      PORT = 8000
    REMOVE:
      PORT = 8000
    ADD:
      PORT = 8080

Example 3: Multi-file refactoring (move a function).
User Request: "Move the calculate_sum function from main.py to a new file called utils.py and import it back into main.py."
UPDATE-FILE: main.py
  HUNK:
    BEFORE:
      import os
    ADD:
      from utils import calculate_sum
  HUNK:
    BEFORE:
      # End of imports

      def calculate_sum(a, b):
        return a + b

      def main():
    REMOVE:
      def calculate_sum(a, b):
        return a + b
---
CREATE-FILE: utils.py
  CONTENT:
    def calculate_sum(a, b):
      """Calculates the sum of two numbers."""
      return a + b

Example 4: File deletion.
User Request: "Please delete the temporary file scratch.txt."
DELETE-FILE: scratch.txt


## The `llm-patcher` Utility: A Python Implementation

This section provides the complete design and source code for `llm-patcher`, a command-line utility that materializes the principles and specifications outlined previously. This tool is designed to be a robust, safe, and user-friendly mechanism for applying LLM-generated patches from the system clipboard to a local filesystem.

### Core Architecture and Dependencies

The `llm-patcher` tool is implemented as a single-file Python script to ensure ease of distribution and use. It is designed with minimal external dependencies to simplify installation. The primary dependency is `pyperclip`, a cross-platform clipboard utility, which will be used as a fallback within a more comprehensive, custom-built clipboard access function inspired by the robust logic found in the `cross_platform` module. The architecture is function-driven, with clear separation of concerns for clipboard access, parsing, patch verification, and atomic file application.

### Clipboard Integration: The Entry Point

The tool's workflow begins by fetching the patch content from the system clipboard. A naive clipboard implementation is often platform-specific and brittle. The `cross_platform` module provides a superior strategy by checking for various environments and using a chain of fallbacks. This logic will be replicated in Python to create a highly reliable `get_clipboard_text()` function.

The function will sequentially check for different operating environments and use the appropriate tool:
1.  **WSL (Windows Subsystem for Linux):** It will first attempt to use `win32yank.exe -o`, which is the most reliable way to access the Windows host clipboard from within WSL. If that fails, it will fall back to `clip.exe`.
2.  **macOS:** It will execute the `pbpaste` command.
3.  **Linux (X11/Wayland):** It will try `wl-paste` first for Wayland environments, then fall back to `xclip -selection clipboard -o` and `xsel --clipboard --output` for X11 environments.
4.  **Termux:** It will use `termux-clipboard-get`.
5.  **Generic Fallback:** If none of the above specific tools are found, it will attempt to use the `pyperclip` library as a final fallback.

This multi-tiered approach ensures that `llm-patcher` can function correctly across the wide variety of terminal environments used by developers.

### The LLMPS v1 Parsing Engine

The core of the tool is its ability to parse the LLMPS v1 syntax. A function, `parse_llmps`, will be implemented to transform the raw clipboard text into a structured, in-memory representation. This parser will operate as a line-by-line state machine, making it efficient and scalable.

The parser will maintain its current state (e.g., `AWAITING_HEADER`, `IN_HUNK_BEFORE`, `IN_CREATE_CONTENT`) and process each line accordingly.
*   When it encounters a header like `UPDATE-FILE:`, it creates a new `PatchOperation` object and transitions to a state expecting a `HUNK:` or `---`.
*   When it sees an indented line within a `CONTENT:` or `BEFORE:` block, it appends that line to the current block's content.
*   Lines with `---` signal the end of the current file operation and reset the state to `AWAITING_HEADER`.

This process yields a list of data class objects (e.g., `UpdateFileOp`, `CreateFileOp`), each containing the structured data needed for the application phase.

### The Atomic Application Engine

Applying file changes is a critical operation where data integrity is paramount. A simple `open(path, 'w')` is inherently unsafe because it truncates the file before writing; an interruption during this process can lead to data loss.[span_0](start_span)[span_0](end_span)[span_1](start_span)[span_1](end_span) To prevent this, `llm-patcher` will implement an atomic application engine based on the "temporary file and rename" pattern, a well-established method for ensuring atomic writes.[span_2](start_span)[span_2](end_span)[span_3](start_span)[span_3](end_span)

The `apply_patch` function will use a two-phase commit protocol for maximum safety:

1.  **Phase 1: Verification and Staging.** In this phase, the engine performs all operations in-memory or on temporary files, without modifying the user's source files.
    *   It iterates through each `PatchOperation` from the parser.
    *   For an `UPDATE-FILE` operation, it reads the target file into memory. It then searches for the exact sequence of lines specified in each hunk's `BEFORE:` and `AFTER:` blocks. If any context block cannot be found, the entire patch is considered invalid, and the process aborts with a clear error message.
    *   For all operations (`CREATE`, `UPDATE`), the new, intended content of the file is written to a temporary file in the same directory (e.g., `main.py.llm-patch.tmp`). Writing to the same directory is crucial to ensure that the final `rename` operation occurs on the same filesystem, which is a prerequisite for atomicity on POSIX systems.[span_4](start_span)[span_4](end_span)
    *   For a `DELETE-FILE` operation, it simply verifies that the file exists.
    *   If any step in this phase fails, the engine immediately cleans up all temporary files it created and exits, leaving the user's workspace untouched.

2.  **Phase 2: Commit.** This phase is executed only if the verification phase completes successfully for all file operations in the patch.
    *   The engine iterates through the staged changes.
    *   For each temporary file created in Phase 1, it uses `os.replace()` (which is an atomic `rename` on POSIX systems) to move the temporary file to its final destination, overwriting the original file in a single, atomic step.[span_5](start_span)[span_5](end_span)
    *   For each `DELETE-FILE` operation, it uses `os.remove()` to delete the target file.
    *   For each `RENAME-FILE` operation, it uses `os.rename()`.

This two-phase approach guarantees that a patch is either applied in its entirety or not at all, preventing partial or corrupt states.

### User Interface and Safety Features

To be a practical developer tool, `llm-patcher` requires a user-friendly and safe command-line interface.

*   **Command-Line Interface:** The CLI is built using Python's standard `argparse` library, providing familiar help messages and argument parsing.

*   **Dry Run Mode (`--dry-run`):** A crucial safety feature is the `--dry-run` flag. When enabled, the tool will execute the entire verification and staging phase (Phase 1) but will stop just before the commit phase. It will print a summary of the changes and the unified diffs that would be applied, allowing the user to inspect the outcome without any risk.

*   **Interactive Confirmation:** By default, `llm-patcher` operates in an interactive mode. After the verification phase succeeds, it presents the user with a summary of the pending changes (e.g., `M src/main.py`, `A src/utils.py`) and a colorized unified diff for each modification. It then prompts for explicit confirmation (`[y/N]`). The patch is only applied if the user enters "y". This interactive confirmation step acts as a final, critical safety check, mirroring the approval-gate design of `codex-cli`. This behavior can be bypassed with a `--yes` flag for use in trusted scripts.

| Argument | Shorthand | Description | Default |
| :--- | :--- | :--- | :--- |
| `--dry-run` | `-d` | Verify patch and show changes without applying. | `False` |
| `--yes` | `-y` | Skip interactive confirmation and apply patch directly. | `False` |
| `--help` | `-h` | Show the help message and exit. | N/A |

### Packaging for Distribution (`pyproject.toml`)

To make `llm-patcher` easily installable and runnable as a system-wide command, it will be packaged using modern Python standards with a `pyproject.toml` file. The key to creating a command-line executable is the `[project.scripts]` table, a standard mechanism defined by Python packaging specifications.[span_6](start_span)[span_6](end_span)[span_7](start_span)[span_7](end_span)[span_8](start_span)[span_8](end_span)

The `pyproject.toml` file will define the project metadata, dependencies, and the crucial entry point:

```toml
[project]
name = "llm-patcher"
version = "1.0.0"
dependencies = [
    "pyperclip>=1.8.0"
]

[project.scripts]
llm-patcher = "llm_patcher.main:run"

This configuration instructs the installer (e.g., pip) to create an executable script named llm-patcher in the user's path. When executed, this script will call the run function inside the llm_patcher/main.py module. This is the standard, cross-platform method for distributing Python-based CLI tools.
Complete Source Code
This section provides the complete, production-ready source code for the llm-patcher utility and its associated packaging configuration.
pyproject.toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "llm-patcher"
version = "1.0.0"
authors =
description = "A tool to safely apply LLM-generated code patches from the clipboard."
readme = "README.md"
requires-python = ">=3.8"
classifiers =
dependencies = [
    "pyperclip>=1.8.0"
]

[project.urls]
"Homepage" = "https://github.com/example/llm-patcher"

[project.scripts]
llm-patcher = "llm_patcher.main:run"

llm_patcher/main.py
#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

# Use pyperclip as a fallback
try:
    import pyperclip
except ImportError:
    pyperclip = None

# --- Color Constants for Terminal Output ---
class Colors:
    HEADER = '\033 = field(default_factory=list)
    remove: List[str] = field(default_factory=list)
    add: List[str] = field(default_factory=list)
    after: List[str] = field(default_factory=list)

@dataclass
class CreateFileOp:
    path: Path
    content: List[str]

@dataclass
class DeleteFileOp:
    path: Path

@dataclass
class UpdateFileOp:
    path: Path
    hunks: List[Hunk]

@dataclass
class RenameFileOp:
    source_path: Path
    dest_path: Path

PatchOperation = Union

# --- Clipboard Utility ---
def get_clipboard_text() -> str:
    """Gets text from the system clipboard using a robust, cross-platform strategy."""
    # Check for WSL
    if "microsoft" in os.uname().release.lower():
        try:
            return subprocess.check_output(['win32yank.exe', '-o'], text=True, encoding='utf-8')
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                return subprocess.check_output(['clip.exe'], text=True, encoding='utf-8')
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass # Fall through

    # Check for macOS
    if sys.platform == "darwin":
        try:
            return subprocess.check_output(['pbpaste'], text=True, encoding='utf-8')
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass # Fall through

    # Check for Linux (Wayland/X11)
    if sys.platform.startswith("linux"):
        tools = ['wl-paste'],
            ['xclip', '-selection', 'clipboard', '-o'],
            ['xsel', '--clipboard', '--output']
        for tool in tools:
            try:
                return subprocess.check_output(tool, text=True, encoding='utf-8')
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    
    # Check for Termux
    if "com.termux" in os.environ.get("PREFIX", ""):
        try:
            return subprocess.check_output(['termux-clipboard-get'], text=True, encoding='utf-8')
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    # Fallback to pyperclip
    if pyperclip:
        return pyperclip.paste()

    raise RuntimeError("Could not access clipboard. Please install xclip, xsel, wl-clipboard, or pyperclip.")

# --- LLMPS v1 Parser ---
def parse_llmps(patch_text: str) -> List[PatchOperation]:
    """Parses a string in LLMPS v1 format into a list of PatchOperation objects."""
    operations =
    file_blocks = patch_text.strip().split('\n---\n')

    for block in file_blocks:
        lines = block.strip().split('\n')
        header = lines

        if header.startswith("CREATE-FILE:"):
            path = Path(header.split(":", 1).strip())
            if len(lines) < 2 or lines.strip()!= "CONTENT:":
                raise ValueError(f"CREATE-FILE block for {path} is missing CONTENT: marker.")
            
            content_lines =
            if len(lines) > 2:
                first_line_indent = len(lines) - len(lines.lstrip(' '))
                for line in lines[2:]:
                    # Un-indent by the amount of the first content line
                    content_lines.append(line[first_line_indent:])
            operations.append(CreateFileOp(path=path, content=content_lines))

        elif header.startswith("DELETE-FILE:"):
            path = Path(header.split(":", 1).strip())
            operations.append(DeleteFileOp(path=path))

        elif header.startswith("RENAME-FILE:"):
            parts = header.split(":", 1).strip().split(" TO ")
            if len(parts)!= 2:
                raise ValueError(f"Invalid RENAME-FILE header: {header}")
            source_path = Path(parts.strip())
            dest_path = Path(parts.strip())
            operations.append(RenameFileOp(source_path=source_path, dest_path=dest_path))

        elif header.startswith("UPDATE-FILE:"):
            path = Path(header.split(":", 1).strip())
            hunks =
            current_hunk = None
            current_section = None

            for line in lines[1:]:
                stripped_line = line.lstrip(' ')
                indent_level = len(line) - len(stripped_line)

                if stripped_line.startswith("HUNK:"):
                    if current_hunk:
                        hunks.append(current_hunk)
                    current_hunk = Hunk()
                    current_section = None
                elif current_hunk:
                    if stripped_line.startswith("BEFORE:"):
                        current_section = current_hunk.before
                    elif stripped_line.startswith("REMOVE:"):
                        current_section = current_hunk.remove
                    elif stripped_line.startswith("ADD:"):
                        current_section = current_hunk.add
                    elif stripped_line.startswith("AFTER:"):
                        current_section = current_hunk.after
                    elif current_section is not None:
                        # Find the indent of the first line of the current section
                        if not current_section:
                            first_line_indent = indent_level
                        else:
                            # This logic assumes consistent indentation within a block
                            first_line_indent = indent_level
                        
                        current_section.append(line[first_line_indent:])
                    else:
                        raise ValueError(f"Unexpected line in UPDATE-FILE block: {line}")
            
            if current_hunk:
                hunks.append(current_hunk)
            operations.append(UpdateFileOp(path=path, hunks=hunks))
        
        else:
            raise ValueError(f"Unknown operation header: {header}")
            
    return operations

# --- Atomic Application Engine ---
def find_subsequence(main_list: List[str], sub_list: List[str]) -> int:
    """Finds the starting index of a sub-list within a main list."""
    if not sub_list:
        return 0
    for i in range(len(main_list) - len(sub_list) + 1):
        if main_list[i:i+len(sub_list)] == sub_list:
            return i
    return -1

def apply_patch(operations: List[PatchOperation], dry_run: bool, skip_confirmation: bool):
    """Verifies and applies a list of patch operations atomically."""
    staged_changes =
    
    print(color_text("--- Verification Phase ---", Colors.HEADER))

    # --- Phase 1: Verification & Staging ---
    try:
        for op in operations:
            if isinstance(op, CreateFileOp):
                print(f"Verifying CREATE-FILE: {op.path}")
                if op.path.exists():
                    raise FileExistsError(f"File {op.path} already exists. Use UPDATE-FILE instead.")
                staged_changes.append(('create', op.path, op.content))

            elif isinstance(op, DeleteFileOp):
                print(f"Verifying DELETE-FILE: {op.path}")
                if not op.path.is_file():
                    raise FileNotFoundError(f"File to delete does not exist: {op.path}")
                staged_changes.append(('delete', op.path, None))

            elif isinstance(op, RenameFileOp):
                print(f"Verifying RENAME-FILE: {op.source_path} -> {op.dest_path}")
                if not op.source_path.is_file():
                    raise FileNotFoundError(f"File to rename does not exist: {op.source_path}")
                if op.dest_path.exists():
                    raise FileExistsError(f"Destination for rename already exists: {op.dest_path}")
                staged_changes.append(('rename', op.source_path, op.dest_path))

            elif isinstance(op, UpdateFileOp):
                print(f"Verifying UPDATE-FILE: {op.path}")
                if not op.path.is_file():
                    raise FileNotFoundError(f"File to update does not exist: {op.path}")
                
                with open(op.path, 'r', encoding='utf-8') as f:
                    original_lines = f.read().splitlines()

                modified_lines = list(original_lines)
                offset = 0

                for hunk in op.hunks:
                    if not hunk.before:
                        raise ValueError("Hunk is missing mandatory BEFORE block.")
                    
                    start_index = find_subsequence(modified_lines, hunk.before)
                    if start_index == -1:
                        raise ValueError(f"Could not find context for hunk in {op.path}:\n---\n" + "\n".join(hunk.before) + "\n---")
                    
                    change_point = start_index + len(hunk.before)
                    
                    # Verify REMOVE block
                    if hunk.remove:
                        remove_len = len(hunk.remove)
                        if modified_lines[change_point : change_point + remove_len]!= hunk.remove:
                            raise ValueError(f"REMOVE block does not match content in {op.path}")
                    
                    # Apply changes
                    del modified_lines[change_point : change_point + len(hunk.remove)]
                    modified_lines[change_point:change_point] = hunk.add
                
                staged_changes.append(('update', op.path, modified_lines))

        print(color_text("\nVerification successful.", Colors.OKGREEN))

    except (ValueError, FileNotFoundError, FileExistsError) as e:
        print(color_text(f"\nVerification failed: {e}", Colors.FAIL))
        sys.exit(1)

    # --- Display Diff and Ask for Confirmation ---
    print(color_text("\n--- Proposed Changes ---", Colors.HEADER))
    for change_type, path, content in staged_changes:
        if change_type == 'create':
            print(color_text(f"A {path}", Colors.OKGREEN))
            for line in content:
                print(color_text(f"+ {line}", Colors.OKGREEN))
        elif change_type == 'delete':
            print(color_text(f"D {path}", Colors.FAIL))
        elif change_type == 'rename':
            print(color_text(f"R {path} -> {content}", Colors.OKCYAN))
        elif change_type == 'update':
            print(color_text(f"M {path}", Colors.OKBLUE))
            original_lines = path.read_text(encoding='utf-8').splitlines()
            diff = generate_diff(original_lines, content)
            print(diff)
    
    if dry_run:
        print(color_text("\nDry run complete. No files were changed.", Colors.WARNING))
        return

    if not skip_confirmation:
        response = input(color_text("\nApply these changes? [y/N] ", Colors.BOLD)).lower().strip()
        if response!= 'y':
            print("Operation cancelled.")
            sys.exit(0)

    # --- Phase 2: Commit ---
    print(color_text("\n--- Application Phase ---", Colors.HEADER))
    temp_files =
    try:
        for change_type, path, content in staged_changes:
            if change_type in ['create', 'update']:
                with tempfile.NamedTemporaryFile('w', delete=False, dir=path.parent, encoding='utf-8') as tmp:
                    tmp.write("\n".join(content))
                    # Ensure content has a trailing newline if it's not empty
                    if content:
                        tmp.write("\n")
                    temp_files.append((tmp.name, path))
        
        # If all temp files are written successfully, then rename them
        for tmp_name, final_path in temp_files:
            os.replace(tmp_name, final_path)
            print(f"Applied change to {final_path}")

        # Handle deletions and renames after updates to avoid conflicts
        for change_type, path, content in staged_changes:
            if change_type == 'delete':
                os.remove(path)
                print(f"Deleted {path}")
            elif change_type == 'rename':
                os.rename(path, content)
                print(f"Renamed {path} to {content}")

        print(color_text("\nPatch applied successfully.", Colors.OKGREEN))

    except Exception as e:
        print(color_text(f"\nAn error occurred during the application phase: {e}", Colors.FAIL))
        # Clean up any temp files that were created
        for tmp_name, _ in temp_files:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        print("Operation rolled back. Your files have not been changed.")
        sys.exit(1)

def generate_diff(old_lines: List[str], new_lines: List[str]) -> str:
    """Generates a colorized unified diff string."""
    diff =
    import difflib
    for line in difflib.unified_diff(old_lines, new_lines, lineterm=''):
        if line.startswith('+'):
            diff.append(color_text(line, Colors.OKGREEN))
        elif line.startswith('-'):
            diff.append(color_text(line, Colors.FAIL))
        elif line.startswith('@@'):
            diff.append(color_text(line, Colors.OKCYAN))
        else:
            diff.append(line)
    return "\n".join(diff)

# --- Main Execution Logic ---
def run():
    parser = argparse.ArgumentParser(
        description="Safely apply LLM-generated code patches from the clipboard."
    )
    parser.add_argument(
        '-d', '--dry-run',
        action='store_true',
        help="Verify patch and show changes without applying."
    )
    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help="Skip interactive confirmation and apply patch directly."
    )
    args = parser.parse_args()

    try:
        patch_text = get_clipboard_text()
        if not patch_text.strip():
            print("Clipboard is empty. No patch to apply.")
            sys.exit(0)

        operations = parse_llmps(patch_text)
        apply_patch(operations, args.dry_run, args.yes)

    except Exception as e:
        print(color_text(f"An unexpected error occurred: {e}", Colors.FAIL))
        sys.exit(1)

if __name__ == "__main__":
    run()

Synthesis, Recommendations, and Future Work
This report has detailed a complete system for enabling robust, multi-file code modifications driven by Large Language Models. The system is composed of three core components: a formally specified patch syntax (LLMPS v1), a comprehensive system prompt for guiding LLM generation, and a safety-oriented command-line utility (llm-patcher) for applying the patches. The design is heavily informed by an analysis of the existing codex-cli agentic system, adopting its successful patterns while improving upon areas of potential ambiguity and complexity.
Synthesis of the LLMPS System
The designed system offers a cohesive solution that prioritizes safety, robustness, and usability in the context of AI-assisted software development.
 * Safety: The system's safety is multi-layered. At the lowest level, the llm-patcher utility uses atomic file-writing operations to prevent data corruption during application. At the user-interface level, it defaults to an interactive confirmation mode, requiring explicit user consent before any files are modified. This combination of transactional file operations and a human-in-the-loop design provides strong guarantees against accidental data loss or unwanted changes.
 * Robustness: Robustness is achieved through both the syntax design and the implementation of the tooling. The LLMPS v1 syntax is unambiguous and designed for simple, deterministic parsing, which reduces the likelihood of misinterpreting the LLM's intent. The llm-patcher's clipboard integration is built on a cross-platform, multi-fallback strategy, ensuring it functions reliably across a wide range of developer environments.
 * Modularity: The system is inherently modular. The llm-patcher tool is a standalone utility, completely decoupled from the LLM and the environment in which the patch is generated. This separation of concerns is a powerful architectural choice. It allows any LLM-powered application—be it a CLI, an IDE extension, or a web service—to generate patches in the LLMPS v1 format and delegate the complex and security-sensitive task of file system modification to a single, trusted tool.
Recommendations for Future Work
While the proposed system provides a strong foundation, several avenues exist for future enhancement that would further integrate it into professional software development workflows.
 * Git Integration: A significant enhancement would be to integrate llm-patcher directly with Git. This could include features such as:
   * An option to automatically create a new Git branch before applying a patch, isolating the AI-generated changes.
   * An option to automatically commit the changes after a successful application, using the initial user prompt as the basis for the commit message.
   * The ability to generate a patch by diffing against a specific branch or commit, rather than just the live file system.
 * Self-Correction Loop: The current system is unidirectional: the LLM generates a patch, and the tool applies it. A more advanced system could create a feedback loop. If llm-patcher fails during the verification phase (e.g., because context lines were not found), it could generate a structured error report. This report could be fed back to the LLM, which could then attempt to diagnose the problem (e.g., the file was modified since the patch was generated) and generate a corrected patch.
 * IDE Integration: While the clipboard is a universal interface, a more seamless integration could be achieved by building a server mode into llm-patcher. This mode would allow the tool to listen for patch application requests on a local HTTP port. IDE extensions (for platforms like VS Code or JetBrains) could then send patches directly to this service, bypassing the clipboard entirely and enabling a more fluid user experience.
 * Advanced Context Matching: The current patch application logic relies on an exact match of context lines. This can be brittle if the source file has undergone minor, unrelated changes (e.g., reformatting or adding a comment). Future versions could implement a more resilient fuzzy matching algorithm for locating context blocks. This approach, hinted at in the codex-cli test test_update_line_with_unicode_dash, could tolerate small variations in whitespace and punctuation, making the patch application process more robust in a dynamic development environment.
