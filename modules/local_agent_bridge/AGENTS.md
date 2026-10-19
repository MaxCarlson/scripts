# Local agent bridge

- The moved loader implementation is `local_agent_bridge/cli.py`.
- Preserve its arguments, defaults and operational behavior when changing it.
- The main CLI is `local_agent_bridge/commands.py`, exposed as `local-agent`
  with `local_agent` retained as an alias.
- The independent installer lives in `local_agent_bridge/setup/`; do not depend
  on or invoke the unreviewed agent_abilities/agent_skills managers.

- Authored and copied assets are packaged in `local_agent_bridge/resources/`.
- Keep generic profiles separate from local capability fragments; exercise mode
  switching and named insertion anchors when changing profile rendering.
- Keep the skill, coordinator snippet, worker prompt and settings here.
  Do not install them into user profiles or edit dotfiles as part of resource edits.
- Read `README.md` for the resource map. Read only the relevant supporting document.
- Keep one canonical worker prompt in the skill's `resources/` directory.
- Coordinator skill instructions do not authorize recursive dispatch by the worker.
  Keep worker/reviewer examples consistent with that role boundary.
- Validate skill metadata, relative links and example JSON after changes.
- Behavioral validation requires permitted worker use. Do not invoke agents/models
  when delegation is disabled; record unperformed checks accurately.
- Module-owned progress belongs in `docs/HANDOFF.md`.
- Installer validation uses isolated homes under this module's `.pytest_tmp_root/`.
- The current resource implementation plan is linked from the module README.
