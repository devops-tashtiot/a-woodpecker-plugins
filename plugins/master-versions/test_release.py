import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import types

_src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "release.py")
release_module = types.ModuleType("release")
release_module.__file__ = _src_path
with open(_src_path) as _f:
    exec(compile(_f.read(), _src_path, "exec"), release_module.__dict__)

parse_pr_body        = release_module.parse_pr_body
_known_commit_types  = release_module._known_commit_types
_expand_locations    = release_module._expand_locations
release              = release_module.release


# ---------------------------------------------------------------------------
# Parsers fixture — mirrors the default cliff.toml commit_parsers.
# Tests use this instead of loading the real file so they stay self-contained.
# ---------------------------------------------------------------------------

PARSERS = [
    {"message": r"^breaking(\(.*?\))?", "group": "🚀 Breaking Changes", "bump_type": "major", "skip": False},
    {"message": r"^feat(\(.*?\))?",     "group": "✨ Features",          "bump_type": "minor", "skip": False},
    {"message": r"^fix(\(.*?\))?",      "group": "🐛 Bug Fixes",         "bump_type": "patch", "skip": False},
    {"message": r"^other(\(.*?\))?",    "group": "",                     "bump_type": "",       "skip": True},
]


# ---------------------------------------------------------------------------
# Class 1 — TestParsePrBody
#
# parse_pr_body(body, parsers) -> dict[location -> set[commit_str]]
#
# Each line in the body must match one of the cliff.toml commit_parsers
# patterns, followed immediately by [location]. The [location] is routing
# info only — it is stripped from the commit string before the result is
# stored. git-cliff then receives a clean conventional commit.
# ---------------------------------------------------------------------------

