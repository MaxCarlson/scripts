"""Real-Git and CLI coverage for observed repository identity."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_continuity import dispatcher_cli
from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import _git_launch_context, _launch_preview


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _make_repo(path: Path, *, object_format: str | None = None) -> tuple[Path, str]:
    path.mkdir(parents=True)
    init_args = ["init", "--initial-branch=main"]
    if object_format:
        init_args.append(f"--object-format={object_format}")
    subprocess.run(["git", "-C", str(path), *init_args], check=True, capture_output=True, text=True)
    _git(path, "config", "user.name", "LLMD Test")
    _git(path, "config", "user.email", "llmd-test@example.invalid")
    if object_format:
        _git(path, "config", "core.longpaths", "true")
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "initial")
    return path, _git(path, "rev-parse", "--verify", "HEAD^{commit}")


def test_git_launch_context_matches_independent_queries_for_attached_and_detached_heads(tmp_path: Path) -> None:
    repo, expected_commit = _make_repo(tmp_path / "repo")
    expected_root = _git(repo, "rev-parse", "--path-format=absolute", "--show-toplevel")
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")

    attached = _git_launch_context(dispatcher, "local", str(repo))
    assert attached == {
        "git_repository": _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").removesuffix("/.git"),
        "git_worktree": expected_root,
        "git_branch": _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD"),
        "git_commit": expected_commit,
    }

    _git(repo, "checkout", "--detach", "HEAD")
    detached = _git_launch_context(dispatcher, "local", str(repo))
    assert detached["git_worktree"] == expected_root
    assert detached["git_branch"] is None
    assert detached["git_commit"] == _git(repo, "rev-parse", "--verify", "HEAD^{commit}")


def test_git_launch_context_distinguishes_linked_worktree_commit_and_root(tmp_path: Path) -> None:
    root, base_commit = _make_repo(tmp_path / "root")
    linked = tmp_path / "linked-worktree"
    _git(root, "worktree", "add", "-b", "linked", str(linked))
    (linked / "tracked.txt").write_text("linked change\n", encoding="utf-8")
    _git(linked, "add", "tracked.txt")
    _git(linked, "commit", "-m", "linked change")
    assert _git(root, "rev-parse", "HEAD") == base_commit
    expected_root = _git(root, "rev-parse", "--path-format=absolute", "--show-toplevel")
    expected_linked_worktree = _git(linked, "rev-parse", "--path-format=absolute", "--show-toplevel")

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    root_context = _git_launch_context(dispatcher, "local", str(root))
    linked_context = _git_launch_context(dispatcher, "local", str(linked))

    assert root_context["git_worktree"] == expected_root
    assert linked_context["git_worktree"] == expected_linked_worktree
    assert root_context["git_repository"] == linked_context["git_repository"]
    assert root_context["git_commit"] == base_commit
    assert linked_context["git_commit"] == _git(linked, "rev-parse", "--verify", "HEAD^{commit}")
    assert root_context["git_commit"] != linked_context["git_commit"]


def test_sha256_commit_oid(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    try:
        _, expected_commit = _make_repo(repo, object_format="sha256")
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"installed Git cannot initialize SHA-256 repositories: {exc.stderr}")
    assert _git(repo, "rev-parse", "--show-object-format=storage") == "sha256"
    assert len(expected_commit) == 64
    context = _git_launch_context(DispatcherService(home_dir=tmp_path / "registry"), "local", str(repo))
    assert context["git_commit"] == expected_commit


def test_unborn_repository_reports_branch_but_no_commit(tmp_path: Path) -> None:
    repo = tmp_path / "unborn"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "--initial-branch=planned"], check=True, capture_output=True)
    context = _git_launch_context(DispatcherService(home_dir=tmp_path / "registry"), "local", str(repo))
    assert context["git_worktree"] == _git(repo, "rev-parse", "--path-format=absolute", "--show-toplevel")
    assert context["git_branch"] == "planned"
    assert context["git_commit"] is None


@pytest.mark.parametrize("failure", [FileNotFoundError("git missing"), subprocess.TimeoutExpired(["git"], 3)])
def test_git_launch_context_fails_closed_on_missing_git_or_timeout(tmp_path: Path, monkeypatch, failure) -> None:
    monkeypatch.setattr(dispatcher_cli, "_resolve_environment", lambda *_a, **_k: SimpleNamespace(
        environment_id="local", runtime_kind="windows", distro=None,
    ))
    monkeypatch.setattr(dispatcher_cli, "detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr(dispatcher_cli.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(failure))
    result = _git_launch_context(DispatcherService(home_dir=tmp_path / "registry"), "local", str(tmp_path))
    assert result == {"git_repository": None, "git_worktree": None, "git_branch": None, "git_commit": None}


@pytest.mark.parametrize("failed_query", ["topology", "commit"])
def test_git_launch_context_does_not_infer_identity_after_command_failure(tmp_path: Path, monkeypatch, failed_query) -> None:
    monkeypatch.setattr(dispatcher_cli, "_resolve_environment", lambda *_a, **_k: SimpleNamespace(
        environment_id="local", runtime_kind="windows", distro=None,
    ))
    monkeypatch.setattr(dispatcher_cli, "detect_runtime_kind", lambda: "windows")

    def fake_run(argv, **kwargs):
        query = argv[3:]
        if "--show-toplevel" in query:
            if failed_query == "topology":
                return subprocess.CompletedProcess(argv, 128, "", "not a repository")
            return subprocess.CompletedProcess(argv, 0, "C:/repo\nC:/repo/.git\nC:/repo/.git\n", "")
        if "symbolic-ref" in query:
            return subprocess.CompletedProcess(argv, 0, "topic\n", "")
        if "--show-object-format=storage" in query:
            return subprocess.CompletedProcess(argv, 0, "sha1\n", "")
        if "--verify" in query:
            return subprocess.CompletedProcess(argv, 128, "", "missing HEAD")
        pytest.fail(f"unexpected Git query: {query}")

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    result = _git_launch_context(DispatcherService(home_dir=tmp_path / "registry"), "local", str(tmp_path))
    if failed_query == "topology":
        assert result == {"git_repository": None, "git_worktree": None, "git_branch": None, "git_commit": None}
    else:
        assert result == {
            "git_repository": "C:/repo", "git_worktree": "C:/repo", "git_branch": "topic", "git_commit": None,
        }


def test_wsl_git_context_observes_branch_commit_and_object_format_independently(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(dispatcher_cli, "_resolve_environment", lambda *_a, **_k: SimpleNamespace(
        environment_id="wsl:Ubuntu", runtime_kind="wsl", distro="Ubuntu",
    ))
    monkeypatch.setattr(dispatcher_cli, "detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr(dispatcher_cli.shutil, "which", lambda name: "C:/Windows/wsl.exe" if name == "wsl.exe" else None)

    def fake_run(argv, **kwargs):
        calls.append(argv)
        command = argv[argv.index("git") + 1:]
        if "--show-toplevel" in command:
            output = "/work/repo\n/work/repo/.git\n/work/repo/.git\n"
        elif "--show-object-format=storage" in command:
            output = "sha256\n"
        elif "symbolic-ref" in command:
            output = "main\n"
        elif "--verify" in command:
            output = "f" * 64 + "\n"
        else:
            pytest.fail(f"unexpected Git query: {command}")
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    context = _git_launch_context(DispatcherService(home_dir="unused"), "wsl:Ubuntu", "/work/repo with spaces")
    assert context == {
        "git_repository": "/work/repo", "git_worktree": "/work/repo",
        "git_branch": "main", "git_commit": "f" * 64,
    }
    assert len(calls) == 4
    assert all(call[:4] == ["C:/Windows/wsl.exe", "--distribution", "Ubuntu", "--exec"] for call in calls)
    assert all("/work/repo with spaces" in call for call in calls)


def test_cli_start_preview_reports_independent_commit_and_portable_context(tmp_path: Path, capsys) -> None:
    repo, expected_commit = _make_repo(tmp_path / "repo")
    args = [
        "-H", str(tmp_path / "registry"), "-j", "start", "-g", "Git-Preview", "-n", "smoke",
        "-p", "claude", "-C", str(repo), "-d",
    ]
    assert dispatcher_cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    preview = payload["launch_preview"]
    repositories = preview["portable_launch_context"]["repositories"]
    assert repositories[0]["commit"] == expected_commit
    assert repositories[0]["branch"] == "main"
    assert repositories[0]["worktree"] == _git(repo, "rev-parse", "--path-format=absolute", "--show-toplevel")


def test_provider_switch_preview_drops_malformed_historical_commit_without_rewriting_event(tmp_path: Path, monkeypatch) -> None:
    repo, expected_commit = _make_repo(tmp_path / "repo")
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register(gui="GUI", name="Agent", provider="codex", session_id="source-session", apply=True)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    source = {
        "schema_version": 1,
        "provider": "codex",
        "repositories": [{
            "root": str(repo), "worktree": str(repo), "branch": "main", "commit": "feature-name",
        }],
        "working_directory": str(repo),
        "authorized_directories": [],
        "runtime_identity": {"environment_id": slot["current"]["environment_id"], "runtime_kind": "windows"},
        "semantic_settings": {},
        "destination_preferences": {},
    }
    dispatcher.record_portable_launch_context(
        slot_id=slot["slot_id"], provider="codex", environment_id=slot["current"]["environment_id"],
        session_id="source-session", snapshot=source,
    )
    monkeypatch.setattr(dispatcher_cli, "detect_runtime_kind", lambda: "windows")

    preview = _launch_preview(
        dispatcher, "claude", "00000000-0000-4000-8000-000000000001",
        slot["current"]["environment_id"], None, [], source_slot_id=slot["slot_id"],
        expected_source=("codex", slot["current"]["environment_id"], "source-session"),
    )
    repository = preview["portable_launch_context"]["repositories"][0]
    assert "commit" not in repository
    assert any(item["key"] == "repository_commit" and item["status"] == "unsupported"
               for item in preview["portability_preview"])
    stored = dispatcher.get_portable_launch_context(
        slot_id=slot["slot_id"], provider="codex", environment_id=slot["current"]["environment_id"],
        session_id="source-session",
    )
    assert stored["repositories"][0]["commit"] == "feature-name"
    assert _git(repo, "rev-parse", "--verify", "HEAD^{commit}") == expected_commit
