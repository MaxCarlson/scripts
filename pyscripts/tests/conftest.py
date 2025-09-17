# tests/conftest.py
import pytest
import subprocess
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_atuin_history(monkeypatch):
    class MockAtuinHistory:
        def __init__(self):
            self._history_output = []
            self._history_exception = None
            self._mocked_commands = {}
            self.main_subprocess_mock = MagicMock(spec=subprocess.run) # Mock for subprocess.run in main script

            # Patch subprocess.run globally for the main script
            monkeypatch.setattr("run_history_process.subprocess.run", self.main_subprocess_mock)
            monkeypatch.setattr("run_history_process.subprocess.CalledProcessError", subprocess.CalledProcessError)
            monkeypatch.setattr("run_history_process.subprocess.check_output", MagicMock())


        def set_history_output(self, output_list):
            self._history_output = output_list
            self._history_exception = None
            self.main_subprocess_mock.reset_mock() # Reset calls when history output changes

            # Mock the specific atuin history list command
            def fake_atuin_run(cmd, **kwargs):
                print(f"DEBUG: fake_atuin_run received cmd: {cmd}", file=sys.stderr)
                if cmd[0] == "atuin" and "history" in cmd and "list" in cmd:
                    if self._history_exception:
                        raise self._history_exception
                    return MagicMock(stdout="\n".join(self._history_output) + ("" if not self._history_output else "\n"), stderr="", returncode=0)
                
                # Fallback for other commands if not specifically mocked
                if cmd[0] in self._mocked_commands:
                    mock_return = self._mocked_commands[cmd[0]]
                    if isinstance(mock_return, Exception):
                        raise mock_return
                    return MagicMock(stdout=mock_return[0], stderr=mock_return[1], returncode=mock_return[2])
                
                # Default behavior for unmocked commands
                return MagicMock(stdout="", stderr="", returncode=0)

            self.main_subprocess_mock.side_effect = fake_atuin_run


        def set_history_exception(self, exception):
            self._history_exception = exception
            self._history_output = []
            self.main_subprocess_mock.reset_mock() # Reset calls when history output changes

            def fake_atuin_run_exception(cmd, **kwargs):
                if cmd == ["atuin", "history", "list"]:
                    raise self._history_exception
                return MagicMock(stdout="", stderr="", returncode=0) # Default for other commands
            
            self.main_subprocess_mock.side_effect = fake_atuin_run_exception


        def mock_specific_command_execution(self, command_list, returncode=0, stdout="", stderr=""):
            # This mocks the behavior of subprocess.run when the main script executes a command
            # It needs to be careful not to interfere with the atuin history list mock
            def custom_side_effect(cmd, **kwargs):
                if cmd == ["atuin", "history", "list"]:
                    if self._history_exception:
                        raise self._history_exception
                    return MagicMock(stdout="\n".join(self._history_output), stderr="", returncode=0)
                
                if cmd == command_list:
                    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)
                
                # Default for unmocked commands
                return MagicMock(stdout="", stderr="", returncode=0)

            self.main_subprocess_mock.side_effect = custom_side_effect


        def mock_specific_command_to_raise(self, command_list, exception):
            def custom_side_effect(cmd, **kwargs):
                if cmd == ["atuin", "history", "list"]:
                    if self._history_exception:
                        raise self._history_exception
                    return MagicMock(stdout="\n".join(self._history_output), stderr="", returncode=0)
                
                if cmd == command_list:
                    raise exception
                
                # Default for unmocked commands
                return MagicMock(stdout="", stderr="", returncode=0)

            self.main_subprocess_mock.side_effect = custom_side_effect


    return MockAtuinHistory()