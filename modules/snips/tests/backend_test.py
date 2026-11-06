from snips import backend


def test_existing_autohotkey_is_reused_without_invoking_an_installer(monkeypatch, tmp_path):
    executable = tmp_path / "AutoHotkey64.exe"
    monkeypatch.setattr(backend, "find_autohotkey", lambda: (executable, "2.0.30.0"))
    monkeypatch.setattr(
        backend, "_run_install", lambda command: (_ for _ in ()).throw(AssertionError("installer called"))
    )

    actual_path, version, message = backend.ensure_autohotkey(apply=True)

    assert actual_path == executable
    assert version == "2.0.30.0"
    assert "Found AutoHotkey" in message


def test_installer_falls_through_winget_to_scoop_before_official(monkeypatch, tmp_path):
    executable = tmp_path / "AutoHotkey64.exe"
    detections = iter([(None, None), (None, None), (executable, "2.0.31.0")])
    monkeypatch.setattr(backend, "find_autohotkey", lambda: next(detections))
    monkeypatch.setattr(backend, "is_windows", lambda: True)
    monkeypatch.setattr(backend.shutil, "which", lambda name: name if name in {"winget", "scoop"} else None)
    commands = []

    def install(command):
        commands.append(command)
        if command[0] == "winget":
            raise RuntimeError("WinGet unavailable")

    monkeypatch.setattr(backend, "_run_install", install)
    monkeypatch.setattr(
        backend, "_official_installer", lambda: (_ for _ in ()).throw(AssertionError("official installer called"))
    )

    actual_path, version, _ = backend.ensure_autohotkey(apply=True)

    assert actual_path == executable
    assert version == "2.0.31.0"
    assert [command[0] for command in commands] == ["winget", "scoop"]
    assert commands[1] == ["scoop", "install", "extras/autohotkey"]


def test_dry_run_reports_priority_without_running_installers(monkeypatch):
    monkeypatch.setattr(backend, "find_autohotkey", lambda: (None, None))
    monkeypatch.setattr(backend, "is_windows", lambda: True)
    monkeypatch.setattr(backend.shutil, "which", lambda name: name if name in {"winget", "scoop"} else None)

    executable, version, message = backend.ensure_autohotkey(apply=False)

    assert executable is None and version is None
    assert "WinGet (AutoHotkey.AutoHotkey), then Scoop Extras (autohotkey)" in message
    assert message.endswith("then the official AutoHotkey v2 installer")


def test_official_installer_uses_latest_stable_v2_and_silent_switch(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return (
                b'<a href="AutoHotkey_2.0.31_setup.exe">new</a>'
                b'<a href="AutoHotkey_2.0.9_setup.exe">old</a>'
                b'<a href="AutoHotkey_2.1.1_setup.exe">alpha</a>'
            )

    monkeypatch.setattr(backend.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    downloads = []
    monkeypatch.setattr(backend.urllib.request, "urlretrieve", lambda url, path: downloads.append(url))
    commands = []
    monkeypatch.setattr(backend, "_run_install", lambda command: commands.append(command))

    backend._official_installer()

    assert downloads and downloads[0].endswith("AutoHotkey_2.0.31_setup.exe")
    assert commands and commands[0][-1] == "/silent"


def test_existing_scoop_v2_installation_is_detected(monkeypatch, tmp_path):
    executable = tmp_path / "apps" / "autohotkey" / "current" / "v2" / "AutoHotkey64.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("SCOOP", str(tmp_path))
    monkeypatch.delenv("SCOOP_GLOBAL", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(backend.shutil, "which", lambda _name: None)
    monkeypatch.setattr(backend, "_version", lambda _path: "2.0.31.0")

    actual_path, version = backend.find_autohotkey()

    assert actual_path == executable.resolve()
    assert version == "2.0.31.0"
