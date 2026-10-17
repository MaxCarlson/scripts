# Generic profiles and optional capabilities

The generic source is `local_agent_bridge/resources/profiles/AGENTS.md`. It
contains no local-model delegation policy. Feature text is authored separately
in `resources/instructions/coordinator.snippet.md`; the shared skill and worker
prompt are separate assets too.

Place an anchor where a capability belongs:

```markdown
## Working agreements

<!-- local_agent:insert capabilities -->

## Other instructions
```

`setup/profiles.py:render_template(template, insertions)` takes named fragments
and returns a new string. Each requested anchor must occur exactly once. Names
use lowercase letters, digits, underscores or hyphens and start with a letter.
The source file is never modified. Empty insertions produce the generic profile.
Additional named slots can be used by callers of the utility; the current setup
adapter supplies the `capabilities` slot.

Local delegation is wrapped in `local-agent-bridge:begin` / `:end` HTML comments.
Setup can update or remove that exact contribution without matching the entire
global file. Exact unmarked existing snippet text is recognized and left unowned;
setup never appends a second copy. Edited or malformed markers block changes.

For a fresh or explicitly adopted whole profile, setup writes a rendered file
under its state directory and links/copies it to the effective global location.
Adoption retains active instruction content as its baseline, including newer rules
that differ from the archived dotfiles templates. Removing installation restores
the prior file or link. To change from block management to whole-profile adoption,
remove the block installation first, then plan adoption.

Switch between setups:

```powershell
local_agent setup apply -m generic
local_agent setup apply -m local
```

Generic retains generic settings/custom skills and removes owned local resources.
Local adds them again. Pre-existing recognizable module MCP definitions are disabled
in generic mode; uninstall restores their original state. Arbitrary competing MCP
or agent definitions require reconciliation rather than implicit replacement.
