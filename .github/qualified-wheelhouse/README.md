# Qualified shared-package wheelhouse

These five wheel files are CI-only staging artifacts for the scripts shared-package integration. They were copied from the locally qualified `shared-python-modules` artifacts associated with source checkpoint `ff134131d8615e9c68111551ccf1cdf972a66ef4` and verified against that repository's `dist/SHA256SUMS.txt`.

`SHA256SUMS.txt` pins the exact wheel bytes. The manual Ubuntu qualification workflow verifies each hash and each wheel's distribution name/version before installing them through `PIP_FIND_LINKS`. The wheels are not canonical package source and are not used by normal scripts setup outside the qualification workflow.

After the shared distributions are available through the approved package channel, replace this fixture with a separately reviewed installation test against the published versions. Do not rewrite or refresh these wheel files in place; a new artifact set requires a new checksum review.
