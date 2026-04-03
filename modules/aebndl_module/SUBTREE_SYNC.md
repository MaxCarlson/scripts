# aebndl Upstream Sync

`modules/aebndl_module` is tracked as a normal folder in the main `scripts` repository.
It is not a standalone Git repo anymore.

Upstream changes from the original repository are pulled into the parent repo with `git subtree`.

## Upstream Remote

The parent repo should have this remote configured:

```powershell
git remote add aebndl-upstream https://github.com/estellaarrieta/aebn-vod-downloader.git
```

If the remote already exists, verify it with:

```powershell
git remote get-url aebndl-upstream
```

## Fetch Upstream

From the root of the `scripts` repo:

```powershell
git fetch aebndl-upstream
```

## Pull Upstream Changes Into modules/aebndl_module

From the root of the `scripts` repo:

```powershell
git subtree pull --prefix=modules/aebndl_module aebndl-upstream main --squash
```

Notes:

- Run this from the parent `scripts` repo, not from inside `modules/aebndl_module`.
- `--prefix=modules/aebndl_module` limits the import to this folder.
- `--squash` keeps the parent repo history cleaner by recording the upstream update as one commit.

## Recommended Update Flow

```powershell
git checkout main
git pull
git fetch aebndl-upstream
git subtree pull --prefix=modules/aebndl_module aebndl-upstream main --squash
```

Then review and test the imported changes, for example:

```powershell
pytest tests\ -v
```

Commit the subtree update in the parent repo:

```powershell
git commit -m "Sync aebndl_module from upstream"
```

## Common Mistakes

- Do not run `git pull` inside `modules/aebndl_module`.
- Do not recreate `modules/aebndl_module/.git`.
- Do not convert this folder back into a submodule unless the repo structure is intentionally changing again.
