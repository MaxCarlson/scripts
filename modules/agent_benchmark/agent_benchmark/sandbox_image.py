"""Single source of truth for the LiveCodeBench verifier sandbox image identity.

The catalog (resource declaration), the setup manager (install/status/verify) and the
container verifier (execution) all import these constants so that setup verifies exactly
the image the verifier will run. The reference is pinned to an immutable multi-arch
manifest-list digest (resolved from the Docker Hub registry for ``library/python:3.11-slim``).
"""

from __future__ import annotations

LCB_SANDBOX_RESOURCE_NAME = "lcb-sandbox-verifier"
LCB_SANDBOX_IMAGE_REPOSITORY = "python:3.11-slim"
LCB_SANDBOX_IMAGE_DIGEST = "sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535"
LCB_SANDBOX_IMAGE_REF = f"{LCB_SANDBOX_IMAGE_REPOSITORY}@{LCB_SANDBOX_IMAGE_DIGEST}"
