"""Behavioral checks for the cross-repository source ownership guard."""
import unittest

from scripts_setup.source_ownership import check_changes


class OwnershipTests(unittest.TestCase):
    def test_transferred_and_shared_changes_are_rejected(self):
        errors = check_changes([("M", "modules/agent_memory/agent_memory/classify.py", "a", "b"), ("M", "modules/termdash/pyproject.toml", "a", "b")], [])
        self.assertEqual(len(errors), 2)
        self.assertIn("llm-agent-toolkit", errors[0])
        self.assertIn("shared-python-modules", errors[1])

    def test_unrelated_paths_are_allowed(self):
        self.assertEqual(check_changes([("M", "modules/runmux/pyproject.toml", "a", "b")], []), [])

    def test_exception_is_bound_to_exact_change_and_reason(self):
        change = [("D", "modules/agent_memory/a.py", "old", "0")]
        valid = [{"path": "modules/agent_memory/a.py", "action": "D", "before": "old", "after": "0", "reason": "Retire reconciled source"}]
        self.assertEqual(check_changes(change, valid), [])
        for key, value in [("action", "M"), ("reason", " "), ("before", "different"), ("after", "different"), ("path", "modules/agent_memory/b.py")]:
            self.assertTrue(check_changes(change, [{**valid[0], key: value}]))

    def test_retired_directory_reintroduction_is_rejected(self):
        self.assertTrue(check_changes([("A", "modules/agent_sync/new.py", "0", "new")], []))
        self.assertTrue(check_changes([("A", "modules/agent_sync", "0", "new")], []))


if __name__ == "__main__":
    unittest.main()
