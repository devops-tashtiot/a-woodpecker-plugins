import os
import re
import unittest
from unittest.mock import patch, MagicMock, call

import types

_src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "release.py")
release_module = types.ModuleType("release")
with open(_src_path) as _f:
    exec(compile(_f.read(), _src_path, "exec"), release_module.__dict__)

parse_pr_body            = release_module.parse_pr_body
parse_pr_body_polyrepo   = release_module.parse_pr_body_polyrepo
expand_wildcard          = release_module.expand_wildcard
discover_scopes          = release_module.discover_scopes
deduplicate_by_scope     = release_module.deduplicate_by_scope
_bump_priority           = release_module._bump_priority
release                  = release_module.release


def slug(path: str) -> str:
    return path.replace("/", "-").replace("\\", "-")


# ---------------------------------------------------------------------------
# parse_pr_body tests  (depth=1 / depth=2 — scoped commits)
# ---------------------------------------------------------------------------

class TestParsePrBody(unittest.TestCase):

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

    def test_slug_single_level(self):
        self.assertEqual(slug("nati"), "nati")

    def test_slug_two_levels(self):
        self.assertEqual(slug("plugins/docker"), "plugins-docker")

    def test_slug_deeply_nested(self):
        self.assertEqual(slug("base/infra/networking/firewall"), "base-infra-networking-firewall")

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

    def test_breaking_bang_notation_preserved(self):
        """feat(nati)!: msg — the ! must be kept in the output."""
        result = parse_pr_body("feat(nati)!: big breaking change")
        self.assertEqual(result, {"feat(nati)!: big breaking change"})

    def test_multi_scope_bang_preserved(self):
        """feat(a, b)!: msg — bang kept for each exploded scope."""
        result = parse_pr_body("feat(a, b)!: big change")
        self.assertEqual(result, {"feat(a)!: big change", "feat(b)!: big change"})

    def test_wildcard_scope_parsed_as_literal(self):
        """feat(*): msg is passed through as-is by parse_pr_body."""
        result = parse_pr_body("feat(*): upgrade all")
        self.assertEqual(result, {"feat(*): upgrade all"})

    def test_chore_type_accepted(self):
        result = parse_pr_body("chore(nati): bump deps")
        self.assertEqual(result, {"chore(nati): bump deps"})

    def test_breaking_type_accepted(self):
        result = parse_pr_body("breaking(nati): remove old api")
        self.assertEqual(result, {"breaking(nati): remove old api"})


# ---------------------------------------------------------------------------
# parse_pr_body_polyrepo tests  (depth=0 — no scope)
# ---------------------------------------------------------------------------

class TestParsePrBodyPolyrepo(unittest.TestCase):

    def test_simple_feat(self):
        result = parse_pr_body_polyrepo("feat: add login page")
        self.assertEqual(result, {"feat: add login page"})

    def test_simple_fix(self):
        result = parse_pr_body_polyrepo("fix: resolve crash")
        self.assertEqual(result, {"fix: resolve crash"})

    def test_bang_breaking(self):
        """feat!: msg → breaking change without scope."""
        result = parse_pr_body_polyrepo("feat!: drop python 3.8 support")
        self.assertEqual(result, {"feat!: drop python 3.8 support"})

    def test_type_lowercased(self):
        result = parse_pr_body_polyrepo("FIX: something")
        self.assertIn("fix: something", result)

    def test_empty_body(self):
        self.assertEqual(parse_pr_body_polyrepo(""), set())

    def test_none_body(self):
        self.assertEqual(parse_pr_body_polyrepo(None), set())

    def test_scoped_commit_not_matched(self):
        """feat(nati): msg has a scope → does NOT match polyrepo pattern."""
        result = parse_pr_body_polyrepo("feat(nati): add dashboard")
        self.assertEqual(result, set())

    def test_random_text_not_matched(self):
        self.assertEqual(parse_pr_body_polyrepo("just a PR description"), set())

    def test_multi_line_returns_all(self):
        body = "feat: add feature\nfix: patch bug"
        result = parse_pr_body_polyrepo(body)
        self.assertEqual(result, {"feat: add feature", "fix: patch bug"})

    def test_deduplication(self):
        body = "feat: add feature\nfeat: add feature"
        result = parse_pr_body_polyrepo(body)
        self.assertEqual(result, {"feat: add feature"})

    def test_chore_type(self):
        result = parse_pr_body_polyrepo("chore: update deps")
        self.assertEqual(result, {"chore: update deps"})


