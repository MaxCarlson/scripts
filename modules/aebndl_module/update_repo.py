import subprocess
import sys
import os

def run_command(command, cwd=None):
    print(f"\nExecuting: {command}")
    process = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    if process.stdout:
        print(process.stdout)
    if process.stderr:
        print(process.stderr, file=sys.stderr)
    if process.returncode != 0:
        print(f"Error: Command failed with exit code {process.returncode}", file=sys.stderr)
        sys.exit(process.returncode)
    return process

def confirm_action(prompt):
    response = input(f"{prompt} (y/n): ").lower()
    return response == 'y'

def update_repository():
    print("--- Starting Repository Update ---")

    # Ensure we are in the correct directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # 1. Fetch latest changes from upstream
    print("\nStep 1: Fetching latest changes from upstream...")
    run_command("git fetch upstream")

    # 2. Switch to main branch
    print("\nStep 2: Switching to main branch...")
    run_command("git checkout main")

    # 3. Pull/Merge upstream's main into your main
    print("\nStep 3: Pulling latest changes from upstream/main into your local main branch...")
    if confirm_action("Do you want to merge (y) or rebase (n) upstream/main into your main? (Rebase is cleaner but can be more complex if conflicts arise)"):
        run_command("git pull upstream main") # This is fetch + merge
    else:
        run_command("git pull --rebase upstream main") # This is fetch + rebase

    # Check for conflicts after merge/rebase
    status_output = run_command("git status --porcelain").stdout
    if status_output and "U" in status_output: # 'U' indicates unmerged paths
        print("\n!!! CONFLICTS DETECTED !!!")
        print("Please resolve the conflicts manually, then commit the changes.")
        print("After resolving, run 'git add .' and 'git commit'.")
        input("Press Enter after resolving conflicts and committing...")
        # Re-run status to ensure conflicts are resolved
        status_output = run_command("git status --porcelain").stdout
        if "U" in status_output:
            print("Conflicts still detected. Exiting. Please resolve manually.", file=sys.stderr)
            sys.exit(1)

    # 4. Push your updated main branch to your origin
    print("\nStep 4: Pushing updated main branch to your private GitHub repository (origin)...")
    run_command("git push origin main")

    # 5. Integrate upstream changes into your feature branch
    print("\nStep 5: Integrating changes into your feature branch (feature/tqdm-byte-metrics)...")
    if confirm_action("Do you want to update your feature branch 'feature/tqdm-byte-metrics' with the latest main?"):
        run_command("git checkout feature/tqdm-byte-metrics")
        print("Rebasing 'feature/tqdm-byte-metrics' onto main...")
        run_command("git rebase main")

        # Check for conflicts after rebase
        status_output = run_command("git status --porcelain").stdout
        if status_output and "U" in status_output:
            print("\n!!! CONFLICTS DETECTED DURING REBASE !!!")
            print("Please resolve the conflicts manually, then run 'git rebase --continue'.")
            print("If you want to abort, run 'git rebase --abort'.")
            input("Press Enter after resolving conflicts and continuing/aborting rebase...")
            # Re-run status to ensure conflicts are resolved
            status_output = run_command("git status --porcelain").stdout
            if "U" in status_output:
                print("Conflicts still detected. Exiting. Please resolve manually.", file=sys.stderr)
                sys.exit(1)

        # 6. Force push your rebased feature branch
        print("\nStep 6: Force pushing your rebased feature branch to origin.")
        print("WARNING: Force pushing rewrites history. Only do this if you are sure.")
        if confirm_action("Are you sure you want to force push 'feature/tqdm-byte-metrics'?"):
            run_command("git push origin feature/tqdm-byte-metrics --force")
        else:
            print("Force push skipped. Your remote feature branch is not updated.")
    else:
        print("Skipping feature branch update.")

    print("\n--- Repository Update Complete ---")

if __name__ == "__main__":
    update_repository()
