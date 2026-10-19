# Local worker tools and permissions - 2026-10-19

The earlier audit was committed and pushed as d0eeb895 before this investigation.
This follow-up inspected current OpenCode configuration without inference,
delegation, model loading, permission changes or starting/stopping services.

## Verified resolved tools

OpenCode CLI 1.19.3 supports a diagnostic that resolves the actual named roles:

```powershell
opencode debug agent local-worker
opencode debug agent local-reviewer
```

Run from the scripts root against the current installed user configuration:

| Tool | local-worker | local-reviewer |
| --- | --- | --- |
| read, glob, grep | enabled | enabled |
| edit, write | enabled | disabled |
| bash | enabled | disabled |
| webfetch, todowrite, skill | enabled | enabled |
| task (recursive delegation) | disabled | disabled |
| question | disabled by resolved runtime policy | disabled by resolved runtime policy |

The worker's effective base permission is allow. The role adds task denial and
denies loading local-agent-handoff; it does not deny editing or shell execution.
The reviewer adds edit and bash denials. Denying edit covers write/apply_patch
as documented by OpenCode. The observed tool catalog exposes edit/write for this
local provider; a separate apply_patch tool is not required to modify files.

The installed global opencode.json has no global permission/tools overrides,
no inline competing agent definitions, no MCP tool servers and no plugins.
No opencode.json, opencode.jsonc or .opencode directory was present in the scripts
workspace. None of the inspected OpenCode/config-home override variables was set.
Other projects and existing sessions can differ and require their own inspection.

## Interpretation and remedies

1. **No persistent worker write block was found.** No permission relaxation is
   warranted. Use agent=local-worker for authorized editing and local-reviewer
   for inspection. The earlier read-only trial selected local-reviewer, so its
   absent write/bash tools match the role's intended permissions.
2. **Keep the essential MCP profile.** It controls which coordinator-facing
   OpenCode MCP operations are advertised, not the model's built-in read/write
   tools. Switching to full does not fix worker filesystem access.
3. **Use the correct workspace and handle real permission requests.** The
   resolved policy asks for external_directory access and protected .env reads;
   doom_loop also asks. Supply an explicit absolute directory on dispatch and
   observation. Inspect input_required via the exposed permission/job-input tools;
   approve only a concrete authorized request. Do not blanket-allow all paths to
   suppress these requests. A model can return a blocker in text when question
   is unavailable; that does not remove its read/write tools.
4. **Fresh sessions isolate old task instructions.** The previous temporary
   no-write request may still constrain an old conversation. Reusing that session
   can preserve it even when current role configuration permits writing. Use a
   fresh session for an unrelated edit test and an explicit task envelope. This
   is a possible explanation, not a verified finding about an old session.
5. **Model behavior still needs a permitted live test.** Resolved tools establish
   configuration availability, not successful model tool calls, valid chat-template
   encoding, filesystem ACL access or edit correctness. The earlier no-delegation
   instruction remains in force; no local model job was dispatched here.

The HTTP readiness check found LM Studio responding on 1234, while OpenCode's
4096 health request timed out after two seconds. That does not prove a tool
permission failure or that no process exists; no repeated requests were made.
The next permitted live check should use a disposable workspace: read a known
file, write/edit an allowed file, run a harmless focused check and verify the
sentinel/diff. Review prompts and returned job evidence before changing settings.

## Previously incomplete planned work

- Real local-worker bounded editing, honest checks and recursion behavior.
- Permission/input-required handling and related-session follow-up validation.
- Cancellation during editing and repeatable structured-output/schema checks.
- Reproducible fixture and measured control trials for token/latency claims.
- Applying the prepared host migration and confirming clean status afterward
  (completed with user authorization on 2026-10-19; see HANDOFF.md).
- Claude/Cursor and non-skill resource migration adapters; retain legacy dotfiles
  and rollback targets until replacements are verified.

These include validation and migration tasks, not evidence that every associated
runtime API or feature is missing. A/C/D in BENCHMARK.md remain historical reported
observations. The new mining request is only a
[deferred note](plans/20261019_gpu-workload-coordination/plan.md).

## Primary sources

- [OpenCode built-in tools](https://opencode.ai/docs/tools/): editing, writing,
  shell execution and the shared edit permission.
- [OpenCode permissions](https://opencode.ai/docs/permissions/): tool rules,
  agent overrides and external-directory prompts. Installed diagnostic output
  takes precedence over differences in documentation for later versions.
- [opencode-mcp 3.0.0 configuration](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/configuration.md):
  essential/full catalogs and explicit server startup.