# ---------------------------------------------------------------------------
# _bump_priority tests
# ---------------------------------------------------------------------------

class TestBumpPriority(unittest.TestCase):

    def test_breaking_type_is_3(self):
        self.assertEqual(_bump_priority("breaking(nati): remove api"), 3)

    def test_bang_notation_is_3(self):
        self.assertEqual(_bump_priority("feat(nati)!: big change"), 3)

    def test_breaking_bang_both_3(self):
        self.assertEqual(_bump_priority("breaking(nati)!: extra explicit"), 3)

    def test_feat_is_2(self):
        self.assertEqual(_bump_priority("feat(nati): add feature"), 2)

    def test_fix_is_1(self):
        self.assertEqual(_bump_priority("fix(nati): patch bug"), 1)

    def test_chore_is_1(self):
        self.assertEqual(_bump_priority("chore(nati): update deps"), 1)

    def test_docs_is_1(self):
        self.assertEqual(_bump_priority("docs(nati): update readme"), 1)

    def test_polyrepo_feat_returns_0(self):
        """_bump_priority requires '(' after type — scopeless messages return 0."""
        self.assertEqual(_bump_priority("feat: add login"), 0)

    def test_polyrepo_breaking_returns_0(self):
        """Scopeless breaking: msg has no '(' → returns 0."""
        self.assertEqual(_bump_priority("breaking: remove legacy"), 0)

    def test_no_type_match_is_0(self):
        """String with no type prefix → 0."""
        self.assertEqual(_bump_priority("random text"), 0)


# ---------------------------------------------------------------------------
# deduplicate_by_scope tests
# ---------------------------------------------------------------------------

class TestDeduplicateByScope(unittest.TestCase):

    def test_breaking_wins_over_feat(self):
        msgs = {"feat(nati): add thing", "breaking(nati): remove api"}
        result = deduplicate_by_scope(msgs)
        self.assertEqual(result, {"breaking(nati): remove api"})

    def test_feat_wins_over_fix(self):
        msgs = {"fix(nati): patch", "feat(nati): add feature"}
        result = deduplicate_by_scope(msgs)
        self.assertEqual(result, {"feat(nati): add feature"})

    def test_bang_notation_wins_over_feat(self):
        msgs = {"feat(nati): normal", "feat(nati)!: breaking"}
        result = deduplicate_by_scope(msgs)
        self.assertEqual(result, {"feat(nati)!: breaking"})

    def test_different_scopes_both_kept(self):
        msgs = {"feat(nati): add thing", "breaking(base/argo): remove api"}
        result = deduplicate_by_scope(msgs)
        self.assertEqual(result, {"feat(nati): add thing", "breaking(base/argo): remove api"})

    def test_three_commits_same_scope_highest_wins(self):
        msgs = {"fix(nati): patch", "feat(nati): minor", "breaking(nati): major"}
        result = deduplicate_by_scope(msgs)
        self.assertEqual(result, {"breaking(nati): major"})

    def test_single_message_passes_through(self):
        msgs = {"feat(nati): add feature"}
        result = deduplicate_by_scope(msgs)
        self.assertEqual(result, {"feat(nati): add feature"})

    def test_equal_priority_first_encountered_wins(self):
        """Two fix commits for the same scope — only one survives (any one)."""
        msgs = {"fix(nati): patch A", "fix(nati): patch B"}
        result = deduplicate_by_scope(msgs)
        self.assertEqual(len(result), 1)
        self.assertTrue(result.pop().startswith("fix(nati):"))

    def test_multiple_scopes_no_collisions(self):
        msgs = {
            "feat(nati): add thing",
            "fix(base/argo): patch",
            "breaking(check/auth): remove",
        }
        result = deduplicate_by_scope(msgs)
        self.assertEqual(len(result), 3)


# ---------------------------------------------------------------------------
# discover_scopes tests
# ---------------------------------------------------------------------------

