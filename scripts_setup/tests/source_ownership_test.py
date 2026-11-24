"""Behavioral checks for source ownership, including real Git repositories."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts_setup.source_ownership import check_changes

ROOT = Path(__file__).resolve().parents[2]

def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

class OwnershipTests(unittest.TestCase):
    def test_owner_changes_and_exact_exceptions(self):
        changes = [("M", "modules/agent_memory/a.py", "100644", "100644", "old", "new"),
                   ("M", "modules/termdash/a.py", "100644", "100644", "old", "new")]
        errors = check_changes(changes, [])
        self.assertEqual(len(errors), 2)
        self.assertIn("llm-agent-toolkit", errors[0])
        self.assertIn("shared-python-modules", errors[1])
        exc = [{"path":"modules/agent_memory/a.py","action":"M","before_mode":"100644","after_mode":"100644","before":"old","after":"new","reason":"API reconciliation"}]
        self.assertEqual(len(check_changes(changes, exc)), 1)

    def test_directory_retirement_exception_is_deletion_only(self):
        exc = [{"type":"retirement","path":"modules/agent_sync","reason":"Reviewed source retirement"}]
        self.assertEqual(check_changes([("D","modules/agent_sync/a.py","100644","000000","blob","0")], exc), [])
        self.assertTrue(check_changes([("A","modules/agent_sync/a.py","000000","100644","0","blob")], exc))

    def test_git_integration_catches_additions_gitlinks_and_mode_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=Path(temporary)
            git(repo,"init","-q")
            git(repo,"config","user.email","test@example.invalid")
            git(repo,"config","user.name","Test")
            (repo/"scripts_setup").mkdir(); (repo/"modules/agent_sync").mkdir(parents=True)
            (repo/"scripts_setup/transferred_modules.py").write_text('TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION = {"agent_sync": "agent-sync"}\n')
            (repo/"scripts_setup/shared_packages.py").write_text('SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION = {}\n')
            (repo/".github").mkdir(); (repo/".github/source-ownership-exceptions.json").write_text("[]")
            f=repo/"modules/agent_sync/old.py"; f.write_text("old\n")
            git(repo,"add","."); git(repo,"commit","-qm","base"); base=git(repo,"rev-parse","HEAD")
            f.unlink(); f.write_text("new\n"); git(repo,"add","."); git(repo,"commit","-qm","replace")
            raw=subprocess.check_output(["git","diff","--raw","--no-abbrev","-z","--no-renames",base,"HEAD","--"],cwd=repo)
            fields=raw.decode().split("\0")
            changes=[(fields[i].split()[4],fields[i+1],*fields[i].split()[1:5]) for i in range(0,len(fields)-1,2)]
            self.assertTrue(check_changes(changes,[],toolkit={"agent_sync"},shared=set()))
            self.assertTrue(any(c[2] != c[3] for c in changes))

if __name__ == "__main__": unittest.main()
