import os
import re
import unittest
from unittest.mock import patch, MagicMock

# release.sh is Python despite the .sh extension
import types

_src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "release.sh")
release_module = types.ModuleType("release")
with open(_src_path) as _f:
    exec(compile(_f.read(), _src_path, "exec"), release_module.__dict__)

parse_pr_body = release_module.parse_pr_body
release = release_module.release


def slug(path: str) -> str:
    return path.replace("/", "-").replace("\\", "-")


# ---------------------------------------------------------------------------
# parse_pr_body tests
# ---------------------------------------------------------------------------

class TestParsePrBody(unittest.TestCase):

    # --- happy-path cases from claude.md ---

    def test_case1_single_level(self):
        """TC1: feat(nati): add dashboard → one entry, path=nati"""
        result = parse_pr_body("feat(nati): add dashboard")
        self.assertEqual(result, {"feat(nati): add dashboard"})

    def test_case2_nested_plugin(self):
        """TC2: fix(plugins/docker): resolve socket error → one entry"""
        result = parse_pr_body("fix(plugins/docker): resolve socket error")
        self.assertEqual(result, {"fix(plugins/docker): resolve socket error"})

    def test_case3_bulk_explosion(self):
        """TC3: feat(base/argo, nati, plugins/git): … → three entries"""
        result = parse_pr_body("feat(base/argo, nati, plugins/git): global auth update")
        self.assertEqual(result, {
            "feat(base/argo): global auth update",
            "feat(nati): global auth update",
            "feat(plugins/git): global auth update",
        })

    def test_case4_deeply_nested(self):
        """TC4: chore(base/infra/networking/firewall): update rules → one entry"""
        result = parse_pr_body("chore(base/infra/networking/firewall): update rules")
        self.assertEqual(result, {"chore(base/infra/networking/firewall): update rules"})

    # --- slug derivation ---

    def test_slug_single_level(self):
        self.assertEqual(slug("nati"), "nati")

    def test_slug_two_levels(self):
        self.assertEqual(slug("plugins/docker"), "plugins-docker")

    def test_slug_deeply_nested(self):
        self.assertEqual(slug("base/infra/networking/firewall"), "base-infra-networking-firewall")

    # --- edge cases ---

    def test_empty_body(self):
        self.assertEqual(parse_pr_body(""), set())

    def test_none_body(self):
        self.assertEqual(parse_pr_body(None), set())

    def test_no_conventional_commits(self):
        body = "just some random text\nno commits here"
        self.assertEqual(parse_pr_body(body), set())

    def test_deduplication(self):
        """Duplicate lines must collapse into one entry."""
        body = "feat(nati): add dashboard\nfeat(nati): add dashboard"
        result = parse_pr_body(body)
        self.assertEqual(result, {"feat(nati): add dashboard"})

    def test_mixed_valid_and_invalid_lines(self):
        body = (
            "feat(nati): add dashboard\n"
            "this line is not a commit\n"
            "fix(plugins/check): resolve login timeout\n"
        )
        result = parse_pr_body(body)
        self.assertEqual(result, {
            "feat(nati): add dashboard",
            "fix(plugins/check): resolve login timeout",
        })

    def test_whitespace_trimmed_in_scopes(self):
        """Spaces around comma-separated scopes must be stripped."""
        result = parse_pr_body("feat(base/argo , nati ): msg")
        self.assertIn("feat(base/argo): msg", result)
        self.assertIn("feat(nati): msg", result)

    def test_multi_line_pr_body(self):
        body = (
            "feat(base/argo, nati): update core security\n"
            "fix(plugins/check): resolve login timeout\n"
        )
        result = parse_pr_body(body)
        self.assertEqual(result, {
            "feat(base/argo): update core security",
            "feat(nati): update core security",
            "fix(plugins/check): resolve login timeout",
        })

    def test_type_lowercased(self):
        """Type must be lowercased regardless of input case."""
        result = parse_pr_body("FEAT(nati): something")
        self.assertIn("feat(nati): something", result)


# ---------------------------------------------------------------------------
# release() integration tests (filesystem + subprocess mocked)
# ---------------------------------------------------------------------------

class TestRelease(unittest.TestCase):

    def _run(self, pr_body, dirs_that_exist, cliff_returncode=0, cliff_stderr="", cliff_stdout="Bumped to 1.1.0"):
        mock_result = MagicMock()
        mock_result.returncode = cliff_returncode
        mock_result.stdout = cliff_stdout
        mock_result.stderr = cliff_stderr

        env = {
            "PR_BODY": pr_body,
            "PLUGIN_MONOREPO_PATH": "/repo",
        }

        with patch.dict(os.environ, env), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isdir", side_effect=lambda p: any(p.endswith(d) for d in dirs_that_exist)), \
             patch.object(release_module, "run_command", return_value=mock_result) as mock_cmd:
            release()
            return mock_cmd

    def test_single_component_calls_git_cliff(self):
        mock_cmd = self._run("feat(nati): add dashboard", dirs_that_exist=["nati"])
        self.assertEqual(mock_cmd.call_count, 1)
        call_arg = mock_cmd.call_args[0][0]
        self.assertIn("--include-path 'nati/**/*'", call_arg)
        self.assertIn("feat(nati): add dashboard", call_arg)

    def test_multi_scope_calls_git_cliff_for_each(self):
        mock_cmd = self._run(
            "feat(base/argo, nati, plugins/git): global auth update",
            dirs_that_exist=["base/argo", "nati", "plugins/git"],
        )
        self.assertEqual(mock_cmd.call_count, 3)

    def test_missing_directory_is_skipped(self, capsys=None):
        mock_cmd = self._run(
            "feat(nati): add dashboard\nfix(missing-dir): something",
            dirs_that_exist=["nati"],
        )
        # Only nati was a real dir → only one cliff call
        self.assertEqual(mock_cmd.call_count, 1)

    def test_empty_pr_body_does_nothing(self):
        mock_cmd = self._run("", dirs_that_exist=[])
        mock_cmd.assert_not_called()

    def test_cliff_failure_does_not_raise(self):
        """A non-zero git-cliff exit must print an error but not crash."""
        mock_cmd = self._run(
            "feat(nati): add dashboard",
            dirs_that_exist=["nati"],
            cliff_returncode=1,
            cliff_stderr="some git-cliff error",
        )
        self.assertEqual(mock_cmd.call_count, 1)

    def test_tag_slug_uses_hyphens(self):
        mock_cmd = self._run(
            "fix(plugins/docker): resolve socket error",
            dirs_that_exist=["plugins/docker"],
        )
        call_arg = mock_cmd.call_args[0][0]
        self.assertIn("plugins-docker-v", call_arg)

    def test_deeply_nested_slug(self):
        mock_cmd = self._run(
            "chore(base/infra/networking/firewall): update rules",
            dirs_that_exist=["base/infra/networking/firewall"],
        )
        call_arg = mock_cmd.call_args[0][0]
        self.assertIn("base-infra-networking-firewall-v", call_arg)


if __name__ == "__main__":
    unittest.main()