class TestDiscoverScopes(unittest.TestCase):

    def _listdir(self, entries, root="/repo", depth=1, parent=None):
        with patch("os.listdir", return_value=entries), \
             patch("os.path.isdir", return_value=True):
            return discover_scopes(root, depth, parent)

    def test_depth1_returns_direct_subdirs(self):
        result = self._listdir(["nati", "plugins", "base"])
        self.assertEqual(sorted(result), ["base", "nati", "plugins"])

    def test_depth1_with_parent_prefix(self):
        result = self._listdir(["argo", "infra"], parent="base")
        self.assertEqual(sorted(result), ["base/argo", "base/infra"])

    def test_depth2_no_parent_two_level_scan(self):
        """depth=2, no parent: scans two levels deep."""
        def listdir_side(path):
            if path == "/repo":
                return ["base", "check"]
            if path.endswith("base"):
                return ["argo", "infra"]
            if path.endswith("check"):
                return ["auth"]
            return []

        with patch("os.listdir", side_effect=listdir_side), \
             patch("os.path.isdir", return_value=True):
            result = discover_scopes("/repo", depth=2)
        self.assertEqual(sorted(result), ["base/argo", "base/infra", "check/auth"])

    def test_depth2_with_parent_prefix(self):
        result = self._listdir(["argo", "infra"], depth=2, parent="base")
        self.assertEqual(sorted(result), ["base/argo", "base/infra"])

    def test_depth1_non_dirs_excluded(self):
        with patch("os.listdir", return_value=["nati", "README.md"]), \
             patch("os.path.isdir", side_effect=lambda p: p.endswith("nati")):
            result = discover_scopes("/repo", depth=1)
        self.assertEqual(result, ["nati"])

    def test_oserror_returns_empty(self):
        with patch("os.listdir", side_effect=OSError("no such dir")):
            result = discover_scopes("/no/such/dir", depth=1)
        self.assertEqual(result, [])

    def test_depth_other_returns_empty(self):
        result = discover_scopes("/repo", depth=99)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# expand_wildcard tests
# ---------------------------------------------------------------------------

class TestExpandWildcard(unittest.TestCase):

    def _expand(self, messages, listdir_result=None, depth=1, exclude_regex=""):
        """Helper: mocks os.listdir and os.path.isdir for expand_wildcard."""
        listdir_result = listdir_result or []
        with patch("os.listdir", return_value=listdir_result), \
             patch("os.path.isdir", return_value=True):
            return expand_wildcard(messages, "/repo", depth, exclude_regex)

    def test_wildcard_expands_to_each_scope(self):
        result = self._expand({"feat(*): upgrade"}, ["a", "b"])
        self.assertEqual(result, {"feat(a): upgrade", "feat(b): upgrade"})

    def test_breaking_wildcard_expands(self):
        result = self._expand({"breaking(*): remove api"}, ["a", "b"])
        self.assertEqual(result, {
            "breaking(a): remove api",
            "breaking(b): remove api",
        })

    def test_bang_notation_preserved(self):
        result = self._expand({"feat(*)!: big change"}, ["x"])
        self.assertEqual(result, {"feat(x)!: big change"})

    def test_non_wildcard_passes_through_unchanged(self):
        msgs = {"feat(nati): x", "fix(base/argo): y"}
        self.assertEqual(self._expand(msgs), msgs)

    def test_wildcard_no_dirs_returns_empty(self):
        result = self._expand({"feat(*): x"}, [])
        self.assertEqual(result, set())

    def test_mixed_wildcard_and_specific(self):
        result = self._expand({"feat(*): x", "fix(nati): y"}, ["a"])
        self.assertEqual(result, {"feat(a): x", "fix(nati): y"})

    def test_no_wildcard_skips_discovery(self):
        """If no * in messages, same object is returned (no filesystem access)."""
        msgs = {"feat(nati): x"}
        self.assertIs(expand_wildcard(msgs, "/repo", 1), msgs)

    def test_no_wildcard_no_exclude_identity(self):
        """No wildcard, no exclude → exact same object returned."""
        msgs = {"feat(a): x", "fix(b): y"}
        self.assertIs(expand_wildcard(msgs, "/repo", 1, exclude_regex=""), msgs)

    def test_exclude_regex_filters_wildcard_scopes(self):
        result = self._expand(
            {"feat(*): upgrade"}, ["nati", "docs", "shared"],
            exclude_regex="^docs$|^shared$"
        )
        self.assertEqual(result, {"feat(nati): upgrade"})

    def test_exclude_regex_filters_explicit_scope(self):
        result = self._expand({"feat(nati): upgrade"}, exclude_regex="^nati")
        self.assertEqual(result, set())

    def test_exclude_regex_allows_partial_match(self):
        """Regex applied via re.search so partial match also excludes."""
        result = self._expand({"feat(base/legacy): msg"}, exclude_regex="legacy")
        self.assertEqual(result, set())

    def test_exclude_regex_filters_prefix_wildcard_scopes(self):
        """feat(base/*) with some dirs excluded."""
        result = self._expand(
            {"feat(base/*): upgrade"}, ["argo", "infra", "legacy"],
            depth=2, exclude_regex="^base/legacy$"
        )
        self.assertEqual(result, {"feat(base/argo): upgrade", "feat(base/infra): upgrade"})

    def test_wildcard_invalid_at_depth2(self):
        """feat(*) at depth=2 is invalid — result is empty."""
        result = self._expand({"feat(*): msg"}, ["a", "b"], depth=2)
        self.assertEqual(result, set())

    def test_prefix_wildcard_at_depth2(self):
        """feat(base/*) at depth=2 expands to all subdirs of base/."""
        result = self._expand({"feat(base/*): upgrade"}, ["nati", "check"], depth=2)
        self.assertEqual(result, {"feat(base/nati): upgrade", "feat(base/check): upgrade"})

    def test_prefix_wildcard_no_subdirs(self):
        """feat(base/*) with no subdirs under base/ → empty."""
        result = self._expand({"feat(base/*): upgrade"}, [], depth=2)
        self.assertEqual(result, set())

    def test_all_wildcard_scopes_excluded_returns_empty(self):
        """If every discovered scope is excluded, result is empty."""
        result = self._expand(
            {"feat(*): upgrade"}, ["docs", "shared"],
            exclude_regex="^docs$|^shared$"
        )
        self.assertEqual(result, set())

    def test_mixed_wildcard_and_explicit_with_exclude(self):
        """Wildcard + explicit; exclude filters both."""
        result = self._expand(
            {"feat(*): x", "feat(docs): y"},
            ["nati", "docs"],
            exclude_regex="^docs$"
        )
        # feat(*) → nati (docs excluded), feat(docs) → excluded
        self.assertEqual(result, {"feat(nati): x"})


