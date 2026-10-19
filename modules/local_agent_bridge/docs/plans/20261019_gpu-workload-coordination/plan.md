# Deferred: coordinate competing programs with local model activity

Status: request recorded only. Do not implement or activate yet.
Requested: 2026-10-19. The user reiterated that this should only be written down.

## Requested behavior

- Allow configured competing programs, initially the user's crypto miner, to be
  paused or closed when a local model needs the GPU for loading or actual use.
- Cover inference attempted by an agent or another client, not just one Codex
  dispatch path. Account for model loading separately from inference activity.
- An idle loaded model should not keep the miner stopped indefinitely.
- Restart/resume the program after a configurable interval without model use.
  Concurrent requests and streaming responses must count as active until finished.

## Decisions for later implementation

- Define the authoritative load/request/activity signal and how clients outside
  the bridge are observed. Do not equate model residency with inference activity.
- Define the inactivity interval, startup grace, failure behavior and manual
  override. A request during the idle countdown must prevent an early restart.
- Decide whether the miner supports a pause that releases enough GPU resources,
  or requires graceful shutdown followed by a configured relaunch command.
- Record which process was previously running and which controller owns it;
  restart only a program this feature stopped, preserving manual stops.
- Handle overlapping requests, cancelled streams, controller crashes, restart
  cooldowns and unknown activity without repeatedly stopping/starting programs.
- Evaluate reuse of the scheduler's monitored-process ownership/lifecycle code
  before adding a second process supervisor; inspect current implementation first.
- Plan isolated tests and an explicitly authorized live validation. No current
  miner process, scheduler rule, model/server configuration or service is changed
  by this note.

No implementation tasks have started. Architecture and concrete process targets
remain for a future discussion; this note does not authorize stopping the miner.
