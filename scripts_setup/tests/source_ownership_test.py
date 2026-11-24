"""Git-level tests for the source ownership guard production CLI."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts_setup.source_ownership import check_changes

SCRIPT = Path(__file__).resolve().parents[1] / "source_ownership.py"

def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

class OwnershipTests(unittest.TestCase):
    def test_exact_object_mode_gitlink_and_retirement_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=Path(temporary)
            git(repo,"init","-q"); git(repo,"config","user.email","test@example.invalid"); git(repo,"config","user.name","Test")
            for folder in ("scripts_setup", ".github", "modules/agent_sync"):
                (repo/folder).mkdir(parents=True,exist_ok=True)
            (repo/"scripts_setup/transferred_modules.py").write_text('TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION: dict[str, str] = {"agent_sync": "agent-sync"}\n')
            (repo/"scripts_setup/shared_packages.py").write_text('SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION: dict[str, str] = {}\n')
            policy=repo/".github/source-ownership-exceptions.json"; policy.write_text("[]\n")
            source=repo/"modules/agent_sync/file.py"; source.write_text("before\n"); source.chmod(0o644)
            git(repo,"add","."); git(repo,"commit","-qm","base"); base=git(repo,"rev-parse","HEAD")
            source.write_text("after\n"); source.chmod(0o755); git(repo,"add","."); git(repo,"update-index","--chmod=+x","modules/agent_sync/file.py"); git(repo,"commit","-qm","mode and content")
            raw=subprocess.check_output(["git","diff","--raw","--no-abbrev","-z","--no-renames",base,"HEAD","--"],cwd=repo).decode().split("\0")
            meta=raw[0].split(); self.assertEqual(meta[0],":100644"); self.assertEqual(meta[1],"100755")
            self.assertEqual(len(meta[2]),40); self.assertEqual(len(meta[3]),40); self.assertEqual(meta[4],"M")
            run=subprocess.run([os.fspath(__import__('sys').executable),os.fspath(SCRIPT),"--base",base,"--end","HEAD"],cwd=repo,capture_output=True,text=True,env={**os.environ,"PYTHONPATH":str(SCRIPT.parents[1])})
            self.assertEqual(run.returncode,1,run.stdout+run.stderr)
            policy.write_text(json.dumps([{"type":"retirement","path":"modules/agent_sync","reason":"approved source retirement"}]))
            git(repo,"add",str(policy.relative_to(repo))); git(repo,"commit","-qm","record policy")
            source.unlink(); git(repo,"add","-u"); git(repo,"update-index","--add","--cacheinfo","160000","0123456789012345678901234567890123456789","modules/agent_sync"); git(repo,"commit","-qm","retire with gitlink")
            run=subprocess.run([os.fspath(__import__('sys').executable),os.fspath(SCRIPT),"--base",base,"--end","HEAD"],cwd=repo,capture_output=True,text=True,env={**os.environ,"PYTHONPATH":str(SCRIPT.parents[1])})
            self.assertEqual(run.returncode,1,run.stdout+run.stderr)
            git(repo,"update-index","--force-remove","modules/agent_sync"); git(repo,"commit","-qm","complete retirement")
            run=subprocess.run([os.fspath(__import__('sys').executable),os.fspath(SCRIPT),"--base",base,"--end","HEAD"],cwd=repo,capture_output=True,text=True,env={**os.environ,"PYTHONPATH":str(SCRIPT.parents[1])})
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)

if __name__ == "__main__":
    unittest.main()