class TestParsePrBody(unittest.TestCase):

    def test_1_single_component_with_scope(self):
        """
        Checks: a standard line with type, scope, location, and description
                produces one entry in the result dict.

        Example:
          Input:  "feat(auth)[nati]: add login"
          Parser matches "^feat\\((.*)\\" at start, finds '[' immediately after.
          Bracket content "nati" becomes the location key.
          Brackets are stripped → commit_str = "feat(auth): add login"
          Result: {"nati": {"feat(auth): add login"}}
        """
        result = parse_pr_body("feat(auth)[nati]: add login", PARSERS)
        self.assertEqual(result, {"nati": {"feat(auth): add login"}})

    def test_2_no_scope(self):
        """
        Checks: type without scope — the scopeless parser pattern (^feat) matches,
                bracket immediately follows, location and description work normally.

        Example:
          Input:  "feat[nati]: add login"
          "^feat" matches positions 0-4. Next char is '['.
          Brackets stripped → commit_str = "feat: add login"
          Result: {"nati": {"feat: add login"}}
        """
        result = parse_pr_body("feat[nati]: add login", PARSERS)
        self.assertEqual(result, {"nati": {"feat: add login"}})

    def test_3_multiple_locations(self):
        """
        Checks: comma-separated locations in [...] produce one entry per location,
                each carrying the same commit string.

        Example:
          Input:  "feat(auth)[nati, check]: msg"
          Locations = ["nati", "check"] (spaces stripped)
          commit_str = "feat(auth): msg"
          Result: {"nati": {"feat(auth): msg"}, "check": {"feat(auth): msg"}}
        """
        result = parse_pr_body("feat(auth)[nati, check]: msg", PARSERS)
        self.assertEqual(result, {
            "nati":  {"feat(auth): msg"},
            "check": {"feat(auth): msg"},
        })

    def test_4_root_location(self):
        """
        Checks: empty brackets [] mean the repo root — the location key is "".

        Example:
          Input:  "feat(auth)[]: add login"
          Bracket content = "" → location = ""  (root)
          commit_str = "feat(auth): add login"
          Result: {"": {"feat(auth): add login"}}
        """
        result = parse_pr_body("feat(auth)[]: add login", PARSERS)
        self.assertEqual(result, {"": {"feat(auth): add login"}})

    def test_5_bang_preserved(self):
        """
        Checks: the ! (breaking-change bang) that comes after [] is kept in the
                commit string — it is NOT part of the location brackets.

        Example:
          Input:  "feat(auth)[nati]!: add login"
          Brackets stripped: "[nati]" removed.
          Remaining line: "feat(auth)!: add login"  ← bang is still there
          Result: {"nati": {"feat(auth)!: add login"}}
        """
        result = parse_pr_body("feat(auth)[nati]!: add login", PARSERS)
        self.assertEqual(result, {"nati": {"feat(auth)!: add login"}})

    def test_6_uppercase_type_not_matched(self):
        """
        Checks: uppercase type is silently ignored — cliff.toml patterns are
                lowercase anchors (^feat, ^fix, ...) and re.match is case-sensitive.

        Example:
          Input:  "FEAT(auth)[nati]: add login"
          "^feat" does NOT match "FEAT..." → no parser matches → line skipped.
          Result: {}
        """
        result = parse_pr_body("FEAT(auth)[nati]: add login", PARSERS)
        self.assertEqual(result, {})

    def test_7_leading_space_not_matched(self):
        """
        Checks: a line with leading whitespace is NOT matched — current_line is
                NOT stripped before passing to _match_line, so "  feat..." has a
                space at position 0 and "^feat" does not match it.
                Per README: type must start at the very beginning of the line.

        Example:
          Input: "  feat(auth)[nati]: add login"  (two leading spaces)
          re.match("^feat", "  feat...") → None  → line silently ignored.
          Result: {}
        """
        result = parse_pr_body("  feat(auth)[nati]: add login", PARSERS)
        self.assertEqual(result, {})

    def test_8_unknown_type_not_matched(self):
        """
        Checks: a type not listed in cliff.toml commit_parsers is silently skipped.
                git-cliff would filter it anyway (filter_unconventional=true).

        Example:
          Input:  "chore(auth)[nati]: bump deps"
          "chore" matches no parser pattern → line skipped.
          Result: {}
        """
        result = parse_pr_body("chore(auth)[nati]: bump deps", PARSERS)
        self.assertEqual(result, {})

    def test_9_wildcard_location_literal(self):
        """
        Checks: [*] is treated as a literal location "*" by parse_pr_body.
                Wildcard expansion to actual directories happens later in
                _expand_locations — parse_pr_body itself does NOT expand it.

        Example:
          Input:  "feat(auth)[*]: upgrade all"
          Location key = "*"  (literal string, not expanded here)
          commit_str = "feat(auth): upgrade all"
          Result: {"*": {"feat(auth): upgrade all"}}
        """
        result = parse_pr_body("feat(auth)[*]: upgrade all", PARSERS)
        self.assertEqual(result, {"*": {"feat(auth): upgrade all"}})

    def test_10_empty_body(self):
        """
        Checks: empty string body returns empty dict — nothing to parse.

        Example:
          Input:  ""
          Result: {}
        """
        result = parse_pr_body("", PARSERS)
        self.assertEqual(result, {})

    def test_11_no_parsers_returns_empty_with_error(self):
        """
        Checks: if parsers list is empty, parse_pr_body prints an error and
                returns {} immediately — it cannot determine which lines are commits.

        Example:
          parsers = []
          Input:  "feat(auth)[nati]: add login"
          Output: {} (error printed to stdout)
        """
        result = parse_pr_body("feat(auth)[nati]: add login", [])
        self.assertEqual(result, {})

    def test_12_multi_line_description(self):
        """
        Checks: continuation lines are ALWAYS collected after a commit line, until
                the next line that matches a parser pattern with '[...}'.
                This includes commits with a non-empty description — everything
                after the commit line (that isn't a new commit header) is appended.

        Example:
          Input:
            "feat(auth)[nati]:"
            "  Replace basic auth with OAuth2."
            "  Supports Google and GitHub."
            ""
            "fix(bug)[check]: unrelated fix"

          "feat(auth)[nati]:" → commit_str = "feat(auth):"
          Continuation lines collected until next commit header: ["  Replace basic auth with OAuth2.", "  Supports Google and GitHub.", ""]
          Final commit_str = "feat(auth):   Replace basic auth with OAuth2.\n  Supports Google and GitHub.\n"
          "fix(bug)[check]: unrelated fix" → separate entry.

          Result: {
            "nati":  {commit containing "Replace basic auth with OAuth2."},
            "check": {"fix(bug): unrelated fix"},
          }
        """
        body = (
            "feat(auth)[nati]:\n"
            "  Replace basic auth with OAuth2.\n"
            "  Supports Google and GitHub.\n"
            "\n"
            "fix(bug)[check]: unrelated fix"
        )
        result = parse_pr_body(body, PARSERS)
        self.assertIn("nati", result)
        self.assertIn("check", result)
        nati_commit = next(iter(result["nati"]))
        # Continuation lines are stored raw (no strip) — leading spaces preserved
        self.assertIn("  Replace basic auth with OAuth2.", nati_commit)
        self.assertIn("  Supports Google and GitHub.", nati_commit)
        self.assertEqual(result["check"], {"fix(bug): unrelated fix"})

    def test_13_multiple_components_multiple_lines(self):
        """
        Checks: a body with several commit lines produces one dict entry per
                unique location, with each location holding its own commit set.

        Example:
          Input:
            "feat(auth)[nati]: add login"
            "fix(timeout)[check]: fix socket"

          Result: {
            "nati":  {"feat(auth): add login"},
            "check": {"fix(timeout): fix socket"},
          }
        """
        body = "feat(auth)[nati]: add login\nfix(timeout)[check]: fix socket"
        result = parse_pr_body(body, PARSERS)
        self.assertEqual(result, {
            "nati":  {"feat(auth): add login"},
            "check": {"fix(timeout): fix socket"},
        })

    def test_14_no_scope_bang_multiple_locations(self):
        """
        Checks: scopeless type + bang + multiple comma-separated locations all
                work together — each location gets the same commit_str (with bang).

        Example:
          Input:  "feat[nati, check]!: big change"
          "^feat" matches, brackets "[nati, check]" found immediately after.
          Brackets stripped → commit_str = "feat!: big change"
          Locations = ["nati", "check"]
          Result: {"nati": {"feat!: big change"}, "check": {"feat!: big change"}}
        """
        result = parse_pr_body("feat[nati, check]!: big change", PARSERS)
        self.assertEqual(result, {
            "nati":  {"feat!: big change"},
            "check": {"feat!: big change"},
        })


# ---------------------------------------------------------------------------
# Class 1b — TestParsePrBodyEdgeCases
# ---------------------------------------------------------------------------

