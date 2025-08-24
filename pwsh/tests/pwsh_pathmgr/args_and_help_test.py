import re
import platform

LONGS = {
    "-i": "--install",
    "-u": "--uninstall",
    "-p": "--print",
    "-c": "--check",
    "-s": "--shell",
    "-t": "--target-path",
    "-f": "--profile-file",
    "-n": "--dry-run",
    "-T": "--temporary",
}

def test_help_lists_required_options(cli):
    p = cli(["--help"])
    assert p.returncode == 0, p.stderr
    out = p.stdout or p.stderr
    # all long options present
    for short, long in LONGS.items():
        assert long in out
        assert re.search(rf"\s{re.escape(short)}[, ]\s*{re.escape(long)}", out)

def test_argument_style_enforced(cli):
    # Things that must fail style-wise:
    bad_opts = ["-install", "--I", "--Install", "---install", "-long-name"]
    for bad in bad_opts:
        p = cli([bad])
        assert p.returncode != 0
        assert "invalid" in (p.stderr.lower() or p.stdout.lower())

def test_requires_single_dash_single_letter_for_shorts(cli):
    # double letter short should fail
    p = cli(["-ii"])
    assert p.returncode != 0

def test_unknown_option_rejected(cli):
    p = cli(["-x"])
    assert p.returncode != 0
    assert "unknown option" in (p.stderr.lower() or p.stdout.lower())

def test_help_examples_include_scripts_bin(cli):
    p = cli(["--help"])
    text = p.stdout + p.stderr
    assert "scripts/bin" in text
