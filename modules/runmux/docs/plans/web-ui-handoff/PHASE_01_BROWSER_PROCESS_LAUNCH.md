# Runmux Web UI — Phase 1 Agent Handoff: Browser Process Launch

**Phase ID:** RUNMUX-WEB-P1  
**Status:** **Active under the earlier Milestone 1 handoff**; this is a supplemental acceptance/reference specification, not a new assignment or reason to restart work.  
**Priority:** **P0**  
**Primary backlog:** L01–L09, S01–S05, S08–S09  
**Prerequisites:** Current `origin/main`, isolated worktree/registry, verified `runmux run` contract and web-session authorization behavior.

## 1. Objective

Enable a user to start a persistent Runmux-managed CLI process directly from the browser. A `+` tab opens a **New Process** form that has the same underlying process-launch semantics as `runmux run <program stuff here>`. Successful launches appear immediately in the existing process explorer and open as an ordinary run tab, with output available through the existing viewer.

This is the first planned browser write action. It must preserve the existing read-only viewing experience and respect existing authentication/security boundaries. Do not re-implement the supervisor or registry in frontend code.

## 2. Current UI evidence

Current screenshots show a process list and tabs but no new-process tab or launch form. The empty registry view advises the user to start a run using the CLI. The header includes `LOCAL SESSION`, `Registry connected`, and `Lock` indicators. The browser is explicitly labeled read-only. Screenshots do **not** prove whether a launch endpoint or service helper is already present.

## 3. In-scope user interactions

1. A visible **+** button in the process-tab strip exists even when the registry is empty.
2. The empty-process state also offers **New Process**, rather than only CLI instructions.
3. Clicking `+` opens a distinct temporary **New Process** tab. Switching to other tabs does not discard typed form content.
4. Form includes a required command/program with arguments and a working-directory field (explicit default behavior). Include the optional process-name field specified in the already-issued Milestone 1 handoff; reuse the existing CLI name semantics rather than inventing them.
5. Submitting the form invokes the same underlying Python launch/supervision path as the existing CLI, after permission and input validation.
6. While starting, disable duplicate submits or safely deduplicate the request and show a clear pending state.
7. Success produces a **real run ID**, refreshes/discovers the new registry entry, and opens its tab; never use process name as identity.
8. Failure leaves the draft intact and shows a concrete error without registering a ghost entry.
9. Closing the New Process tab discards only the draft (after a reasonable unsaved-data prompt if needed). Closing a successfully launched process tab never stops the process.

## 4. Required repository investigation before design/implementation

- Read `runmux run --help`, CLI parser and dispatch code. Document how program vs arguments, Runmux flags, working directory, environment, shell mode, name, stdout capture, PTY and detach/supervision are represented. Avoid assuming that a single command textbox is semantically sufficient for all platforms.
- Trace the existing process spawn, registry registration, supervisor ownership, readiness, error, and log attachment path. Reuse that path rather than calling `subprocess.Popen` from an unrelated web handler.
- Inspect `modules/web_ui_tools/` and Runmux's web API for current methods, authentication/session/access-code lifecycle, origin protections, and write permission semantics. The existing login authenticates a single local browser session and the Lock control logs it out; there is no separate viewer/elevated role in the inspected framework. Enforce authenticated, same-origin state-changing requests on the server. Do not invent a new elevation/role flow without a concrete need and user approval.
- Inspect Windows 11, macOS, Linux/WSL2 argument parsing behavior relevant to Runmux. Preserve CLI behavior; distinguish `argv` launching from explicit shell commands. Do **not** naively use `shell=True` or a POSIX-only `shlex.split` as a cross-platform implementation.
- Verify whether the browser and supervisor may run as different users or environments, how the cwd default is chosen, and whether path existence/permission failures are returned reliably.
- Identify current tests and fixtures. Do not assume test names, API paths or UI framework internals before inspection.

## 5. Functional contract and error cases

**Command model:** Prefer a command representation that exactly matches the verified CLI contract. The UI may show one familiar command entry field, but backend transport must preserve the distinction between program, arguments, Runmux options, and (only when intentionally selected) shell interpretation. Never treat the string as a template to execute through a shell by default.

