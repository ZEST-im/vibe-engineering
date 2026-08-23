"""Display-name canonicalization (users.json alias table).

Regression guard for the whack-a-mole loop: git config user.name differs from the
kanban handle, so every newly created task re-introduced the non-canonical form and
had to be normalized by hand. Fixtures use placeholder handles on purpose — this is
a public repo, so real names belong only in the machine-local users.json.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def load_server(users_config=None):
    """Load a fresh server module with USERS_CONFIG_PATH pointed at a temp file."""
    prev = os.environ.get("VIBE_HARNESS_USERS_CONFIG")
    if users_config is None:
        os.environ.pop("VIBE_HARNESS_USERS_CONFIG", None)
    else:
        os.environ["VIBE_HARNESS_USERS_CONFIG"] = users_config
    try:
        spec = importlib.util.spec_from_file_location(
            "vibe_server_alias", os.path.join(SCRIPTS, "server.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if prev is None:
            os.environ.pop("VIBE_HARNESS_USERS_CONFIG", None)
        else:
            os.environ["VIBE_HARNESS_USERS_CONFIG"] = prev


class UserAliasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = os.path.join(self.tmp.name, "users.json")
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"aliases": {"a.kim": "akim", "akim-work": "akim",
                                   "김아영": "akim", "Bo Lee": "bolee"}}, f)
        self.server = load_server(self.cfg)

    def test_alias_maps_to_canonical(self):
        self.assertEqual(self.server._canon_user("a.kim"), "akim")
        self.assertEqual(self.server._canon_user("akim-work"), "akim")
        self.assertEqual(self.server._canon_user("김아영"), "akim")
        self.assertEqual(self.server._canon_user("Bo Lee"), "bolee")

    def test_alias_lookup_is_case_insensitive_and_trimmed(self):
        self.assertEqual(self.server._canon_user("  A.Kim  "), "akim")

    def test_unknown_name_passes_through(self):
        self.assertEqual(self.server._canon_user("Chris Park"), "Chris Park")

    def test_empty_stays_empty(self):
        self.assertEqual(self.server._canon_user(""), "")
        self.assertEqual(self.server._canon_user(None), "")

    def test_new_task_canonicalizes_owner_fields(self):
        data = {"version": 1, "next_id": 1, "tasks": []}
        _, task = self.server._new_task(
            data, {"title": "t", "created_by": "a.kim", "assigned_to": "akim-work"})
        self.assertEqual(task["created_by"], "akim")
        self.assertEqual(task["assigned_to"], "akim")

    def test_update_task_canonicalizes_owner_fields(self):
        task = {"created_by": "akim", "assigned_to": ""}
        self.server._update_task(task, {"created_by": "김아영", "assigned_to": "a.kim"})
        self.assertEqual(task["created_by"], "akim")
        self.assertEqual(task["assigned_to"], "akim")

    def test_git_user_is_canonicalized(self):
        self.server._git_user._cache = "a.kim"
        self.assertEqual(self.server._git_user(), "akim")

    def test_missing_config_means_no_aliases(self):
        srv = load_server(os.path.join(self.tmp.name, "does-not-exist.json"))
        self.assertEqual(srv._load_user_aliases(), {})
        self.assertEqual(srv._canon_user("a.kim"), "a.kim")

    def test_malformed_config_degrades_quietly(self):
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        srv = load_server(bad)
        self.assertEqual(srv._load_user_aliases(), {})
        self.assertEqual(srv._canon_user("a.kim"), "a.kim")

    def test_non_dict_aliases_ignored(self):
        odd = os.path.join(self.tmp.name, "odd.json")
        with open(odd, "w", encoding="utf-8") as f:
            json.dump({"aliases": ["a.kim"]}, f)
        srv = load_server(odd)
        self.assertEqual(srv._load_user_aliases(), {})


if __name__ == "__main__":
    unittest.main()
