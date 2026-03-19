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

run_release() {
  docker run --rm \
    -v "$WORKSPACE:/workspace" \
    -w /workspace \
    -e PLUGIN_MONOREPO_PATH="." \
    -e "PR_BODY=$1" \
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

cleanup() {
  echo "--- Cleaning up tags and changelogs from previous run ---"
  for pattern in "plugins-netanel-v*" "plugins-harel-v*" "plugins-lagziel-v*" "plugins-kaniko-monorepo-v*"; do
    teardown_tags "$pattern"
  done
  rm -f \
    "$WORKSPACE/plugins/netanel/CHANGELOG.md" \
    "$WORKSPACE/plugins/harel/CHANGELOG.md" \
    "$WORKSPACE/plugins/lagziel/CHANGELOG.md" \
    "$WORKSPACE/plugins/kaniko-monorepo/CHANGELOG.md"
  echo ""
}

cleanup

echo "================================================"
echo " release.py Docker Integration Tests"
echo "================================================"
echo ""

# TC1: First release -- no existing tag
echo "TC1: First release -- new component gets v1.0.0"
out=$(run_release "feat(plugins/netanel): add dashboard")
assert_contains "output reports v1.0.0" "$out" "plugins-netanel-v1.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag plugins-netanel-v1.0.0 exists" "plugins-netanel-v1.0.0"
echo ""

# TC2: feat bumps minor -- builds on TC1's persisted tag
echo "TC2: feat bumps minor (1.0.0 -> 1.1.0)"
out=$(run_release "feat(plugins/netanel): add sidebar")
assert_contains "output reports v1.1.0" "$out" "plugins-netanel-v1.1.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag plugins-netanel-v1.1.0 exists" "plugins-netanel-v1.1.0"
echo ""

# TC3: fix bumps patch -- lagziel built from scratch via release.py so both versions have changelog entries
echo "TC3a: lagziel first release -> v1.0.0"
out=$(run_release "feat(plugins/lagziel): initial release")
assert_contains "output reports lagziel v1.0.0" "$out" "plugins-lagziel-v1.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag plugins-lagziel-v1.0.0 exists" "plugins-lagziel-v1.0.0"
echo ""

echo "TC3b: fix bumps patch (1.0.0 -> 1.0.1)"
out=$(run_release "fix(plugins/lagziel): resolve crash on startup")
assert_contains "output reports v1.0.1" "$out" "plugins-lagziel-v1.0.1"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag plugins-lagziel-v1.0.1 exists" "plugins-lagziel-v1.0.1"
echo ""

# TC4: Multi-scope explosion -- two fresh components in one PR line
echo "TC4: Multi-scope explosion -- two components released from one line"
out=$(run_release "feat(plugins/harel, plugins/kaniko-monorepo): shared auth update")
assert_contains "output reports harel v1.0.0" "$out" "plugins-harel-v1.0.0"
assert_contains "output reports kaniko-monorepo v1.0.0" "$out" "plugins-kaniko-monorepo-v1.0.0"
assert_tag_exists "git tag plugins-harel-v1.0.0 exists" "plugins-harel-v1.0.0"
assert_tag_exists "git tag plugins-kaniko-monorepo-v1.0.0 exists" "plugins-kaniko-monorepo-v1.0.0"
echo ""

# TC5: Non-existent directory is skipped
echo "TC5: Non-existent directory -- skipped gracefully"
out=$(run_release "feat(nonexistent/component): some change")
assert_contains "skips missing directory" "$out" "SKIP"
assert_not_contains "no crash" "$out" "Traceback"
echo ""

# TC6: No conventional commits
echo "TC6: No conventional commits in PR body -- exits cleanly"
out=$(run_release "just a random PR description with no commits")
assert_contains "no commits detected" "$out" "No Conventional Commits"
echo ""

# TC7: Second release on harel -- builds on TC4's persisted tag
echo "TC7: feat bumps minor on existing component (1.0.0 -> 1.1.0)"
out=$(run_release "feat(plugins/harel): add retry logic")
assert_contains "output reports harel v1.1.0" "$out" "plugins-harel-v1.1.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag plugins-harel-v1.1.0 exists" "plugins-harel-v1.1.0"
echo ""

# TC-BREAK: breaking type triggers major bump
echo "TC-BREAK: breaking(scope) triggers major bump (1.1.0 -> 2.0.0)"
out=$(run_release "breaking(plugins/harel): remove legacy api")
assert_contains "output reports harel v2.0.0" "$out" "plugins-harel-v2.0.0"
assert_not_contains "no errors" "$out" "ERROR"
assert_tag_exists "git tag plugins-harel-v2.0.0 exists" "plugins-harel-v2.0.0"
echo ""

# TC8: Duplicate lines deduplicated
echo "TC8: Duplicate PR lines -- processed only once"
out=$(run_release "$(printf 'feat(plugins/harel): add thing\nfeat(plugins/harel): add thing')")
assert_tag_exists "git tag plugins-harel-v2.1.0 exists" "plugins-harel-v2.1.0"
count=$(echo "$out" | grep -c "SUCCESS.*plugins-harel" || true)
if [ "$count" -eq 1 ]; then
  echo "  PASS: processed exactly once (count=$count)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected 1 SUCCESS, got $count"
  echo "$out" | sed 's/^/          /'
  FAIL=$((FAIL + 1))
fi
echo ""

# Summary
echo "================================================"
echo " Results: $PASS passed, $FAIL failed"
echo "================================================"
echo ""
echo "--- Tags remaining in repo ---"
git -C "$WORKSPACE" tag -l | sort -V

[ "$FAIL" -eq 0 ]