# ---------------------------------------------------------------------------
# release() integration tests (filesystem + subprocess mocked)
# ---------------------------------------------------------------------------

class TestRelease(unittest.TestCase):

    def _run(self, pr_body, dirs_that_exist, cliff_returncode=0, cliff_stderr="",
             cliff_stdout="Bumped to 1.1.0", list_dirs=None, scope_depth="1",
             exclude_regex=""):
        mock_result = MagicMock()
        mock_result.returncode = cliff_returncode
        mock_result.stdout = cliff_stdout
        mock_result.stderr = cliff_stderr

        env = {
            "PR_BODY": pr_body,
            "PLUGIN_BASE": "/repo",
            "SCOPE_DEPTH": scope_depth,
            "SCOPE_EXCLUDE_REGEX": exclude_regex,
        }

        list_dirs = list_dirs or []

        with patch.dict(os.environ, env), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isdir", side_effect=lambda p: any(p.endswith(d) for d in dirs_that_exist)), \
             patch("os.listdir", return_value=list_dirs), \
             patch("os.path.relpath", side_effect=lambda p, base: p.replace(base + "/", "") if p != base else "."), \
             patch.object(release_module, "run_command", return_value=mock_result) as mock_cmd:
            release()
            return mock_cmd

    # ── depth=1 (existing tests) ────────────────────────────────────────────

    def test_single_component_calls_git_cliff(self):
        mock_cmd = self._run("feat(nati): add dashboard", dirs_that_exist=["nati"])
        self.assertEqual(mock_cmd.call_count, 4)
        call_arg = mock_cmd.call_args[0][0]
        self.assertIn("--include-path 'nati/**/*'", call_arg)
        self.assertIn("feat(nati): add dashboard", call_arg)

    def test_multi_scope_calls_git_cliff_for_each(self):
        mock_cmd = self._run(
            "feat(base/argo, nati, plugins/git): global auth update",
            dirs_that_exist=["base/argo", "nati", "plugins/git"],
        )
        self.assertEqual(mock_cmd.call_count, 12)

    def test_missing_directory_is_skipped(self):
        mock_cmd = self._run(
            "feat(nati): add dashboard\nfix(missing-dir): something",
            dirs_that_exist=["nati"],
        )
        self.assertEqual(mock_cmd.call_count, 4)

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
        self.assertEqual(mock_cmd.call_count, 3)

    def test_tag_slug_uses_hyphens(self):
        mock_cmd = self._run(
            "fix(plugins/docker): resolve socket error",
            dirs_that_exist=["plugins/docker"],
        )
        call_arg = mock_cmd.call_args[0][0]
        self.assertIn("plugins-docker-v", call_arg)

    def test_deeply_nested_slug(self):
        mock_cmd = self._run(
            "feat(base/infra/networking/firewall): update rules",
            dirs_that_exist=["base/infra/networking/firewall"],
        )
        call_arg = mock_cmd.call_args[0][0]
        self.assertIn("base-infra-networking-firewall-v", call_arg)

    def test_feat_wildcard_expands(self):
        """feat(*) discovers direct subdirs via os.listdir and releases each."""
        mock_cmd = self._run(
            "feat(*): global upgrade",
            dirs_that_exist=["a", "b"],
            list_dirs=["a", "b"],
        )
        self.assertEqual(mock_cmd.call_count, 8)

    def test_feat_wildcard_no_dirs_does_nothing(self):
        """feat(*) with no discoverable dirs → no releases."""
        mock_cmd = self._run(
            "feat(*): global upgrade",
            dirs_that_exist=[],
            list_dirs=[],
        )
        mock_cmd.assert_not_called()

    def test_scope_deduplication_breaking_wins_over_feat(self):
        """feat + breaking for same scope → only breaking is processed (one tag)."""
        mock_cmd = self._run(
            "feat(nati): add thing\nbreaking(nati): remove api",
            dirs_that_exist=["nati"],
        )
        self.assertEqual(mock_cmd.call_count, 4)
        for call in mock_cmd.call_args_list:
            arg = call[0][0]
            if "--with-commit" in arg:
                self.assertIn("breaking(nati)", arg)
                self.assertNotIn("feat(nati)", arg)

    def test_scope_deduplication_two_different_scopes_both_process(self):
        """feat(a) + breaking(b) → both processed (different scopes)."""
        mock_cmd = self._run(
            "feat(nati): add thing\nbreaking(base/argo): remove api",
            dirs_that_exist=["nati", "base/argo"],
        )
        self.assertEqual(mock_cmd.call_count, 8)

    # ── depth=1: SCOPE_EXCLUDE_REGEX ───────────────────────────────────────

    def test_depth1_exclude_filters_explicit_scope(self):
        """Explicit scope matching SCOPE_EXCLUDE_REGEX → skipped, no run_command calls."""
        mock_cmd = self._run(
            "feat(nati): add dashboard",
            dirs_that_exist=["nati"],
            exclude_regex="^nati$",
        )
        mock_cmd.assert_not_called()

    def test_depth1_exclude_partial_regex_filters(self):
        """Regex matching partial scope name also excludes."""
        mock_cmd = self._run(
            "feat(base/legacy): refactor",
            dirs_that_exist=["base/legacy"],
            exclude_regex="legacy",
        )
        mock_cmd.assert_not_called()

    def test_depth1_exclude_only_matching_scopes(self):
        """Two scopes: one excluded, one not. Only the valid one is released."""
        mock_cmd = self._run(
            "feat(nati): add thing\nfeat(docs): update docs",
            dirs_that_exist=["nati", "docs"],
            exclude_regex="^docs$",
        )
        self.assertEqual(mock_cmd.call_count, 4)  # only nati released (4 calls)

    def test_depth1_wildcard_with_exclude_skips_some_dirs(self):
        """feat(*) with exclude → discovered dirs that match regex are skipped."""
        mock_cmd = self._run(
            "feat(*): upgrade all",
            dirs_that_exist=["nati", "docs", "shared"],
            list_dirs=["nati", "docs", "shared"],
            exclude_regex="^docs$|^shared$",
        )
        # Only nati released → 4 calls
        self.assertEqual(mock_cmd.call_count, 4)

    def test_depth1_wildcard_all_excluded_does_nothing(self):
        """feat(*) with all dirs excluded → no releases."""
        mock_cmd = self._run(
            "feat(*): upgrade all",
            dirs_that_exist=["docs", "shared"],
            list_dirs=["docs", "shared"],
            exclude_regex="^docs$|^shared$",
        )
        mock_cmd.assert_not_called()

    def test_depth1_bang_notation_breaking_wins(self):
        """feat(nati)!: msg + feat(nati): msg — ! notation wins as breaking.
        After deduplication only one message remains, so only 4 calls total.
        The --bumped-version call (call index 1) uses the ! message.
        """
        mock_cmd = self._run(
            "feat(nati)!: breaking change\nfeat(nati): add feature",
            dirs_that_exist=["nati"],
        )
        self.assertEqual(mock_cmd.call_count, 4)
        # The bump query is the only call with both --bumped-version and --with-commit
        bump_calls = [c for c in mock_cmd.call_args_list
                      if "--bumped-version" in c[0][0]]
        self.assertEqual(len(bump_calls), 1)
        self.assertIn("feat(nati)!:", bump_calls[0][0][0])
        self.assertNotIn("feat(nati): add feature", bump_calls[0][0][0])

    # ── depth=2 ─────────────────────────────────────────────────────────────

    def test_depth2_explicit_nested_scope(self):
        """depth=2: feat(base/argo): msg → base-argo-v* tag."""
        mock_cmd = self._run(
            "feat(base/argo): upgrade helm",
            dirs_that_exist=["base/argo"],
            scope_depth="2",
        )
        self.assertEqual(mock_cmd.call_count, 4)
        call_arg = mock_cmd.call_args[0][0]
        self.assertIn("base-argo-v", call_arg)
        self.assertIn("--include-path 'base/argo/**/*'", call_arg)

    def test_depth2_bare_wildcard_invalid_does_nothing(self):
        """depth=2: feat(*): msg is invalid — no releases."""
        mock_cmd = self._run(
            "feat(*): upgrade all",
            dirs_that_exist=["base/argo"],
            list_dirs=["argo"],
            scope_depth="2",
        )
        mock_cmd.assert_not_called()

    def test_depth2_group_wildcard_expands(self):
        """depth=2: feat(base/*): msg expands to all subdirs of base/."""
        mock_cmd = self._run(
            "feat(base/*): major refactor",
            dirs_that_exist=["base/argo", "base/infra"],
            list_dirs=["argo", "infra"],
            scope_depth="2",
        )
        # Two components × 4 calls each = 8
        self.assertEqual(mock_cmd.call_count, 8)

    def test_depth2_group_wildcard_slug_correct(self):
        """depth=2: feat(base/argo): msg → list-tags query uses base-argo-v* pattern."""
        mock_cmd = self._run(
            "feat(base/argo): upgrade",
            dirs_that_exist=["base/argo"],
            scope_depth="2",
        )
        # First call is: git tag -l 'base-argo-v*' — confirms slug is base-argo
        list_tags_call = mock_cmd.call_args_list[0][0][0]
        self.assertIn("base-argo-v", list_tags_call)
        self.assertIn("git tag -l", list_tags_call)

    def test_depth2_group_wildcard_with_exclude(self):
        """depth=2: feat(base/*) with exclude='^base/legacy' → legacy skipped."""
        mock_cmd = self._run(
            "feat(base/*): upgrade",
            dirs_that_exist=["base/argo", "base/legacy"],
            list_dirs=["argo", "legacy"],
            scope_depth="2",
            exclude_regex="^base/legacy$",
        )
        # Only base/argo released → 4 calls
        self.assertEqual(mock_cmd.call_count, 4)

    def test_depth2_missing_dir_skipped(self):
        """depth=2: scope dir not on disk → skipped."""
        mock_cmd = self._run(
            "feat(base/ghost): upgrade",
            dirs_that_exist=[],
            scope_depth="2",
        )
        mock_cmd.assert_not_called()

    def test_depth2_breaking_dedup(self):
        """depth=2: breaking + feat for same nested scope → breaking wins."""
        mock_cmd = self._run(
            "feat(base/argo): add thing\nbreaking(base/argo): remove api",
            dirs_that_exist=["base/argo"],
            scope_depth="2",
        )
        self.assertEqual(mock_cmd.call_count, 4)
        bump_calls = [c for c in mock_cmd.call_args_list if "--with-commit" in c[0][0]]
        self.assertIn("breaking(base/argo)", bump_calls[0][0][0])

    # ── depth=0 (polyrepo) ─────────────────────────────────────────────────

    def test_depth0_first_release_no_existing_tag(self):
        """depth=0, no existing tag → v1.0.0 (3 calls: list-tags + git-tag + changelog)."""
        mock_cmd = self._run(
            "feat: add login page",
            dirs_that_exist=[],
            scope_depth="0",
            cliff_stdout="",  # empty → no existing tag → new_tag = v1.0.0
        )
        self.assertEqual(mock_cmd.call_count, 3)
        calls_str = " ".join(c[0][0] for c in mock_cmd.call_args_list)
        self.assertIn("v1.0.0", calls_str)

    def test_depth0_with_existing_tag_bumped(self):
        """depth=0, existing tag present → 4 calls (list-tags + bump + git-tag + changelog)."""
        mock_cmd = self._run(
            "feat: add feature",
            dirs_that_exist=[],
            scope_depth="0",
            cliff_stdout="v1.1.0",  # non-empty → latest_tag found → bump call made
        )
        self.assertEqual(mock_cmd.call_count, 4)

    def test_depth0_scoped_commit_ignored(self):
        """depth=0: feat(nati): msg has a scope → polyrepo parser ignores it → no release."""
        mock_cmd = self._run(
            "feat(nati): add dashboard",
            dirs_that_exist=[],
            scope_depth="0",
        )
        mock_cmd.assert_not_called()

    def test_depth0_empty_body_does_nothing(self):
        mock_cmd = self._run("", dirs_that_exist=[], scope_depth="0")
        mock_cmd.assert_not_called()

    def test_depth0_multiple_commits_makes_one_release(self):
        """depth=0: fix + feat in body → exactly one bump+tag+changelog cycle (4 calls)."""
        # Note: _bump_priority returns 0 for all scopeless messages, so max() picks
        # an arbitrary winner — we only assert the correct call count here.
        mock_cmd = self._run(
            "fix: patch a bug\nfeat: add feature",
            dirs_that_exist=[],
            scope_depth="0",
            cliff_stdout="v1.1.0",  # non-empty → existing tag → 4 calls
        )
        self.assertEqual(mock_cmd.call_count, 4)

    def test_depth0_breaking_makes_one_release(self):
        """depth=0: fix + feat + breaking → still one release cycle (4 calls)."""
        mock_cmd = self._run(
            "fix: patch\nfeat: add\nbreaking: remove legacy api",
            dirs_that_exist=[],
            scope_depth="0",
            cliff_stdout="v2.0.0",
        )
        self.assertEqual(mock_cmd.call_count, 4)

    def test_depth0_bang_notation_makes_one_release(self):
        """depth=0: feat!: msg + fix: msg → one release cycle (4 calls)."""
        mock_cmd = self._run(
            "fix: patch\nfeat!: drop python 3.8",
            dirs_that_exist=[],
            scope_depth="0",
            cliff_stdout="v2.0.0",
        )
        self.assertEqual(mock_cmd.call_count, 4)

    def test_depth0_tag_pattern_is_version_only(self):
        """depth=0: tag pattern is '^v[0-9]+...' (no slug prefix)."""
        mock_cmd = self._run(
            "feat: add feature",
            dirs_that_exist=[],
            scope_depth="0",
            cliff_stdout="v1.1.0",
        )
        calls_str = " ".join(c[0][0] for c in mock_cmd.call_args_list)
        self.assertIn("^v[0-9]+", calls_str)
        # Make sure no component slug prefix in tag pattern
        self.assertNotIn("-v[0-9]", calls_str)

    def test_depth0_cliff_failure_does_not_crash(self):
        """depth=0: git tag fails (returncode=1) → returns early, no exception."""
        mock_cmd = self._run(
            "feat: add feature",
            dirs_that_exist=[],
            scope_depth="0",
            cliff_stdout="",   # no existing tag → v1.0.0
            cliff_returncode=1,
            cliff_stderr="git-cliff failed",
        )
        # Call 1: git tag -l (list existing tags) — returns returncode=1 but stdout=""
        # latest_tag = None → new_tag = "v1.0.0"
        # Call 2: git tag v1.0.0 — returncode=1 → ERROR printed, early return
        # Call 3 (changelog) never reached
        self.assertEqual(mock_cmd.call_count, 2)


if __name__ == "__main__":
    unittest.main()
