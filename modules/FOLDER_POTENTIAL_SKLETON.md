xinstall/
ÃÄÄ pyproject.toml
ÃÄÄ README.md
ÃÄÄ CHANGELOG.md
ÃÄÄ .gitignore
ÃÄÄ src/
³   ÀÄÄ xinstall/
³       ÃÄÄ __init__.py
³       ÃÄÄ __main__.py
³       ÃÄÄ cli.py
³       ÃÄÄ platform.py
³       ÃÄÄ config/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ paths.py
³       ³   ÃÄÄ load_manifest.py
³       ³   ÀÄÄ schema.py
³       ÃÄÄ inventory/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ state_store.py
³       ³   ÃÄÄ detect_installed.py
³       ³   ÀÄÄ receipts.py
³       ÃÄÄ installers/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ base.py
³       ³   ÃÄÄ plan.py
³       ³   ÃÄÄ windows/
³       ³   ³   ÃÄÄ __init__.py
³       ³   ³   ÃÄÄ winget.py
³       ³   ³   ÃÄÄ choco.py
³       ³   ³   ÀÄÄ scoop.py
³       ³   ÃÄÄ linux/
³       ³   ³   ÃÄÄ __init__.py
³       ³   ³   ÃÄÄ apt.py
³       ³   ³   ÃÄÄ dnf.py
³       ³   ³   ÃÄÄ pacman.py
³       ³   ³   ÀÄÄ brew.py
³       ³   ÃÄÄ termux/
³       ³   ³   ÃÄÄ __init__.py
³       ³   ³   ÀÄÄ pkg.py
³       ³   ÀÄÄ python_tools/
³       ³       ÃÄÄ __init__.py
³       ³       ÃÄÄ pipx.py
³       ³       ÃÄÄ uv.py
³       ³       ÀÄÄ pip_user.py
³       ÃÄÄ runners/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ exec.py
³       ³   ÀÄÄ which.py
³       ÀÄÄ util/
³           ÃÄÄ __init__.py
³           ÃÄÄ logging.py
³           ÃÄÄ text.py
³           ÀÄÄ errors.py
ÃÄÄ docs/
³   ÃÄÄ manifest/
³   ³   ÃÄÄ tools.yaml
³   ³   ÃÄÄ tools.schema.json
³   ³   ÀÄÄ examples/
³   ³       ÃÄÄ minimal.yaml
³   ³       ÀÄÄ full.yaml
³   ÃÄÄ guide/
³   ³   ÃÄÄ INSTALL.md
³   ³   ÃÄÄ MANIFEST.md
³   ³   ÃÄÄ PACKAGE_MANAGERS.md
³   ³   ÀÄÄ TROUBLESHOOTING.md
³   ÀÄÄ state/
³       ÃÄÄ README.md
³       ÃÄÄ installed/
³       ³   ÀÄÄ .gitkeep
³       ÀÄÄ receipts/
³           ÀÄÄ .gitkeep
ÃÄÄ scripts/
³   ÃÄÄ bootstrap_install.sh
³   ÀÄÄ bootstrap_install.ps1
ÀÄÄ tests/
    ÃÄÄ test_cli_check.py
    ÃÄÄ test_manifest_loading.py
    ÃÄÄ test_fallback_planning.py
    ÃÄÄ test_inventory_state_store.py
    ÀÄÄ fixtures/
        ÀÄÄ manifests/
            ÃÄÄ minimal.yaml
            ÀÄÄ full.yaml
