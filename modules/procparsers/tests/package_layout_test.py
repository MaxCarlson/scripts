from pathlib import Path

import procparsers

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_package_uses_importable_src_layout():
    package_root = PROJECT_ROOT / "src" / "procparsers"

    assert (package_root / "__init__.py").is_file()
    assert Path(procparsers.__file__).resolve() == (
        package_root / "__init__.py"
    ).resolve()
