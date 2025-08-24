import platform, pytest
from pathlib import Path

@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only")
def test_powershell_profile_is_modified(repo_root, fake_home, cli):
    profile = fake_home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    p = cli(["-i","-s","powershell","-t",str(repo_root/"scripts"/"bin")])
    assert p.returncode == 0
    txt = profile.read_text()
    assert "$env:Path" in txt and "pathctl" in txt
