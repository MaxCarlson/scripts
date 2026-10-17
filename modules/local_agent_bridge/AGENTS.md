# Local agent bridge

- The moved loader implementation is `local_agent_bridge/cli.py`.
- Preserve its arguments, defaults and operational behavior when changing it.

- Keep the skill, coordinator snippet, worker prompt and settings here for now.
  Do not install them into user profiles or edit dotfiles as part of resource edits.
- Read `README.md` for the resource map. Read only the relevant supporting document.
- Keep one canonical worker prompt in the skill's `resources/` directory.
- Coordinator skill instructions do not authorize recursive dispatch by the worker.
  Keep worker/reviewer examples consistent with that role boundary.
- Validate skill metadata, relative links and example JSON after changes.
- Behavioral validation requires permitted worker use. Do not invoke agents/models
  when delegation is disabled; record unperformed checks accurately.
- Module-owned progress belongs in `docs/HANDOFF.md`.
- The current resource implementation plan is linked from the module README.