**Errors:** Handle empty command, nonexistent executable, inaccessible/invalid working directory, denied authorization, failed registry write, supervisor startup failure, malformed input, process that exits immediately, and concurrent launch attempts. Distinguish a launched run that exits quickly from a launch failure.

**State transitions:** New Process draft → submitting → registered run (or draft with error). If the registry refresh is delayed, reconcile using the returned run ID. Never create duplicate browser tabs for the same run.

**Scope exclusions:** Do not add advanced presets, scheduling, batch launch, full environment editor, lifecycle controls, arbitrary shell aliases, user-defined scripts, or a new PTY input stack in this phase unless the user authorizes a narrowly justified dependency.

## 6. Security gates

Launching programs from localhost is equivalent to granting local code execution in the service's privilege context. Before enabling it:

- Verify loopback-only access, session/authentication/access-code validation, expiration and use rules, origin/CSRF defenses, and explicit authorization for mutation.
- Ensure unauthenticated, expired/locked-session, wrong-origin, or malformed requests cannot invoke launch endpoints directly, even if frontend controls are hidden. There is no separate viewer role in the current single-user web-session model.
- Avoid logging secrets or exposing full environment values. Never store launch credentials in URL query strings or long-lived browser preferences.
- Use server-side validation and explicit authorization; frontend-only validation is insufficient.
- Verify UI displays untrusted subprocess output as inert text/terminal content, not active HTML.
- Do not launch on GET, page load, UI restore, autosave, or automatic retry.

## 7. Validation plan (isolated, non-destructive)

Test only in a separate worktree and disposable registry, on a non-production port using synthetic programs.

| Scenario | Expected behavior |
|---|---|
| Empty registry | New Process entry visible and usable in authorized session |
| Simple long-running Python command | New run registered; output visible; run stays alive when browser tab closes |
| Quoted argument with spaces | Argument arrives as one argument according to actual CLI contract |
| Working directory containing spaces | Correct cwd or explicit failure; no silent path mangling |
| Missing executable | Useful failure; no ghost process |
| Invalid/inaccessible cwd | Rejected safely; form retained |
| Rapid double-click on Launch | One launch or explicitly safe deduplication |
| Locked/unauthorized request | Endpoint denies mutation; UI shows correct reason |
| Immediate process exit | Registered run and terminal state remain consistent |
| Refresh/reconnect | New run discoverable by run ID; no repeat launch |
| Two same-named runs | Distinct tabs and registry entries keyed by run ID |

**Cross-platform claims:** Only claim Windows, WSL2, macOS or Termux support where that runtime is actually exercised or supported by source-level reasoning plus explicit limitations. Use existing project-local validation tooling if present.

## 8. Acceptance criteria

- [ ] Authorized user can open a new-process tab and launch a synthetic Runmux-managed process.
- [ ] Launch behavior matches the **verified** relevant `runmux run` command semantics.
- [ ] Process appears in explorer and opens under its unique run ID; logs are accessible.
- [ ] Closing/browser refreshing does not terminate or duplicate the run.
- [ ] Unauthorized/locked browser requests cannot launch.
- [ ] Failures are visible, non-destructive, and leave no false successful registry entries.
- [ ] Existing read-only browsing, terminal and details functions do not regress.
- [ ] Automated tests and isolated end-to-end checks support the claims.

## 9. Expected agent deliverables

1. Short API/CLI/authorization reconnaissance summary, citing code paths.
2. A scoped implementation plan with only **out-of-scope product/security decisions** escalated if necessary.
3. Code/tests/documentation on the **existing active feature branch**, as authorized by the original Milestone 1 handoff.
4. Reproducible isolated validation commands and results, plus security regression tests.
5. Commit/PR reference and a list of deferred requirements, including L10–L12.

## 10. Relationship to the existing assignment

The active Milestone 1 agent has **already received an implementation handoff** covering the essential feature. This Phase 1 document supplies additional edge cases and implementation checks, but it does **not** expand authorized scope or request a new plan/worktree. Send the agent `CURRENT_AGENT_PHASE_01_ADDENDUM.md` rather than another full assignment.