class TestParsePrBodyEdgeCases(unittest.TestCase):

    def test_A_malformed_bracket_in_continuation(self):
        """
        Checks: a line with no closing bracket (e.g. "feat[nati: ...") does NOT
                match _match_line, so inside a continuation block it is collected
                as description text rather than being treated as a new commit.

        Example:
          "feat(auth)[nati]:"                         ← empty description → continuation mode
          "feat[nati: this has no closing bracket"    ← _match_line returns None → continuation text
          "fix(bug)[check]: stops continuation"       ← valid → stops collection

          Result:
            "nati"  → commit contains "feat[nati: this has no closing bracket"
            "check" → {"fix(bug): stops continuation"}
        """
        body = (
            "feat(auth)[nati]:\n"
            "feat[nati: this has no closing bracket\n"
            "fix(bug)[check]: stops continuation"
        )
        result = parse_pr_body(body, PARSERS)
        self.assertIn("nati", result)
        self.assertIn("check", result)
        nati_commit = next(iter(result["nati"]))
        self.assertIn("feat[nati: this has no closing bracket", nati_commit)
        self.assertEqual(result["check"], {"fix(bug): stops continuation"})

    def test_B_same_location_two_lines_both_in_set(self):
        """
        Checks: two different commit lines targeting the same location both appear
                in the set — they are NOT deduplicated because they are different strings.

        Example:
          "feat(auth)[nati]: add login"
          "fix(bug)[nati]: fix crash"

          Result: {"nati": {"feat(auth): add login", "fix(bug): fix crash"}}
        """
        body = "feat(auth)[nati]: add login\nfix(bug)[nati]: fix crash"
        result = parse_pr_body(body, PARSERS)
        self.assertEqual(result, {"nati": {"feat(auth): add login", "fix(bug): fix crash"}})

    def test_C_other_type_skip_still_routed(self):
        """
        Checks: parse_pr_body does NOT check the skip=True flag in parsers.
                The "other" pattern matches, brackets are stripped, and the commit
                is routed to the location. git-cliff will later skip it — not parse_pr_body.

        Example:
          "other(scope)[nati]: some no-op"
          "other" pattern matches → commit_str = "other(scope): some no-op"
          Result: {"nati": {"other(scope): some no-op"}}
        """
        result = parse_pr_body("other(scope)[nati]: some no-op", PARSERS)
        self.assertEqual(result, {"nati": {"other(scope): some no-op"}})

    def test_D_duplicate_line_deduplicated_by_set(self):
        """
        Checks: the exact same commit line appearing twice produces only one entry
                in the set — Python sets automatically deduplicate identical strings.

        Example:
          "feat(auth)[nati]: add login"   ← first occurrence
          "feat(auth)[nati]: add login"   ← identical duplicate

          Result: {"nati": {"feat(auth): add login"}}  (one entry, not two)
        """
        body = "feat(auth)[nati]: add login\nfeat(auth)[nati]: add login"
        result = parse_pr_body(body, PARSERS)
        self.assertEqual(result, {"nati": {"feat(auth): add login"}})

    def test_E_location_with_slash(self):
        """
        Checks: a location containing a slash is stored as-is in the dict key.
                Slug conversion (slash → hyphen) happens later in release(), not here.

        Example:
          "feat(auth)[plugins/docker]: add registry support"
          Location key = "plugins/docker"  (slash preserved)
          Result: {"plugins/docker": {"feat(auth): add registry support"}}
        """
        result = parse_pr_body("feat(auth)[plugins/docker]: add registry support", PARSERS)
        self.assertEqual(result, {"plugins/docker": {"feat(auth): add registry support"}})

    def test_F_spaces_around_locations_stripped(self):
        """
        Checks: spaces around each location in a comma-separated list are stripped
                via loc.strip(), producing clean location keys.

        Example:
          "feat(auth)[nati,  check  ,  base/argo ]: msg"
          raw_locs = "nati,  check  ,  base/argo "
          After split + strip: ["nati", "check", "base/argo"]
          Result: {
            "nati":     {"feat(auth): msg"},
            "check":    {"feat(auth): msg"},
            "base/argo":{"feat(auth): msg"},
          }
        """
        result = parse_pr_body("feat(auth)[nati,  check  ,  base/argo ]: msg", PARSERS)
        self.assertEqual(result, {
            "nati":      {"feat(auth): msg"},
            "check":     {"feat(auth): msg"},
            "base/argo": {"feat(auth): msg"},
        })

    def test_G_parser_with_empty_message_skipped(self):
        """
        Checks: a parser entry with message="" is skipped by _match_line
                (the "if not msg: continue" guard). The next valid parser still matches.

        Example:
          parsers = [{"message": "", "group": "X"}, <standard feat parser>]
          Input: "feat[nati]: add login"
          Empty-message parser skipped → "^feat" parser matches.
          Result: {"nati": {"feat: add login"}}
        """
        parsers_with_empty = [{"message": "", "group": "X", "bump_type": "", "skip": False}] + PARSERS
        result = parse_pr_body("feat[nati]: add login", parsers_with_empty)
        self.assertEqual(result, {"nati": {"feat: add login"}})

    def test_H_bang_empty_description_multiline(self):
        """
        Checks: bang (!) with empty description collects continuation lines.
                The bang is preserved in commit_str. Continuation is collected
                until the next commit header (always, regardless of description).

        Example:
          "feat(auth)[nati]!:"                       ← empty description after bracket removal
          "  Big breaking change description."        ← continuation line (raw, spaces preserved)
          "fix(bug)[check]: stops it"                ← stops continuation

          commit_str after join: "feat(auth)!:   Big breaking change description."
          Result:
            "nati"  → commit contains "Big breaking change description."
            "check" → {"fix(bug): stops it"}
        """
        body = (
            "feat(auth)[nati]!:\n"
            "  Big breaking change description.\n"
            "fix(bug)[check]: stops it"
        )
        result = parse_pr_body(body, PARSERS)
        self.assertIn("nati", result)
        nati_commit = next(iter(result["nati"]))
        self.assertIn("  Big breaking change description.", nati_commit)
        self.assertIn("feat(auth)!:", nati_commit)
        self.assertEqual(result["check"], {"fix(bug): stops it"})

    def test_I_trailing_comma_adds_root(self):
        """
        Checks: a trailing comma in [location, ] produces an empty string after
                split + strip, which is treated as the repo root location ("").

        Example:
          "feat(auth)[nati, ]: msg"
          raw_locs = "nati, "
          split(",") → ["nati", " "]
          strip each → ["nati", ""]   ← "" = root
          Result: {"nati": {"feat(auth): msg"}, "": {"feat(auth): msg"}}
        """
        result = parse_pr_body("feat(auth)[nati, ]: msg", PARSERS)
        self.assertEqual(result, {
            "nati": {"feat(auth): msg"},
            "":     {"feat(auth): msg"},
        })

    def test_L_nested_bracket_in_content_becomes_continuation(self):
        """
        Checks: a line with a '[' inside the bracket content (e.g. "feat[na[ti]: msg")
                fails bracket_re because [^[\\]]*  forbids '[' inside brackets.
                _match_line returns None → inside a continuation block the line is
                collected as description text, NOT treated as a new commit.

        Example:
          "feat(auth)[nati]:"              ← empty description → continuation mode
          "feat[na[ti]: malformed line"    ← bracket_re fails → becomes continuation text
          "fix(bug)[check]: stops it"      ← valid commit → stops continuation

          Result:
            "nati"  → commit contains "feat[na[ti]: malformed line"
            "check" → {"fix(bug): stops it"}
        """
        body = (
            "feat(auth)[nati]:\n"
            "feat[na[ti]: malformed line\n"
            "fix(bug)[check]: stops it"
        )
        result = parse_pr_body(body, PARSERS)
        self.assertIn("nati", result)
        nati_commit = next(iter(result["nati"]))
        self.assertIn("feat[na[ti]: malformed line", nati_commit)
        self.assertEqual(result["check"], {"fix(bug): stops it"})

    def test_M_breaking_without_scope(self):
        """
        Checks: the scopeless "^breaking" parser entry works correctly —
                type immediately followed by brackets, no parentheses needed.

        Example:
          "breaking[nati]: remove v1 api"
          "^breaking" matches at 0-8. stripped[8] = '[' ✓
          Brackets stripped → commit_str = "breaking: remove v1 api"
          Result: {"nati": {"breaking: remove v1 api"}}
        """
        result = parse_pr_body("breaking[nati]: remove v1 api", PARSERS)
        self.assertEqual(result, {"nati": {"breaking: remove v1 api"}})


    def test_N_non_empty_description_collects_continuation(self):
        """
        Checks: continuation is collected even when the commit has a non-empty
                description. Any following lines that don't match a parser pattern
                are appended to the commit string, not silently ignored.

        Example:
          "other(scope)[nati]: no-op marker"   ← has description, NOT bare ':'
          "some extra prose"                    ← not a commit → continuation
          "fix(bug)[check]: stops it"           ← commit header → stops collection

          Result:
            "nati"  → commit contains both "other(scope): no-op marker" and "some extra prose"
            "check" → {"fix(bug): stops it"}
        """
        body = (
            "other(scope)[nati]: no-op marker\n"
            "some extra prose\n"
            "fix(bug)[check]: stops it\n"
        )
        result = parse_pr_body(body, PARSERS)
        self.assertIn("nati", result)
        nati_commit = next(iter(result["nati"]))
        self.assertIn("other(scope): no-op marker", nati_commit)
        self.assertIn("some extra prose", nati_commit)
        self.assertEqual(result["check"], {"fix(bug): stops it"})

    def test_J_spaces_only_bracket_is_root(self):
        """
        Checks: bracket content consisting only of spaces strips to "" → root location,
                identical in behaviour to empty brackets [].

        Example:
          "feat(auth)[   ]: msg"
          raw_locs = "   "
          split(",") → ["   "]
          strip → [""]   ← root
          Result: {"": {"feat(auth): msg"}}
        """
        result = parse_pr_body("feat(auth)[   ]: msg", PARSERS)
        self.assertEqual(result, {"": {"feat(auth): msg"}})


