# file: get_file_type_from_releases.py
#!/usr/bin/env python3
import sys
import argparse
import subprocess
import json
import fnmatch

DEFAULT_OWNER = "MaxCarlson"

def gh_json(args):
    cmd = ["gh"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running {' '.join(cmd)}: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON from {' '.join(cmd)}: {e}", file=sys.stderr)
        sys.exit(1)

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Find files in GitHub releases using gh CLI")
    parser.add_argument("--repo", "-R", help="Full repository path 'owner/repo', or repo name if --owner is omitted")
    parser.add_argument("--owner", "-o", help="GitHub owner (username or org)")
    parser.add_argument("--repo-name", "-n", help="Repository name (requires --owner)")
    parser.add_argument("--pattern", "-P", required=True, help="Glob pattern to match asset names")
    parser.add_argument("--limit", "-l", type=int, default=30, help="Number of latest releases to check")
    parser.add_argument("--releases", "-r", type=int, default=1, help="Number of releases with matches to display")
    parser.add_argument("--matches-per-release", "-m", type=int, default=1, help="Matches per release to display")
    return parser.parse_args(argv)

def determine_repo(repo_arg, owner_arg, repo_name_arg):
    if repo_arg:
        if "/" in repo_arg:
            return repo_arg
        else:
            return f"{DEFAULT_OWNER}/{repo_arg}"
    elif owner_arg and repo_name_arg:
        return f"{owner_arg}/{repo_name_arg}"
    else:
        print("Error: must specify --repo or both --owner and --repo-name", file=sys.stderr)
        sys.exit(1)

def main(argv=None):
    args = parse_args(argv)
    repo = determine_repo(args.repo, args.owner, args.repo_name)
    releases = gh_json(["release", "list", "--repo", repo, "--json", "tagName,publishedAt", "--limit", str(args.limit)])
    total_releases = len(releases)
    if total_releases == 0:
        print(f"No releases found for {repo}", file=sys.stderr)
        sys.exit(1)
    last_date = releases[0]["publishedAt"]
    print(f"Repository: {repo}")
    print(f"Total releases checked: {total_releases}; Latest release date: {last_date}")
    print(f"Pattern: {args.pattern}")
    print()
    found = 0
    for rel in releases:
        if found >= args.releases:
            break
        tag = rel["tagName"]
        published = rel["publishedAt"]
        details = gh_json(["release", "view", tag, "--repo", repo, "--json", "tagName,publishedAt,targetCommitish,assets"])
        assets = details.get("assets", [])
        matches = [a for a in assets if fnmatch.fnmatch(a.get("name", ""), args.pattern)]
        if matches:
            found += 1
            display = matches[: args.matches_per_release]
            print(f"{repo}")
            print(f"> Release: {tag} (published at {published}; target '{details.get('targetCommitish')}')")
            print(f"> Showing {len(display)}/{len(matches)} matches:")
            for asset in display:
                print(f"- {asset.get('name')} ({asset.get('browserDownloadUrl')})")
            print()
    if found == 0:
        print(f"No matches found for pattern '{args.pattern}' in the latest {total_releases} releases", file=sys.stderr)
        sys.exit(1)
    return 0

if __name__ == "__main__":
    sys.exit(main())

# ---------------------------------------
# file: tests/test_get_file_type_from_releases.py
import json
import pytest
import subprocess
from get_file_type_from_releases import main

class FakeProcess:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr

def test_single_match(monkeypatch, capsys):
    releases_list = [{"tagName": "v1.0", "publishedAt": "2021-01-01T00:00:00Z"}]
    assets = [
        {"name": "app64.exe", "browserDownloadUrl": "https://download/app64.exe"},
        {"name": "readme.txt", "browserDownloadUrl": "https://download/readme.txt"},
    ]
    view_details = {"tagName":"v1.0","publishedAt":"2021-01-01T00:00:00Z","targetCommitish":"main","assets":assets}
    def fake_run(cmd, capture_output, text):
        cmd_str = " ".join(cmd)
        if "release list" in cmd_str:
            return FakeProcess(stdout=json.dumps(releases_list))
        elif "release view" in cmd_str:
            return FakeProcess(stdout=json.dumps(view_details))
        return FakeProcess(stdout="", returncode=1, stderr="error")
    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = main(["--repo", "owner/repo", "--pattern", "*64.exe"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Total releases checked: 1; Latest release date: 2021-01-01T00:00:00Z" in captured.out
    assert "- app64.exe (https://download/app64.exe)" in captured.out

def test_no_match(monkeypatch):
    releases_list = [{"tagName": "v1.0", "publishedAt": "2021-01-01T00:00:00Z"}]
    view_details = {"tagName":"v1.0","publishedAt":"2021-01-01T00:00:00Z","targetCommitish":"main","assets":[]}
    def fake_run(cmd, capture_output, text):
        cmd_str = " ".join(cmd)
        if "release list" in cmd_str:
            return FakeProcess(stdout=json.dumps(releases_list))
        elif "release view" in cmd_str:
            return FakeProcess(stdout=json.dumps(view_details))
        return FakeProcess(stdout="", returncode=1, stderr="error")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as exc:
        main(["--repo", "owner/repo", "--pattern", "*.apk"])
    assert exc.value.code == 1

def test_multiple_matches_and_flags(monkeypatch, capsys):
    releases_list = [
        {"tagName": "v2.0", "publishedAt": "2022-02-02T00:00:00Z"},
        {"tagName": "v1.0", "publishedAt": "2021-01-01T00:00:00Z"}
    ]
    assets_v2 = [
        {"name": "app64.exe", "browserDownloadUrl": "url1"},
        {"name": "app32.exe", "browserDownloadUrl": "url2"},
        {"name": "app64_v2.exe", "browserDownloadUrl": "url3"},
    ]
    view_details_v2 = {"tagName":"v2.0","publishedAt":"2022-02-02T00:00:00Z","targetCommitish":"main","assets":assets_v2}
    assets_v1 = [
        {"name": "app64.exe", "browserDownloadUrl": "url4"},
    ]
    view_details_v1 = {"tagName":"v1.0","publishedAt":"2021-01-01T00:00:00Z","targetCommitish":"main","assets":assets_v1}
    def fake_run(cmd, capture_output, text):
        cmd_str = " ".join(cmd)
        if "release list" in cmd_str:
            return FakeProcess(stdout=json.dumps(releases_list))
        elif "release view v2.0" in cmd_str:
            return FakeProcess(stdout=json.dumps(view_details_v2))
        elif "release view v1.0" in cmd_str:
            return FakeProcess(stdout=json.dumps(view_details_v1))
        return FakeProcess(stdout="", returncode=1, stderr="error")
    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = main(["--repo", "owner/repo", "--pattern", "*64.exe", "--releases", "2", "--matches-per-release", "2"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Showing 2/2 matches" in captured.out
    assert "- app64.exe (url1)" in captured.out
    assert "- app64_v2.exe (url3)" in captured.out
    assert "- app64.exe (url4)" in captured.out
