#!/usr/bin/env bash
# Creates test PRs in Gitea for each test case in test_release_docker.sh.
# Usage: ./create-test-prs.sh

set -euo pipefail

# Debug helper: prints response body on non-zero exit
curl_debug() {
  local desc="$1"; shift
  local response
  response=$(curl -sf "$@" 2>&1) || {
    echo "    [DEBUG] FAILED: $desc"
    echo "    [DEBUG] Command: curl -sf $*"
    echo "    [DEBUG] Response: $response"
    return 1
  }
  echo "$response"
}

GITEA_URL="${GITEA_URL:-http://localhost:3000}"
GITEA_TOKEN="${GITEA_TOKEN:-3935ecfe08a1f2baf043bde1a317b337f60650d0}"
REPO="netanelzucaim/semantic"
BASE_BRANCH="main"
API="$GITEA_URL/api/v1/repos/$REPO"
AUTH="Authorization: token $GITEA_TOKEN"

# Each entry: "branch|pr-title|pr-body"
# Bodies may contain \n (literal) which JSON interprets as newline — used for multi-line PR bodies.
declare -a TEST_CASES=(
  "test/tc1-netanel-first|TC1 First Release|feat(plugins/netanel): add dashboard"
  "test/tc2-netanel-minor|TC2 Minor Bump|feat(plugins/netanel): add sidebar"
  "test/tc3a-lagziel-first|TC3a Lagziel First Release|feat(plugins/lagziel): initial release"
  "test/tc3b-lagziel-patch|TC3b Patch Bump|fix(plugins/lagziel): resolve crash on startup"
  "test/tc4-multi-scope|TC4 Multi-scope Explosion|feat(plugins/harel, plugins/kaniko-monorepo): shared auth update"
  "test/tc5-nonexistent|TC5 Nonexistent Directory|feat(nonexistent/component): some change"
  "test/tc6-no-commits|TC6 No Conventional Commits|just a random PR description with no commits"
  "test/tc7-harel-minor|TC7 Minor Bump Existing|feat(plugins/harel): add retry logic"
  "test/tc-break-harel|TC-BREAK Major Bump|breaking(plugins/harel): remove legacy api"
  "test/tc8-dedup|TC8 Duplicate Lines|feat(plugins/harel): add thing\nfeat(plugins/harel): add thing"
)

# Close all open PRs
echo "==> Closing all open PRs"
open_prs=$(curl_debug "list open PRs" "$API/pulls?state=open&limit=50" -H "$AUTH" \
  | python3 -c "import sys,json; [print(p['number']) for p in json.load(sys.stdin)]")
for pr in $open_prs; do
  curl_debug "close PR #$pr" -X PATCH "$API/pulls/$pr" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d '{"state":"closed"}' > /dev/null
  echo "    Closed PR #$pr"
done

for entry in "${TEST_CASES[@]}"; do
  IFS="|" read -r branch title body <<< "$entry"

  echo "==> $branch"

  # Delete branch if it exists, then recreate fresh from main
  curl_debug "delete branch $branch" -X DELETE "$API/branches/$branch" \
    -H "$AUTH" > /dev/null 2>&1 || true
  curl_debug "create branch $branch" -X POST "$API/branches" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"new_branch_name\":\"$branch\",\"old_branch_name\":\"$BASE_BRANCH\"}" \
    > /dev/null

  # Add a trigger file with random suffix so the branch can be re-created each run
  rand=$(head -c 6 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 6)
  trigger_file=".triggers/${branch//\//-}-${rand}"
  content=$(echo -n "$branch-$rand" | base64)
  curl_debug "create trigger file $trigger_file" -X POST "$API/contents/$trigger_file" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"message\":\"chore: trigger for $branch\",\"content\":\"$content\",\"branch\":\"$branch\"}" \
    > /dev/null 2>&1 || true

  # Create PR
  pr_number=$(curl_debug "create PR for $branch" -X POST "$API/pulls" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"title\":\"$title\",\"head\":\"$branch\",\"base\":\"$BASE_BRANCH\",\"body\":\"$body\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('number','?'))")

  echo "    PR #$pr_number: $title"
  echo "    Body: $body"
done

echo ""
echo "Done. View PRs at $GITEA_URL/$REPO/pulls"