# ---------------------------------------------------------------------------
# Class 2 — TestKnownCommitTypes
#
# _known_commit_types(parsers) -> set[str]
#
# Returns the raw message pattern strings from cliff.toml commit_parsers —
# no extraction, no transformation. These are the regexes used by
# _match_line to identify valid commit headers.
# ---------------------------------------------------------------------------

class TestKnownCommitTypes(unittest.TestCase):

    def test_1_returns_all_raw_patterns(self):
        """
        Checks: all 8 message patterns from PARSERS are returned as-is.

        Example:
          PARSERS has 8 entries. Each has a "message" key.
          Result must contain exactly those 8 strings, unchanged.
          e.g. "^feat\\((.*)\\" is in the result — not "feat".
        """
        result = _known_commit_types(PARSERS)
        expected = {p["message"] for p in PARSERS}
        self.assertEqual(result, expected)

    def test_2_empty_parsers_returns_empty_set(self):
        """
        Checks: empty parsers list → empty set. No patterns to return.

        Example:
          _known_commit_types([]) == set()
        """
        self.assertEqual(_known_commit_types([]), set())

    def test_3_parsers_without_message_key_skipped(self):
        """
        Checks: parser entries missing the "message" key are silently skipped.

        Example:
          parsers = [{"group": "Features"}]  ← no "message" key
          Result: set()  (nothing to add)
        """
        self.assertEqual(_known_commit_types([{"group": "Features"}]), set())


