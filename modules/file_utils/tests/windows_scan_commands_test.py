from __future__ import annotations

import json

from file_utils import diskspace


class WinSys:
    def __init__(self):
        self.last_cmds = []
    def is_windows(self) -> bool: return True
    def is_linux(self) -> bool: return False
    def is_termux(self) -> bool: return False
    def is_wsl2(self) -> bool: return False
    def run_command(self, cmd: str, sudo: bool = False) -> str:
        self.last_cmds.append(cmd)
        # Provide synthetic JSON for largest/heaviest
        if "ConvertTo-Json" in cmd or "-EncodedCommand" in cmd:
            return json.dumps([{"FullName": "C:/big.bin", "SizeBytes": 1234567}])
        return ""


def test_windows_largest_uses_encodedcommand_and_parses():
    ws = WinSys()
    items = diskspace.scan_largest_files(ws, "C:/Users", top_n=1, min_size=None)
    assert any("-EncodedCommand" in c for c in ws.last_cmds)
    assert items and items[0].path.endswith("big.bin")


def test_windows_heaviest_dirs_uses_encodedcommand_and_parses():
    ws = WinSys()
    items = diskspace.scan_heaviest_dirs(ws, "C:/Users", top_n=1)
    assert any("-EncodedCommand" in c for c in ws.last_cmds)
