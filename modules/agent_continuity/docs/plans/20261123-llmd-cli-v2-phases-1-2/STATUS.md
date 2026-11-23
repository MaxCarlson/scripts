# LLMD CLI v2 phases 1-2

Status: implemented and validated on feature/llmd-cli-v2-20261123; implemented and validated; local commit recorded.

Scope: global and scoped listings, composite registration, positional forms, compatibility, and documentation. Phases 3-4 and live provider or terminal launches remain deferred.

Implementation uses existing events and the dispatcher mutation lock, with ordered event timestamps for replay. A partial registration can be retried. Registration selection changes have no runtime observation in this phase.

Validation: python -m pytest -q --basetemp=.pytest_tmp_root/llmd-v2-full; python -m ruff check agent_continuity/dispatcher.py agent_continuity/dispatcher_cli.py tests/dispatcher_v2_test.py.

Next: independently review deferred phases 3-4; do not push.