# ---------------------------------------------------------------------------
# Class 3 — TestExpandLocations
#
# _expand_locations(location_to_commits, root_path, exclude_regex) -> dict
#
# Expands wildcard locations ([*] and [base/*]) to concrete directory paths
# and applies SCOPE_EXCLUDE_REGEX to filter unwanted locations.
# ---------------------------------------------------------------------------

class TestExpandLocations(unittest.TestCase):

    def test_1_no_wildcard_no_exclude_returns_same(self):
        """
        Checks: when there are no wildcards and no exclude regex, the original
                dict is returned unchanged (fast-path — no filesystem access).

        Example:
          Input:  {"nati": {"feat: msg"}}
          No '*' in any location key. exclude_regex = "".
          Result: exactly the same dict object (identity check).
        """
        d = {"nati": {"feat: msg"}}
        result = _expand_locations(d, "/repo", "")
        self.assertIs(result, d)

    def test_2_star_wildcard_expands_to_subdirs(self):
        """
        Checks: location "*" expands to all direct subdirectories of root_path.

        Example:
          Input:  {"*": {"feat: msg"}}
          Filesystem has dirs: ["a", "b"] under /repo
          Result: {"a": {"feat: msg"}, "b": {"feat: msg"}}
          (the "*" key disappears — replaced by concrete dirs)
        """
        with patch("os.listdir", return_value=["a", "b"]), \
             patch("os.path.isdir", return_value=True):
            result = _expand_locations({"*": {"feat: msg"}}, "/repo", "")
        self.assertEqual(result, {"a": {"feat: msg"}, "b": {"feat: msg"}})

    def test_3_prefix_wildcard_expands_subdirs(self):
        """
        Checks: location "plugins/*" expands to all subdirs of root_path/plugins/.
                The prefix is prepended to each discovered dir name.

        Example:
          Input:  {"plugins/*": {"feat: msg"}}
          os.listdir("/repo/plugins") returns ["docker", "git"]
          Result: {"plugins/docker": {"feat: msg"}, "plugins/git": {"feat: msg"}}
        """
        with patch("os.listdir", return_value=["docker", "git"]), \
             patch("os.path.isdir", return_value=True):
            result = _expand_locations({"plugins/*": {"feat: msg"}}, "/repo", "")
        self.assertEqual(result, {
            "plugins/docker": {"feat: msg"},
            "plugins/git":    {"feat: msg"},
        })

    def test_4_exclude_regex_filters_wildcard_results(self):
        """
        Checks: SCOPE_EXCLUDE_REGEX is applied after wildcard expansion.
                Matching locations are silently skipped.

        Example:
          Input:  {"*": {"feat: msg"}}
          Filesystem dirs: ["nati", "docs"]
          exclude_regex = "^docs$"
          "docs" matches → skipped. "nati" does not match → kept.
          Result: {"nati": {"feat: msg"}}
        """
        with patch("os.listdir", return_value=["nati", "docs"]), \
             patch("os.path.isdir", return_value=True):
            result = _expand_locations({"*": {"feat: msg"}}, "/repo", "^docs$")
        self.assertEqual(result, {"nati": {"feat: msg"}})

    def test_5_exclude_regex_filters_explicit_location(self):
        """
        Checks: SCOPE_EXCLUDE_REGEX also applies to explicit (non-wildcard) locations.
                If someone writes [docs] in their message, and docs is excluded, it is
                silently skipped without error.

        Example:
          Input:  {"docs": {"feat: msg"}}
          exclude_regex = "^docs$"
          "docs" matches → skipped.
          Result: {}
        """
        result = _expand_locations({"docs": {"feat: msg"}}, "/repo", "^docs$")
        self.assertEqual(result, {})

    def test_6_explicit_location_with_non_wildcard_star_suffix_skipped_by_exclude(self):
        """
        Checks: an explicit location that looks like a partial wildcard
                (e.g. "plugins/*dsfsf") but does NOT end with exactly "/*"
                is treated as a literal path and passes through the else branch.
                If it matches the exclude regex it is skipped without UnboundLocalError.

        Regression test for bug where the else branch used `subdir` (only defined
        inside wildcard for-loops) instead of `display`, causing:
          UnboundLocalError: cannot access local variable 'subdir'

        Example:
          Input:  {"plugins/*dsfsf": {"feat: msg"}}
          exclude_regex = "plugins"
          Falls into else branch (does not end with "/*").
          "plugins/*dsfsf" matches regex → skipped via display variable (not subdir).
          Result: {}
        """
        result = _expand_locations({"plugins/*dsfsf": {"feat: msg"}}, "/repo", "plugins")
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Class 4 — TestRelease
#
# release() — full integration test with env vars and subprocess mocked.
#
# release() reads PLUGIN_* env vars, calls parse_pr_body, _expand_locations,
# then for each location runs git-cliff twice (bump + changelog) via
# run_command(). Tags are appended to PLUGIN_OUTPUT_TAGS_FILE if set.
# ---------------------------------------------------------------------------

