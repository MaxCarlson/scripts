from pathlib import Path


def test_gpu_requirements_keep_pillow_compatible_with_installed_private_modules():
    requirements = Path(__file__).resolve().parents[1] / "requirements-gpu.txt"
    pillow_requirement = next(
        line.strip().lower()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip().lower().startswith("pillow")
    )

    assert "<13" in pillow_requirement
