#!/usr/bin/env python3
"""
Cleanup script to remove TEST_ projects from production database.

This script finds and deletes all projects with names starting with "TEST_"
that were accidentally created by test runs.

Usage:
    python cleanup_test_projects.py --dry-run  # Preview what will be deleted
    python cleanup_test_projects.py            # Actually delete
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from knowledge_manager import project_ops, db


def cleanup_test_projects(dry_run: bool = True) -> None:
    """
    Find and delete all projects starting with TEST_.

    Args:
        dry_run: If True, only show what would be deleted
    """
    # Get all projects
    conn = db.get_db_connection()
    cursor = conn.cursor()

    # Find TEST_ projects
    cursor.execute("""
        SELECT id, name, status, created_at
        FROM projects
        WHERE name LIKE 'TEST_%'
        ORDER BY name
    """)

    test_projects = cursor.fetchall()

    if not test_projects:
        print("✓ No TEST_ projects found in database")
        return

    print(f"Found {len(test_projects)} TEST_ projects:\n")

    for proj_id, name, status, created_at in test_projects:
        print(f"  - {name} ({status}) - Created: {created_at[:19]}")
        print(f"    ID: {proj_id}")

    if dry_run:
        print(f"\n[DRY RUN] Would delete {len(test_projects)} projects")
        print("Run without --dry-run to actually delete")
        return

    # Confirm deletion
    print(f"\n⚠️  About to DELETE {len(test_projects)} projects!")
    response = input("Type 'DELETE' to confirm: ")

    if response != "DELETE":
        print("Cancelled.")
        return

    # Delete projects
    deleted_count = 0
    for proj_id, name, _, _ in test_projects:
        try:
            # This will cascade delete tasks, tags, notes, etc.
            cursor.execute("DELETE FROM projects WHERE id = %s", (proj_id,))
            conn.commit()
            print(f"  ✓ Deleted: {name}")
            deleted_count += 1
        except Exception as e:
            print(f"  ✗ Error deleting {name}: {e}")
            conn.rollback()

    print(f"\n✓ Deleted {deleted_count} / {len(test_projects)} projects")

    cursor.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Clean up TEST_ projects from database")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without actually deleting"
    )
    args = parser.parse_args()

    cleanup_test_projects(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