class TestRelease(unittest.TestCase):

    def _run(self, message, dirs_exist=(), cliff_stdout="nati-1.1.0",
             cliff_returncode=0, cliff_stderr="", list_dirs=(),
             exclude_regex="", output_tags_file="", changelog_level="1"):
        """
        Helper: patches env vars and all filesystem/subprocess calls, then
        calls release() and returns the mock for run_command.
        changelog_level defaults to "1" (required by release()).
        Pass "" to simulate the variable being unset.

        PLUGIN_MESSAGE_FILE: release() reads the PR body from a file, not an
        env var. We write the message to a real temp file and point
        PLUGIN_MESSAGE_FILE at it so release() can open it normally.
        """
        mock_result = MagicMock()
        mock_result.returncode = cliff_returncode
        mock_result.stdout = cliff_stdout
        mock_result.stderr = cliff_stderr

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(message)
            tmp_path = f.name

        env = {
            "PLUGIN_MESSAGE_FILE":        tmp_path,
            "PLUGIN_BASE":                "/repo",
            "PLUGIN_SCOPE_EXCLUDE_REGEX": exclude_regex,
            "PLUGIN_OUTPUT_TAGS_FILE":    output_tags_file,
            "PLUGIN_VERBOSE":             "0",
            "PLUGIN_CHANGELOG_LEVEL":     changelog_level,
        }

        try:
            with patch.dict(os.environ, env, clear=False), \
                 patch("os.path.exists", return_value=True), \
                 patch("os.path.isdir", side_effect=lambda p: any(p.endswith(d) for d in dirs_exist)), \
                 patch("os.listdir", return_value=list(list_dirs)), \
                 patch.object(release_module, "run_command", return_value=mock_result) as mock_cmd:
                release()
        finally:
            os.unlink(tmp_path)

        return mock_cmd

    def test_1_single_component_first_release(self):
        """
        Checks: a single component with no existing tag triggers two git-cliff
                calls — one for --bump --bumped-version, one to generate the
                changelog — and the include-path flag names the correct component.

        Example:
          PLUGIN_MESSAGE = "feat(auth)[nati]: add login"
          PLUGIN_BASE    = "/repo"
          No existing tags (run_command for git tag returns empty stdout).
          git cliff --bump --bumped-version → "nati-1.0.0"  (first release)
          git cliff --tag 'nati-1.0.0' --output ... → writes CHANGELOG.md
          run_command called twice: once for tag-list, once for bump, once for changelog = 3 calls.
        """
        mock_cmd = self._run(
            "feat[nati]: add login",
            dirs_exist=["nati"],
            cliff_stdout="nati-1.1.0",
        )
        # tag list + bump + changelog = 3 calls
        self.assertGreaterEqual(mock_cmd.call_count, 2)
        calls_str = " ".join(str(c) for c in mock_cmd.call_args_list)
        self.assertIn("nati", calls_str)

    def test_2_missing_directory_skipped(self):
        """
        Checks: if the component directory does not exist on disk, that location
                is skipped and no git-cliff call is made for it.

        Example:
          PLUGIN_MESSAGE = "feat(auth)[ghost]: add login"
          /repo/ghost does NOT exist (isdir returns False for it)
          run_command is called only for git tag -l (to check existing tags)
          → or not called at all if early-exit happens before the tag check.
          The cliff command is definitely not called.
        """
        mock_cmd = self._run(
            "feat[ghost]: add login",
            dirs_exist=[],   # ghost does not exist
        )
        calls_str = " ".join(str(c) for c in mock_cmd.call_args_list)
        self.assertNotIn("git cliff", calls_str)

    def test_3_empty_message_does_nothing(self):
        """
        Checks: empty PLUGIN_MESSAGE → parse_pr_body returns {} → release()
                prints "No release commits detected" and exits early.
                run_command is never called.

        Example:
          PLUGIN_MESSAGE = ""
          Result: run_command.call_count == 0
        """
        mock_cmd = self._run("", dirs_exist=[])
        mock_cmd.assert_not_called()

    def test_4_cliff_failure_does_not_crash(self):
        """
        Checks: if git-cliff returns a non-zero exit code for the changelog step,
                release() prints an error message but does NOT raise an exception
                (it continues to the next component or exits gracefully).

        Example:
          PLUGIN_MESSAGE = "feat(auth)[nati]: add login"
          git cliff changelog returncode = 1, stderr = "some error"
          release() prints ">>> ERROR generating changelog..." and continues.
          No exception is raised.
        """
        try:
            self._run(
                "feat[nati]: add login",
                dirs_exist=["nati"],
                cliff_stdout="nati-1.1.0",
                cliff_returncode=1,
                cliff_stderr="fatal: not a git repo",
            )
        except Exception as e:
            self.fail(f"release() raised an exception on cliff failure: {e}")


# ---------------------------------------------------------------------------
# Class 4b — TestChangelogLevel
#
# parse_pr_body(body, parsers, changelog_level=N) level-enforcement tests.
#
# PLUGIN_CHANGELOG_LEVEL controls which location depths are accepted.
# The formula is:
#   level 0  → only root (empty string location)
#   level N  → location must have exactly N-1 forward slashes
#              e.g. level 1 → "nati" (0 slashes)
#                   level 2 → "plugins/docker" (1 slash)
#
# Tests 7 and 8 verify that release() itself enforces the variable as required.
# ---------------------------------------------------------------------------

