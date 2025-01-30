#!/usr/bin/env python3
import unittest
import subprocess
import os
import shutil
import tempfile
import sys
from io import StringIO
from contextlib import contextmanager

# Assuming git_sync_improved.py is in the same directory or importable
import git_sync_improved

class TestGitSyncImproved(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.main_repo_path = os.path.join(self.temp_dir, "main_repo")
        self.submodule_repo_path = os.path.join(self.temp_dir, "submodule_repo")

        # Initialize main repository
        os.makedirs(self.main_repo_path)
        subprocess.run(["git", "init"], cwd=self.main_repo_path, check=True, capture_output=True)
        with open(os.path.join(self.main_repo_path, "main_file.txt"), "w") as f:
            f.write("Initial main repo file")
        subprocess.run(["git", "add", "main_file.txt"], cwd=self.main_repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit in main repo"], cwd=self.main_repo_path, check=True, capture_output=True)

        # Initialize submodule repository
        os.makedirs(self.submodule_repo_path)
        subprocess.run(["git", "init"], cwd=self.submodule_repo_path, check=True, capture_output=True)
        with open(os.path.join(self.submodule_repo_path, "submodule_file.txt"), "w") as f:
            f.write("Initial submodule file")
        subprocess.run(["git", "add", "submodule_file.txt"], cwd=self.submodule_repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit in submodule repo"], cwd=self.submodule_repo_path, check=True, capture_output=True)

        # Add submodule to main repo
        os.chdir(self.main_repo_path) # Change to main repo dir for submodule add
        subprocess.run(["git", "submodule", "add", self.submodule_repo_path, "submodule"], check=True, capture_output=True)
        os.chdir(self.temp_dir) # Change back to temp dir

        # Set script path (assuming it's in the same directory as test script)
        self.script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "git_sync_improved.py"))
        if not os.path.exists(self.script_path):
            raise FileNotFoundError(f"Script not found at: {self.script_path}. Ensure git_sync_improved.py is in the same directory.")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @contextmanager
    def captured_output(self):
        new_out, new_err = StringIO(), StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = new_out, new_err
            yield sys.stdout, sys.stderr
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def run_script(self, *args, input_str=None, cwd=None):
        command = [sys.executable, self.script_path] + list(args)
        process = subprocess.Popen(
            command,
            cwd=cwd if cwd else self.main_repo_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=input_str)
        return stdout, stderr, process.returncode

    def assertGitStatusClean(self, repo_path):
        status_output = subprocess.run(["git", "status", "--short"], cwd=repo_path, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(status_output, "", "Git status should be clean")

    def assertGitStatusChanges(self, repo_path):
        status_output = subprocess.run(["git", "status", "--short"], cwd=repo_path, capture_output=True, text=True, check=True).stdout.strip()
        self.assertNotEqual(status_output, "", "Git status should have changes")

    def test_basic_workflow_no_changes(self):
        stdout, stderr, returncode = self.run_script()
        self.assertEqual(returncode, 0)
        self.assertIn("No changes detected. Running git pull...", stdout)
        self.assertGitStatusClean(self.main_repo_path)
        self.assertGitStatusClean(os.path.join(self.main_repo_path, "submodule"))

    def test_basic_workflow_with_changes(self):
        with open(os.path.join(self.main_repo_path, "main_file.txt"), "a") as f:
            f.write("\nAdded line to main file")
        stdout, stderr, returncode = self.run_script(input_str="y\nTest commit message\n")
        self.assertEqual(returncode, 0)
        self.assertIn("Committing changes", stdout)
        self.assertIn("Pushing changes", stdout) # Assuming push will happen, might need mock remote for proper test
        self.assertGitStatusClean(self.main_repo_path)
        self.assertGitStatusClean(os.path.join(self.main_repo_path, "submodule"))

    def test_force_flag(self):
        with open(os.path.join(self.main_repo_path, "main_file.txt"), "a") as f:
            f.write("\nAdded line for force test")
        stdout, stderr, returncode = self.run_script("-f", input_str="Test commit message\n") # Input still needed for commit message
        self.assertEqual(returncode, 0)
        self.assertIn("Committing changes", stdout)
        self.assertIn("Pushing changes", stdout)
        self.assertGitStatusClean(self.main_repo_path)
        self.assertGitStatusClean(os.path.join(self.main_repo_path, "submodule"))

    def test_skip_commit_option(self):
        with open(os.path.join(self.main_repo_path, "main_file.txt"), "a") as f:
            f.write("\nAdded line for skip commit test")
        stdout, stderr, returncode = self.run_script(input_str="s\n")
        self.assertEqual(returncode, 0)
        self.assertIn("Skipping commit, proceeding to git pull.", stdout)
        self.assertNotIn("Committing changes", stdout)
        self.assertIn("Pulling latest changes", stdout)
        self.assertGitStatusChanges(self.main_repo_path) # Changes should be staged but not committed
        subprocess.run(["git", "reset", "HEAD", "main_file.txt"], cwd=self.main_repo_path, check=True, capture_output=True) # Unstage for cleanup
        self.assertGitStatusClean(self.main_repo_path)

    def test_add_pattern_flag(self):
        os.makedirs(os.path.join(self.main_repo_path, "test_dir"))
        with open(os.path.join(self.main_repo_path, "test_dir", "test_file.special"), "w") as f:
            f.write("Special file")
        with open(os.path.join(self.main_repo_path, "main_file.txt"), "a") as f:
            f.write("\nAdded line for add pattern test")

        stdout, stderr, returncode = self.run_script("-a", "*.txt", input_str="y\nTest add pattern\n")
        self.assertEqual(returncode, 0)
        self.assertIn("Adding files: *.txt", stdout)
        self.assertIn("Committing changes", stdout)
        self.assertGitStatusClean(self.main_repo_path)
        status_output = subprocess.run(["git", "status", "--short"], cwd=self.main_repo_path, capture_output=True, text=True, check=True).stdout.strip()
        self.assertNotIn("test_file.special", status_output) # special file should not be added

    def test_submodule_processing(self):
        with open(os.path.join(self.submodule_repo_path, "submodule_file.txt"), "a") as f:
            f.write("\nChange in submodule")
        stdout, stderr, returncode = self.run_script(input_str="y\nTest submodule commit\n")
        self.assertEqual(returncode, 0)
        self.assertIn("Processing submodule: submodule", stdout)
        self.assertIn("Committing changes", stdout) # Should commit in both main and submodule
        self.assertGitStatusClean(self.main_repo_path)
        self.assertGitStatusClean(os.path.join(self.main_repo_path, "submodule"))

    def test_selective_submodule_processing(self):
        # Add a second submodule for testing selective processing
        second_submodule_repo_path = os.path.join(self.temp_dir, "second_submodule_repo")
        os.makedirs(second_submodule_repo_path)
        subprocess.run(["git", "init"], cwd=second_submodule_repo_path, check=True, capture_output=True)
        with open(os.path.join(second_submodule_repo_path, "second_submodule_file.txt"), "w") as f:
            f.write("Initial second submodule file")
        subprocess.run(["git", "add", "second_submodule_file.txt"], cwd=second_submodule_repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit in second submodule repo"], cwd=second_submodule_repo_path, check=True, capture_output=True)
        os.chdir(self.main_repo_path)
        subprocess.run(["git", "submodule", "add", second_submodule_repo_path, "submodule2"], check=True, capture_output=True)
        os.chdir(self.temp_dir)

        submodule1_path = os.path.join(self.main_repo_path, "submodule")
        submodule2_path = os.path.join(self.main_repo_path, "submodule2")

        with open(os.path.join(submodule1_path, "submodule_file.txt"), "a") as f:
            f.write("\nChange in submodule1")
        with open(os.path.join(submodule2_path, "second_submodule_file.txt"), "a") as f:
            f.write("\nChange in submodule2")

        stdout, stderr, returncode = self.run_script("--submodules", "submodule", input_str="y\nSelective submodule commit\n")
        self.assertEqual(returncode, 0)
        self.assertIn("Processing submodule: submodule", stdout)
        self.assertNotIn("Entering submodule: submodule2", stdout) # Should skip submodule2
        self.assertIn("Committing changes", stdout)
        self.assertGitStatusClean(self.main_repo_path)
        self.assertGitStatusClean(submodule1_path)
        self.assertGitStatusChanges(submodule2_path) # submodule2 should still have changes

    def test_config_file_load_and_generate(self):
        config_file_path = os.path.join(self.temp_dir, ".test_git_sync.conf")
        # Generate config file with force=true and verbose=true
        stdout_gen, stderr_gen, returncode_gen = self.run_script("--generate-config", "--config", config_file_path, "-f", "-v")
        self.assertEqual(returncode_gen, 0)
        self.assertTrue(os.path.exists(config_file_path))

        # Run script using config file
        with open(os.path.join(self.main_repo_path, "main_file.txt"), "a") as f:
            f.write("\nChange for config test")
        stdout_config, stderr_config, returncode_config = self.run_script("--config", config_file_path, input_str="Test commit from config\n")
        self.assertEqual(returncode_config, 0)
        self.assertIn("Committing changes", stdout_config)
        self.assertIn("[INFO] Pushing changes", stdout_config) # Verbose should be enabled from config
        self.assertGitStatusClean(self.main_repo_path)

    def test_dry_run_mode(self):
        with open(os.path.join(self.main_repo_path, "main_file.txt"), "a") as f:
            f.write("\nChange for dry run")
        stdout, stderr, returncode = self.run_script("--dry-run", input_str="y\nDry run commit message\n")
        self.assertEqual(returncode, 0)
        self.assertIn("[DRY-RUN] Simulating command: git add .", stdout)
        self.assertIn("[DRY-RUN] Simulating command: git commit -m", stdout)
        self.assertIn("[DRY-RUN] Simulating command: git pull", stdout)
        self.assertIn("[DRY-RUN] Simulating command: git push", stdout)
        self.assertGitStatusChanges(self.main_repo_path) # No actual commit should happen

    def test_commit_template_simple(self):
        with captured_output() as (stdout_capture, stderr_capture):
            stdout, stderr, returncode = self.run_script("--commit-template", "simple", input_str="y\nShort description input\nLong description input\n")
        self.assertEqual(returncode, 0)
        self.assertIn("Commit Message Preview", stdout_capture.getvalue())
        self.assertIn("feat: Short description input", stdout_capture.getvalue())
        self.assertIn("Long description input", stdout_capture.getvalue())
        self.assertIn("Committing changes", stdout)
        commit_message_log = subprocess.run(["git", "log", "-n", "1", "--pretty=format:%B"], cwd=self.main_repo_path, capture_output=True, text=True, check=True).stdout.strip()
        self.assertIn("Short description input", commit_message_log)
        self.assertIn("Long description input", commit_message_log)
        self.assertGitStatusClean(self.main_repo_path)

    def test_create_branch(self):
        test_branch_name = "test-new-branch"
        stdout, stderr, returncode = self.run_script("--create-branch", test_branch_name, input_str="y\nCommit on new branch\n")
        self.assertEqual(returncode, 0)
        self.assertIn(f"Branch '{test_branch_name}' does not exist locally. Creating...", stdout)
        self.assertIn(f"Checking out new branch '{test_branch_name}'", stdout) # Check if your script logs branch checkout
        current_branch = subprocess.run(["git", "branch", "--show-current"], cwd=self.main_repo_path, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(current_branch, test_branch_name)
        self.assertGitStatusClean(self.main_repo_path)

    def test_branch_specification(self):
        test_branch_name = "feature-branch"
        subprocess.run(["git", "checkout", "-b", test_branch_name], cwd=self.main_repo_path, check=True, capture_output=True) # Create test branch
        subprocess.run(["git", "checkout", "main"], cwd=self.main_repo_path, check=True, capture_output=True) # Switch back to main

        stdout, stderr, returncode = self.run_script("--branch", test_branch_name, input_str="y\nCommit to feature branch\n")
        self.assertEqual(returncode, 0)
        self.assertIn(f"Pulling latest changes", stdout) # Should pull and push to feature-branch
        self.assertIn(f"Pushing changes", stdout)
        self.assertGitStatusClean(self.main_repo_path)
        current_branch_after_run = subprocess.run(["git", "branch", "--show-current"], cwd=self.main_repo_path, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(current_branch_after_run, "main") # Should remain on main branch after script finishes

    def test_submodule_branches_specification(self):
        test_submodule_branch_name = "submodule-feature-branch"
        subprocess.run(["git", "checkout", "-b", test_submodule_branch_name], cwd=self.submodule_repo_path, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=self.submodule_repo_path, check=True, capture_output=True)

        with open(os.path.join(self.submodule_repo_path, "submodule_file.txt"), "a") as f:
            f.write("\nChange in submodule for branch test")

        stdout, stderr, returncode = self.run_script("--submodule-branches", test_submodule_branch_name, input_str="y\nCommit to submodule branch\n")
        self.assertEqual(returncode, 0)
        self.assertIn("Processing submodule: submodule", stdout)
        self.assertIn("Pulling latest changes", stdout) # Should pull and push to submodule-feature-branch in submodule
        self.assertIn("Pushing changes", stdout)
        self.assertGitStatusClean(self.main_repo_path)
        submodule_current_branch = subprocess.run(["git", "branch", "--show-current"], cwd=os.path.join(self.main_repo_path, "submodule"), capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(submodule_current_branch, "main") # Should remain on main branch in submodule after script finishes

    def test_argument_count_warnings(self):
        with captured_output() as (stdout_capture, stderr_capture):
            stdout, stderr, returncode = self.run_script("--submodule-add-patterns", "*.txt", "--submodules", "submodule,submodule2") # Assuming submodule2 exists from previous test
        self.assertIn("Number of submodule add patterns (1) is less than the number of submodules (2)", stderr_capture.getvalue())
        with captured_output() as (stdout_capture2, stderr_capture2):
             stdout2, stderr2, returncode2 = self.run_script("--submodule-add-patterns", "*.txt,*.js,*.css,*.html", "--submodules", "submodule")
        self.assertIn("Number of submodule add patterns (4) exceeds the number of repositories (main + submodules = 2)", stderr_capture2.getvalue())

if __name__ == '__main__':
    unittest.main()
