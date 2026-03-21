#!/usr/bin/env bash
set -euo pipefail

IMAGE="netanelzucaim123/python-git-cliff:latest"
WORKSPACE="$(cd "$(dirname "$0")" && pwd)"
PASS=0
FAIL=0

setup_tag() {
  git -C "$WORKSPACE" tag "$1" 2>/dev/null || true
}

teardown_tags() {
  git -C "$WORKSPACE" tag -l "$1" | xargs -r git -C "$WORKSPACE" tag -d >/dev/null 2>&1 || true
}

# Run release.py in docker with PLUGIN_BASE="." and default SCOPE_DEPTH=1
run_release() {
  docker run --rm \
    -v "$WORKSPACE:/workspace" \
    -w /workspace \
    -e PLUGIN_BASE="." \
    -e "PR_BODY=$1" \
    "$IMAGE" \
    sh -c "git config --global safe.directory '*' && python3 release.py" 2>&1
}

# Run release.py with full control over env vars.
# Usage: run_release_ex <pr_body> [VAR=VALUE ...]
run_release_ex() {
  local pr_body="$1"; shift
  local env_args=(-e "PR_BODY=$pr_body")
  for kv in "$@"; do
    env_args+=(-e "$kv")
  done
  docker run --rm \
    -v "$WORKSPACE:/workspace" \
    -w /workspace \
    "${env_args[@]}" \
    "$IMAGE" \
    sh -c "git config --global safe.directory '*' && python3 release.py" 2>&1
}

assert_contains() {
  local name="$1" output="$2" expected="$3"
  if echo "$output" | grep -qF "$expected"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    echo "        Expected to find: '$expected'"
    echo "$output" | sed 's/^/          /'
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local name="$1" output="$2" unexpected="$3"
  if ! echo "$output" | grep -qF "$unexpected"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    echo "        Expected NOT to find: '$unexpected'"
    echo "$output" | sed 's/^/          /'
    FAIL=$((FAIL + 1))
  fi
}

assert_tag_exists() {
  local name="$1" tag="$2"
  if git -C "$WORKSPACE" tag -l "$tag" | grep -qF "$tag"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    echo "        Expected git tag '$tag' to exist but it does not"
    FAIL=$((FAIL + 1))
  fi
}

assert_tag_absent() {
  local name="$1" tag_pattern="$2"
  local count
  count=$(git -C "$WORKSPACE" tag -l "$tag_pattern" | wc -l)
  if [ "$count" -eq 0 ]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    echo "        Expected no tag matching '$tag_pattern' but found: $(git -C "$WORKSPACE" tag -l "$tag_pattern")"
    FAIL=$((FAIL + 1))
  fi
}

cleanup() {
  echo "--- Cleaning up tags and changelogs from previous run ---"
  for pattern in \
    "plugins-netanel-v*" \
    "plugins-harel-v*" \
    "plugins-lagziel-v*" \
    "plugins-kaniko-monorepo-v*" \
    "plugins-kaniko-monorepo-cliff-v*" \
    "netanel-v*" \
    "harel-v*" \
    "lagziel-v*" \
    "kaniko-monorepo-v*" \
    "plugins-v*" \
    "v*"; do
    teardown_tags "$pattern"
  done
  rm -f \
    "$WORKSPACE/plugins/netanel/CHANGELOG.md" \
    "$WORKSPACE/plugins/harel/CHANGELOG.md" \
    "$WORKSPACE/plugins/lagziel/CHANGELOG.md" \
    "$WORKSPACE/plugins/kaniko-monorepo/CHANGELOG.md" \
    "$WORKSPACE/plugins/kaniko-monorepo-cliff/CHANGELOG.md" \
    "$WORKSPACE/plugins/CHANGELOG.md" \
    "$WORKSPACE/CHANGELOG.md"
  echo ""
}

cleanup

echo "================================================"
echo " release.py Docker Integration Tests"
echo "================================================"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: Depth=1 — Monorepo (PLUGIN_BASE=./plugins, single-word scopes)
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 1: Depth=1 Monorepo"
echo "└─────────────────────────────────────────────"
echo ""