class TestChangelogLevel(unittest.TestCase):

    def test_1_level1_accepts_toplevel_rejects_nested(self):
        """
        Checks: changelog_level=1 accepts locations with 0 slashes (top-level dirs)
                and skips locations with 1+ slashes (nested paths).

        Why this matters: the most common monorepo setup — all components sit
        directly under PLUGIN_BASE. Setting level=1 enforces that no nested path
        can accidentally trigger a release.

        Body:
          feat[nati]: add dashboard       ← "nati"          has 0 slashes → level 1 → ACCEPT
          fix[plugins/docker]: fix socket ← "plugins/docker" has 1 slash  → level 1 expects 0 → SKIP

        Expected: {"nati": {"feat: add dashboard"}}
                  "plugins/docker" must not appear.
        """
        body = (
            "feat[nati]: add dashboard\n"
            "fix[plugins/docker]: fix socket\n"
        )
        result = parse_pr_body(body, PARSERS, changelog_level=1)
        self.assertIn("nati", result)
        self.assertEqual(result["nati"], {"feat: add dashboard"})
        self.assertNotIn("plugins/docker", result)

    def test_2_level2_accepts_nested_rejects_toplevel(self):
        """
        Checks: changelog_level=2 accepts locations with exactly 1 slash and
                skips locations with 0 slashes.

        Why this matters: a mono-of-monorepo layout where all versioned components
        live one level deep (e.g. plugins/docker, plugins/git). Level=2 ensures
        someone cannot accidentally release the "plugins" parent by writing [plugins].

        Body:
          feat[plugins/docker]: add auth  ← "plugins/docker" has 1 slash → level 2 → ACCEPT
          fix[nati]: fix crash            ← "nati"          has 0 slashes → level 2 expects 1 → SKIP

        Expected: {"plugins/docker": {"feat: add auth"}}
                  "nati" must not appear.
        """
        body = (
            "feat[plugins/docker]: add auth\n"
            "fix[nati]: fix crash\n"
        )
        result = parse_pr_body(body, PARSERS, changelog_level=2)
        self.assertIn("plugins/docker", result)
        self.assertEqual(result["plugins/docker"], {"feat: add auth"})
        self.assertNotIn("nati", result)

    def test_3_level0_accepts_root_only(self):
        """
        Checks: changelog_level=0 accepts ONLY the empty-bracket root location [].
                Any non-empty location is skipped.

        Why this matters: a single-component repo where only the root is ever
        released. Level=0 prevents accidentally triggering a nested release.

        Body:
          feat[]: release root   ← empty string → root → ACCEPT
          feat[nati]: add thing  ← "nati" non-empty → SKIP

        Expected: {"": {"feat: release root"}}
                  "nati" must not appear.
        """
        body = (
            "feat[]: release root\n"
            "feat[nati]: add thing\n"
        )
        result = parse_pr_body(body, PARSERS, changelog_level=0)
        self.assertIn("", result)
        self.assertEqual(result[""], {"feat: release root"})
        self.assertNotIn("nati", result)

    def test_4_multilocation_skipped_if_any_location_fails(self):
        """
        Checks: if ANY location in a comma-separated list fails the level check,
                the ENTIRE line is skipped — even locations that would individually pass.

        Why this matters: a line like feat[nati, plugins/docker] targets two
        components at different depths. Partially accepting it would be wrong —
        either the whole line is valid for this repo's layout or none of it is.

        Body (changelog_level=1):
          feat[nati, plugins/docker]: shared change
          ↑ "nati":          0 slashes → ok for level 1
          ↑ "plugins/docker": 1 slash  → FAIL for level 1 → whole line skipped

        Expected: {} — neither nati nor plugins/docker appears.
        """
        body = "feat[nati, plugins/docker]: shared change\n"
        result = parse_pr_body(body, PARSERS, changelog_level=1)
        self.assertEqual(result, {})

    def test_5_failing_line_ends_previous_continuation(self):
        """
        Checks: a level-failing commit line acts as a commit boundary — it stops
                the continuation collection of the preceding commit (because
                _match_line returns truthy for any valid commit structure, regardless
                of level), finalises that commit with its accumulated lines, and is
                then skipped itself.

        Why this matters: without this behaviour, the continuation lines of the
        first commit would "bleed" past the rejected line and potentially merge
        with the next commit's body.

        Body (changelog_level=2):
          feat[plugins/docker]:          ← ACCEPT, starts continuation
            description line 1           ← continuation
            description line 2           ← continuation
          fix[nati]: wrong level         ← _match_line matches → BREAKS inner loop
                                            → first commit finalised with its 2 lines
                                            → level check fails (0 slashes, expected 1) → SKIP
          feat[plugins/auth]: next       ← ACCEPT, starts fresh

        Expected:
          "plugins/docker" commit contains both description lines
          "plugins/auth"   commit = "feat: next"
          "nati" absent
        """
        body = (
            "feat[plugins/docker]:\n"
            "  description line 1\n"
            "  description line 2\n"
            "fix[nati]: wrong level\n"
            "feat[plugins/auth]: next\n"
        )
        result = parse_pr_body(body, PARSERS, changelog_level=2)

        self.assertIn("plugins/docker", result)
        docker_commit = next(iter(result["plugins/docker"]))
        self.assertIn("  description line 1", docker_commit)
        self.assertIn("  description line 2", docker_commit)

        self.assertIn("plugins/auth", result)
        self.assertEqual(result["plugins/auth"], {"feat: next"})

        self.assertNotIn("nati", result)

    def test_6_release_missing_changelog_level_exits_early(self):
        """
        Checks: when PLUGIN_CHANGELOG_LEVEL is not set (empty string is falsy),
                release() prints an error and returns before calling run_command.

        Why this matters: PLUGIN_CHANGELOG_LEVEL is required. Without it the plugin
        has no idea what depth the user expects, so running silently would be wrong.
        The empty-string check mirrors how pipeline tools set "not configured" vars.

        Expected: run_command never called.
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "nati-1.1.0"
        mock_result.stderr = ""

        env = {
            # PLUGIN_MESSAGE_FILE is not reached — release() exits before it
            # when PLUGIN_CHANGELOG_LEVEL is unset.
            "PLUGIN_MESSAGE_FILE":        "dummy.txt",
            "PLUGIN_BASE":                "/repo",
            "PLUGIN_SCOPE_EXCLUDE_REGEX": "",
            "PLUGIN_OUTPUT_TAGS_FILE":    "",
            "PLUGIN_VERBOSE":             "0",
            "PLUGIN_CHANGELOG_LEVEL":     "",   # empty → falsy → triggers required-var error
        }
        with patch.dict(os.environ, env, clear=False), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isdir", return_value=True), \
             patch.object(release_module, "run_command", return_value=mock_result) as mock_cmd:
            release()

        mock_cmd.assert_not_called()

    def test_7_release_invalid_changelog_level_exits_early(self):
        """
        Checks: when PLUGIN_CHANGELOG_LEVEL is set to a non-integer string,
                int() raises ValueError, which is caught, an error is printed,
                and release() returns before calling run_command.

        Why this matters: a typo like PLUGIN_CHANGELOG_LEVEL=one or a copy-paste
        mistake should fail loudly rather than crashing with an unhandled exception
        deep inside the loop.

        Expected: run_command never called.
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "nati-1.1.0"
        mock_result.stderr = ""

        env = {
            # PLUGIN_MESSAGE_FILE is not reached — release() exits before it
            # when PLUGIN_CHANGELOG_LEVEL is non-integer.
            "PLUGIN_MESSAGE_FILE":        "dummy.txt",
            "PLUGIN_BASE":                "/repo",
            "PLUGIN_SCOPE_EXCLUDE_REGEX": "",
            "PLUGIN_OUTPUT_TAGS_FILE":    "",
            "PLUGIN_VERBOSE":             "0",
            "PLUGIN_CHANGELOG_LEVEL":     "abc",  # non-integer → int() raises ValueError
        }
        with patch.dict(os.environ, env, clear=False), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isdir", return_value=True), \
             patch.object(release_module, "run_command", return_value=mock_result) as mock_cmd:
            release()

        mock_cmd.assert_not_called()