# TC1: First release -- no existing tag
echo "TC1: First release -- new component gets v1.0.0"
out=$(run_release_ex "feat(netanel): add dashboard" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "output reports v1.0.0" "$out" "netanel-v1.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag netanel-v1.0.0 exists" "netanel-v1.0.0"
echo ""

# TC2: feat bumps minor -- builds on TC1's persisted tag
echo "TC2: feat bumps minor (1.0.0 -> 1.1.0)"
out=$(run_release_ex "feat(netanel): add sidebar" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "output reports v1.1.0" "$out" "netanel-v1.1.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag netanel-v1.1.0 exists" "netanel-v1.1.0"
echo ""

# TC3a: lagziel first release
echo "TC3a: lagziel first release -> v1.0.0"
out=$(run_release_ex "feat(lagziel): initial release" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "output reports lagziel v1.0.0" "$out" "lagziel-v1.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag lagziel-v1.0.0 exists" "lagziel-v1.0.0"
echo ""

echo "TC3b: fix bumps patch (1.0.0 -> 1.0.1)"
out=$(run_release_ex "fix(lagziel): resolve crash on startup" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "output reports v1.0.1" "$out" "lagziel-v1.0.1"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag lagziel-v1.0.1 exists" "lagziel-v1.0.1"
echo ""

# TC4: Multi-scope explosion -- two components in one line
echo "TC4: Multi-scope explosion -- two components released from one line"
out=$(run_release_ex "feat(harel, kaniko-monorepo): shared auth update" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "output reports harel v1.0.0" "$out" "harel-v1.0.0"
assert_contains "output reports kaniko-monorepo v1.0.0" "$out" "kaniko-monorepo-v1.0.0"
assert_tag_exists "git tag harel-v1.0.0 exists" "harel-v1.0.0"
assert_tag_exists "git tag kaniko-monorepo-v1.0.0 exists" "kaniko-monorepo-v1.0.0"
echo ""

# TC5: Non-existent directory is skipped
echo "TC5: Non-existent directory -- skipped gracefully"
out=$(run_release_ex "feat(nonexistent): some change" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "skips missing directory" "$out" "SKIP"
assert_not_contains "no crash" "$out" "Traceback"
echo ""

# TC6: No conventional commits
echo "TC6: No conventional commits in PR body -- exits cleanly"
out=$(run_release_ex "just a random PR description with no commits" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "no commits detected" "$out" "No Conventional Commits"
echo ""

# TC7: feat bumps minor on existing component
echo "TC7: feat bumps minor on existing component (1.0.0 -> 1.1.0)"
out=$(run_release_ex "feat(harel): add retry logic" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "output reports harel v1.1.0" "$out" "harel-v1.1.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag harel-v1.1.0 exists" "harel-v1.1.0"
echo ""

# TC-BREAK: breaking type triggers major bump
echo "TC-BREAK: breaking(scope) triggers major bump (1.1.0 -> 2.0.0)"
out=$(run_release_ex "breaking(harel): remove legacy api" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_contains "output reports harel v2.0.0" "$out" "harel-v2.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag harel-v2.0.0 exists" "harel-v2.0.0"
echo ""

# TC8: Duplicate lines deduplicated
echo "TC8: Duplicate PR lines -- processed only once"
out=$(run_release_ex "$(printf 'feat(harel): add thing\nfeat(harel): add thing')" "PLUGIN_BASE=./plugins" "SCOPE_DEPTH=1")
assert_tag_exists "git tag harel-v2.1.0 exists" "harel-v2.1.0"
count=$(echo "$out" | grep -c "SUCCESS.*harel" || true)
if [ "$count" -eq 1 ]; then
  echo "  PASS: processed exactly once (count=$count)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected 1 SUCCESS, got $count"
  echo "$out" | sed 's/^/          /'
  FAIL=$((FAIL + 1))
fi
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1b: Depth=1 — Flat Monorepo (single-level scope names)
#
# True depth=1 scenario: each top-level folder under PLUGIN_BASE is one
# component.  The scope is a bare name (e.g. "plugins"), the resulting tag
# has no slash in it (e.g. plugins-v1.0.0).
#
# We use the repo's own "plugins/" directory as the single component since it
# is the only non-hidden top-level directory in the workspace.
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 1b: Depth=1 Flat Monorepo (single-level scope)"
echo "└─────────────────────────────────────────────"
echo ""

# TC-D1-1: First release — no prior plugins-v* tag → always v1.0.0
echo "TC-D1-1: Flat monorepo first release -- no prior tag → plugins-v1.0.0"
out=$(run_release_ex "feat(plugins): add initial structure" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1")
assert_contains "output reports plugins-v1.0.0" "$out" "plugins-v1.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "plugins-v1.0.0 exists" "plugins-v1.0.0"
echo ""

# TC-D1-2: Second release creates a new higher tag (exact version depends on git history)
echo "TC-D1-2: Flat monorepo second release -- new plugins-v* tag created"
out=$(run_release_ex "feat(plugins): add retry logic" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1")
assert_contains "tag created with plugins-v prefix" "$out" "plugins-v"
assert_contains "output reports SUCCESS" "$out" "SUCCESS"
assert_not_contains "no errors" "$out" "ERROR"
# Extract the created tag from output and verify it exists in git
created_tag=$(echo "$out" | grep -oE 'plugins-v[0-9]+\.[0-9]+\.[0-9]+' | tail -1)
if [ -n "$created_tag" ]; then
  assert_tag_exists "git tag $created_tag exists" "$created_tag"
fi
echo ""

# TC-D1-3: Slug format — single-level scope produces single-word-v* tag (no nested hyphens)
echo "TC-D1-3: Single-level scope slug -- tag has no slash-derived separator"
# Scope 'plugins' → slug 'plugins' → tag 'plugins-v*'   (NOT 'plugins-something-v*')
tag_count=$(git -C "$WORKSPACE" tag -l 'plugins-v*' | wc -l)
if [ "$tag_count" -ge 1 ]; then
  echo "  PASS: plugins-v* tags exist (single-word slug confirmed)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: no plugins-v* tags found"
  FAIL=$((FAIL + 1))
fi
# Confirm depth=1 nested scope (two-word slug) tags are NOT created here
assert_tag_absent "no plugins-plugins-v* (double nesting)" "plugins-plugins-v*"
echo ""

# TC-D1-4: feat(*) wildcard at depth=1 discovers all top-level dirs
#           Exclude __pycache__ and hidden dirs; only 'plugins' remains
echo "TC-D1-4: feat(*) wildcard at depth=1 -- discovers top-level component, creates tag"
out=$(run_release_ex "feat(*): global upgrade" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1" \
  "SCOPE_EXCLUDE_REGEX=^__pycache__$|^\\..*")
assert_contains "plugins released via wildcard" "$out" "plugins-v"
assert_contains "output reports SUCCESS" "$out" "SUCCESS"
assert_not_contains "no crash" "$out" "Traceback"
echo ""

# TC-D1-5: CHANGELOG.md written inside the component dir (plugins/CHANGELOG.md)
echo "TC-D1-5: Flat monorepo CHANGELOG.md written inside component directory"
teardown_tags "plugins-v*"
rm -f "$WORKSPACE/plugins/CHANGELOG.md"
out=$(run_release_ex "feat(plugins): add metrics endpoint" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1")
assert_contains "output reports SUCCESS" "$out" "SUCCESS"
if [ -f "$WORKSPACE/plugins/CHANGELOG.md" ]; then
  echo "  PASS: plugins/CHANGELOG.md created inside component dir"
  PASS=$((PASS + 1))
else
  echo "  FAIL: plugins/CHANGELOG.md not found"
  FAIL=$((FAIL + 1))
fi
teardown_tags "plugins-v*"
rm -f "$WORKSPACE/plugins/CHANGELOG.md"
echo ""

# TC-D1-6: Scope not on disk at depth=1 -- skipped gracefully
echo "TC-D1-6: Flat monorepo -- unknown scope skipped, no crash"
out=$(run_release_ex "feat(ghostservice): add feature" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1")
assert_contains "skips missing dir" "$out" "SKIP"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
assert_not_contains "no crash" "$out" "Traceback"
echo ""

# TC-D1-7: Exclude regex works for single-level scope names
echo "TC-D1-7: Flat monorepo -- single-level scope excluded by regex, no release"
out=$(run_release_ex "feat(plugins): add feature" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1" \
  "SCOPE_EXCLUDE_REGEX=^plugins$")
assert_contains "output says SKIP" "$out" "SKIP"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
assert_tag_absent "no new plugins-v* tag" "plugins-v1.*"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: SCOPE_EXCLUDE_REGEX
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 2: SCOPE_EXCLUDE_REGEX"
echo "└─────────────────────────────────────────────"
echo ""

# TC-EXCL-1: Explicit scope excluded → no tag created
echo "TC-EXCL-1: Explicit scope excluded by regex -- no tag created"
out=$(run_release_ex "feat(plugins/lagziel): add thing" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1" \
  "SCOPE_EXCLUDE_REGEX=^plugins/lagziel$")
assert_contains "output says SKIP" "$out" "SKIP"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
# plugins-lagziel still at v1.0.1 (unchanged)
assert_tag_absent "no new lagziel tag created" "plugins-lagziel-v1.1.*"
echo ""

# TC-EXCL-2: Multi-scope explicit where one scope is excluded
echo "TC-EXCL-2: Multi-scope commit with one excluded scope -- only non-excluded released"
teardown_tags "plugins-netanel-v*"
out=$(run_release_ex "feat(plugins/netanel, plugins/lagziel): upgrade" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1" \
  "SCOPE_EXCLUDE_REGEX=^plugins/lagziel$")
assert_contains "netanel released" "$out" "plugins-netanel-v1.0.0"
assert_contains "lagziel skipped" "$out" "SKIP"
assert_tag_exists "plugins-netanel-v1.0.0 exists" "plugins-netanel-v1.0.0"
assert_tag_absent "no new lagziel tag" "plugins-lagziel-v1.1.*"
echo ""

# TC-EXCL-3: All scopes excluded -- no releases, clean exit
echo "TC-EXCL-3: All scopes excluded -- no releases at all"
out=$(run_release_ex "feat(plugins/harel): add thing" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1" \
  "SCOPE_EXCLUDE_REGEX=^plugins/harel$")
assert_contains "output says SKIP" "$out" "SKIP"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
assert_not_contains "no crash" "$out" "Traceback"
echo ""

# TC-EXCL-4: Regex anchoring -- partial match also excludes
echo "TC-EXCL-4: Regex partial match also excludes"
out=$(run_release_ex "feat(plugins/lagziel): add thing" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=1" \
  "SCOPE_EXCLUDE_REGEX=lagziel")
assert_contains "output says SKIP" "$out" "SKIP"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: Depth=1 Wildcard
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 3: Depth=1 Wildcard"
echo "└─────────────────────────────────────────────"
echo ""

# TC-WC1: feat(plugins/*) with depth=2 and PLUGIN_BASE=. → releases all plugins
echo "TC-WC1: feat(plugins/*) at depth=2 -- all plugins subdirs released"
teardown_tags "plugins-netanel-v*"
teardown_tags "plugins-harel-v*"
teardown_tags "plugins-lagziel-v*"
teardown_tags "plugins-kaniko-monorepo-v*"
teardown_tags "plugins-kaniko-monorepo-cliff-v*"
out=$(run_release_ex "feat(plugins/*): global upgrade" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=2")
assert_contains "netanel released" "$out" "plugins-netanel-v1.0.0"
assert_contains "harel released" "$out" "plugins-harel-v1.0.0"
assert_not_contains "no crash" "$out" "Traceback"
assert_tag_exists "plugins-netanel-v1.0.0 tag exists" "plugins-netanel-v1.0.0"
assert_tag_exists "plugins-harel-v1.0.0 tag exists" "plugins-harel-v1.0.0"
echo ""

# TC-WC2: feat(*) with no matching dirs -- clean exit
echo "TC-WC2: feat(*) with PLUGIN_BASE pointing to empty dir -- no releases"
out=$(run_release_ex "feat(*): upgrade all" \
  "PLUGIN_BASE=/nonexistent" \
  "SCOPE_DEPTH=1")
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
assert_not_contains "no crash" "$out" "Traceback"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: Depth=2 — Nested Monorepo
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 4: Depth=2 Nested Monorepo"
echo "└─────────────────────────────────────────────"
echo ""

# TC-D2-1: Explicit two-level scope at depth=2
echo "TC-D2-1: Explicit nested scope at depth=2 -- creates plugins-netanel-v* tag"
teardown_tags "plugins-netanel-v*"
out=$(run_release_ex "feat(plugins/netanel): upgrade" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=2")
assert_contains "output reports success" "$out" "plugins-netanel-v1.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "plugins-netanel-v1.0.0 tag exists" "plugins-netanel-v1.0.0"
echo ""

# TC-D2-2: Bare feat(*) at depth=2 is invalid -- logs warning, no tags created
echo "TC-D2-2: feat(*) at depth=2 is invalid -- warning logged, no releases"
prev_tag_count=$(git -C "$WORKSPACE" tag -l | wc -l)
out=$(run_release_ex "feat(*): upgrade everything" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=2")
assert_contains "warning logged" "$out" "WARN"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
new_tag_count=$(git -C "$WORKSPACE" tag -l | wc -l)
if [ "$new_tag_count" -eq "$prev_tag_count" ]; then
  echo "  PASS: tag count unchanged ($new_tag_count)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected $prev_tag_count tags, now have $new_tag_count"
  FAIL=$((FAIL + 1))
fi
echo ""

# TC-D2-3: Group wildcard feat(plugins/*) at depth=2 -- expands to all plugins
echo "TC-D2-3: feat(plugins/*) at depth=2 -- all plugins subdirs released"
teardown_tags "plugins-netanel-v*"
teardown_tags "plugins-harel-v*"
teardown_tags "plugins-lagziel-v*"
teardown_tags "plugins-kaniko-monorepo-v*"
teardown_tags "plugins-kaniko-monorepo-cliff-v*"
out=$(run_release_ex "feat(plugins/*): global plugin upgrade" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=2")
assert_contains "netanel released" "$out" "plugins-netanel-v1.0.0"
assert_contains "harel released" "$out" "plugins-harel-v1.0.0"
assert_tag_exists "plugins-netanel-v1.0.0" "plugins-netanel-v1.0.0"
assert_tag_exists "plugins-harel-v1.0.0" "plugins-harel-v1.0.0"
echo ""

# TC-D2-4: Group wildcard with exclude at depth=2
echo "TC-D2-4: feat(plugins/*) with exclude -- lagziel skipped, others released"
teardown_tags "plugins-netanel-v*"
teardown_tags "plugins-harel-v*"
teardown_tags "plugins-lagziel-v*"
teardown_tags "plugins-kaniko-monorepo-v*"
teardown_tags "plugins-kaniko-monorepo-cliff-v*"
out=$(run_release_ex "feat(plugins/*): upgrade" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=2" \
  "SCOPE_EXCLUDE_REGEX=^plugins/lagziel$|^plugins/kaniko-monorepo$|^plugins/kaniko-monorepo-cliff$")
assert_contains "netanel released" "$out" "plugins-netanel-v1.0.0"
assert_contains "harel released" "$out" "plugins-harel-v1.0.0"
assert_contains "lagziel skipped" "$out" "SKIP"
assert_tag_absent "lagziel not tagged" "plugins-lagziel-v*"
echo ""

# TC-D2-5: Missing nested dir at depth=2 is skipped gracefully
echo "TC-D2-5: Missing nested dir at depth=2 -- skipped, no crash"
out=$(run_release_ex "feat(plugins/ghostplugin): upgrade" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=2")
assert_contains "skips missing dir" "$out" "SKIP"
assert_not_contains "no crash" "$out" "Traceback"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: Depth=0 — Polyrepo
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 5: Depth=0 Polyrepo"
echo "└─────────────────────────────────────────────"
echo ""

# TC-D0-1: First polyrepo release -- no existing v* tag → v1.0.0
echo "TC-D0-1: Polyrepo first release -- creates v1.0.0"
teardown_tags "v*"
out=$(run_release_ex "feat: add user authentication" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=0")
assert_contains "output reports v1.0.0" "$out" "v1.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag v1.0.0 exists" "v1.0.0"
echo ""

# TC-D0-2: feat bumps minor
echo "TC-D0-2: Polyrepo feat bumps minor (v1.0.0 -> v1.1.0)"
out=$(run_release_ex "feat: add new dashboard" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=0")
assert_contains "output reports v1.1.0" "$out" "v1.1.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag v1.1.0 exists" "v1.1.0"
echo ""

# TC-D0-3: fix bumps patch
echo "TC-D0-3: Polyrepo fix bumps patch (v1.1.0 -> v1.1.1)"
out=$(run_release_ex "fix: resolve null pointer" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=0")
assert_contains "output reports v1.1.1" "$out" "v1.1.1"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag v1.1.1 exists" "v1.1.1"
echo ""

# TC-D0-4: breaking triggers major bump
echo "TC-D0-4: Polyrepo breaking triggers major bump (v1.1.1 -> v2.0.0)"
out=$(run_release_ex "breaking: drop support for Python 3.8" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=0")
assert_contains "output reports v2.0.0" "$out" "v2.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag v2.0.0 exists" "v2.0.0"
echo ""

# TC-D0-5: Scoped commit at depth=0 is ignored -- no release
echo "TC-D0-5: Scoped commit (feat(nati): msg) at depth=0 -- ignored, no release"
prev_tag_count=$(git -C "$WORKSPACE" tag -l "v*" | wc -l)
out=$(run_release_ex "feat(nati): add dashboard" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=0")
assert_contains "no release detected" "$out" "No release commits"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
new_tag_count=$(git -C "$WORKSPACE" tag -l "v*" | wc -l)
if [ "$new_tag_count" -eq "$prev_tag_count" ]; then
  echo "  PASS: no new v* tags created"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected $prev_tag_count v* tags, now have $new_tag_count"
  FAIL=$((FAIL + 1))
fi
echo ""

# TC-D0-6: Empty PR body at depth=0 -- no release
echo "TC-D0-6: Empty PR body at depth=0 -- no release"
out=$(run_release_ex "" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=0")
assert_contains "no release detected" "$out" "No release commits"
assert_not_contains "no SUCCESS" "$out" "SUCCESS"
echo ""

# TC-D0-7: CHANGELOG.md is written at root
echo "TC-D0-7: Polyrepo changelog written at PLUGIN_BASE root"
out=$(run_release_ex "feat: add metrics endpoint" \
  "PLUGIN_BASE=." \
  "SCOPE_DEPTH=0")
assert_contains "output reports success" "$out" "SUCCESS"
if [ -f "$WORKSPACE/CHANGELOG.md" ]; then
  echo "  PASS: CHANGELOG.md exists at repo root"
  PASS=$((PASS + 1))
else
  echo "  FAIL: CHANGELOG.md not found at repo root"
  FAIL=$((FAIL + 1))
fi
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: Scope deduplication (depth=1)
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 6: Scope deduplication"
echo "└─────────────────────────────────────────────"
echo ""

teardown_tags "plugins-lagziel-v*"
setup_tag "plugins-lagziel-v1.0.0"

# TC-DEDUP-1: breaking wins over feat for same scope
echo "TC-DEDUP-1: breaking + feat for same scope -- breaking wins (major bump)"
out=$(run_release "$(printf 'feat(plugins/lagziel): add feature\nbreaking(plugins/lagziel): remove api')")
assert_contains "major bump (v2.0.0)" "$out" "plugins-lagziel-v2.0.0"
assert_not_contains "no minor bump (v1.1.0)" "$out" "plugins-lagziel-v1.1.0"
count=$(echo "$out" | grep -c "SUCCESS.*plugins-lagziel" || true)
if [ "$count" -eq 1 ]; then
  echo "  PASS: processed exactly once (count=$count)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected 1 SUCCESS, got $count"
  echo "$out" | sed 's/^/          /'
  FAIL=$((FAIL + 1))
fi
echo ""

# TC-DEDUP-2: bang notation (!) is treated as breaking — major bump
echo "TC-DEDUP-2: feat(scope)! triggers major bump"
teardown_tags "plugins-netanel-v*"
setup_tag "plugins-netanel-v1.0.0"
out=$(run_release "feat(plugins/netanel)!: drop legacy endpoint")
assert_contains "major bump" "$out" "plugins-netanel-v2.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "plugins-netanel-v2.0.0" "plugins-netanel-v2.0.0"
echo ""

# TC-DEDUP-3: Two different scopes in same PR -- both processed independently
echo "TC-DEDUP-3: Two different scopes -- both processed independently"
teardown_tags "plugins-netanel-v*"
teardown_tags "plugins-harel-v*"
out=$(run_release "$(printf 'feat(plugins/netanel): add thing\nfix(plugins/harel): patch bug')")
assert_contains "netanel SUCCESS" "$out" "plugins-netanel-v1.0.0"
assert_contains "harel SUCCESS" "$out" "plugins-harel-v1.0.0"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: OUTPUT_TAGS_FILE
# ─────────────────────────────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────────"
echo "│ SECTION 7: OUTPUT_TAGS_FILE"
echo "└─────────────────────────────────────────────"
echo ""

# TC-OUT-1: Tags are written to OUTPUT_TAGS_FILE
echo "TC-OUT-1: Created tags appended to OUTPUT_TAGS_FILE"
teardown_tags "plugins-lagziel-v*"
out=$(docker run --rm \
  -v "$WORKSPACE:/workspace" \
  -w /workspace \
  -e PLUGIN_BASE="." \
  -e SCOPE_DEPTH="1" \
  -e "PR_BODY=feat(plugins/lagziel): initial release" \
  -e OUTPUT_TAGS_FILE="/workspace/test_tags_out.txt" \
  "$IMAGE" \
  sh -c "git config --global safe.directory '*' && rm -f /workspace/test_tags_out.txt && python3 release.py" 2>&1)
assert_contains "release succeeded" "$out" "SUCCESS"
if [ -f "$WORKSPACE/test_tags_out.txt" ] && grep -qF "plugins-lagziel-v" "$WORKSPACE/test_tags_out.txt"; then
  echo "  PASS: tag written to OUTPUT_TAGS_FILE"
  PASS=$((PASS + 1))
else
  echo "  FAIL: OUTPUT_TAGS_FILE missing or tag not written"
  echo "        File content: $(cat "$WORKSPACE/test_tags_out.txt" 2>/dev/null || echo '(missing)')"
  FAIL=$((FAIL + 1))
fi
rm -f "$WORKSPACE/test_tags_out.txt"
echo ""

# TC-OUT-2: Multi-scope: all tags written to file
echo "TC-OUT-2: Multi-scope -- all created tags written to OUTPUT_TAGS_FILE"
teardown_tags "plugins-netanel-v*"
teardown_tags "plugins-harel-v*"
out=$(docker run --rm \
  -v "$WORKSPACE:/workspace" \
  -w /workspace \
  -e PLUGIN_BASE="." \
  -e SCOPE_DEPTH="1" \
  -e "PR_BODY=feat(plugins/netanel, plugins/harel): shared upgrade" \
  -e OUTPUT_TAGS_FILE="/workspace/test_tags_out.txt" \
  "$IMAGE" \
  sh -c "git config --global safe.directory '*' && rm -f /workspace/test_tags_out.txt && python3 release.py" 2>&1)
assert_contains "release succeeded" "$out" "SUCCESS"
if [ -f "$WORKSPACE/test_tags_out.txt" ]; then
  tag_count=$(wc -l < "$WORKSPACE/test_tags_out.txt")
  if [ "$tag_count" -ge 2 ]; then
    echo "  PASS: $tag_count tags written to OUTPUT_TAGS_FILE"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: expected >=2 tags in file, got $tag_count"
    cat "$WORKSPACE/test_tags_out.txt" | sed 's/^/          /'
    FAIL=$((FAIL + 1))
  fi
else
  echo "  FAIL: OUTPUT_TAGS_FILE not created"
  FAIL=$((FAIL + 1))
fi
rm -f "$WORKSPACE/test_tags_out.txt"
echo ""


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
echo "================================================"
echo " Results: $PASS passed, $FAIL failed"
echo "================================================"
echo ""
echo "--- Tags remaining in repo ---"
git -C "$WORKSPACE" tag -l | sort -V

[ "$FAIL" -eq 0 ]