# ---------------------------------------------------------------------------
# Class 5 — TestCliffTomlResolution
#
# Verifies the three-tier cliff.toml lookup in release():
#   1. PLUGIN_CLIFF_TOML explicitly set → use that path
#   2. ./cliff.toml exists in the working directory → use it
#   3. Neither → fall back to the bundled cliff.toml next to release.py
# ---------------------------------------------------------------------------

class TestCliffTomlResolution(unittest.TestCase):

    def _run_with_toml_env(self, cliff_toml_env, workspace_has_cliff):
        """
        Calls release() and returns the --config path used in git-cliff commands.
        cliff_toml_env  : value for PLUGIN_CLIFF_TOML ("" means not set)
        workspace_has_cliff : whether ./cliff.toml exists in the working dir
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "nati-1.1.0"
        mock_result.stderr = ""

        bundled = os.path.join(os.path.dirname(_src_path), "cliff.toml")

        def fake_exists(p):
            if p == "./cliff.toml":
                return workspace_has_cliff
            return True  # everything else (dirs, changelog, etc.) exists

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("feat[nati]: add login")
            tmp_path = f.name

        env = {
            "PLUGIN_MESSAGE_FILE":        tmp_path,
            "PLUGIN_BASE":                "/repo",
            "PLUGIN_SCOPE_EXCLUDE_REGEX": "",
            "PLUGIN_OUTPUT_TAGS_FILE":    "",
            "PLUGIN_VERBOSE":             "0",
            "PLUGIN_CHANGELOG_LEVEL":     "1",
        }
        if cliff_toml_env:
            env["PLUGIN_CLIFF_TOML"] = cliff_toml_env
        else:
            env.pop("PLUGIN_CLIFF_TOML", None)

        try:
            with patch.dict(os.environ, env, clear=False), \
                 patch("os.path.exists", side_effect=fake_exists), \
                 patch("os.path.isdir", side_effect=lambda p: p.endswith("nati")), \
                 patch("os.listdir", return_value=[]), \
                 patch.object(release_module, "load_cliff_parsers", return_value=(PARSERS, {})), \
                 patch.object(release_module, "run_command", return_value=mock_result) as mock_cmd:
                release()
        finally:
            os.unlink(tmp_path)

        calls_str = " ".join(str(c) for c in mock_cmd.call_args_list)
        # extract the --config <path> value from the recorded calls
        import re as _re
        m = _re.search(r"--config\s+(\S+)", calls_str)
        return m.group(1) if m else None

    def test_1_explicit_plugin_cliff_toml_used(self):
        """
        Checks: when PLUGIN_CLIFF_TOML is set, that path is passed to git-cliff
                regardless of whether ./cliff.toml exists.
        """
        used = self._run_with_toml_env("/custom/my.toml", workspace_has_cliff=True)
        self.assertEqual(used, "/custom/my.toml")

    def test_2_workspace_cliff_toml_used_when_present(self):
        """
        Checks: when PLUGIN_CLIFF_TOML is not set but ./cliff.toml exists,
                git-cliff is invoked with ./cliff.toml.
        """
        used = self._run_with_toml_env("", workspace_has_cliff=True)
        self.assertEqual(used, "./cliff.toml")

    def test_3_bundled_cliff_toml_used_as_last_resort(self):
        """
        Checks: when PLUGIN_CLIFF_TOML is not set and ./cliff.toml is absent,
                git-cliff is invoked with the bundled cliff.toml (next to release.py).
        """
        bundled = os.path.join(os.path.dirname(_src_path), "cliff.toml")
        used = self._run_with_toml_env("", workspace_has_cliff=False)
        self.assertEqual(used, bundled)


if __name__ == "__main__":
    unittest.main()
