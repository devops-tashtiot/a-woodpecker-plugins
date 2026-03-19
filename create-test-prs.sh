#!/usr/bin/env bash
# Creates test PRs in Gitea for each test case in test_release.py.
# Usage: ./create-test-prs.sh

set -euo pipefail

GITEA_URL="${GITEA_URL:-http://localhost:3000}"
GITEA_TOKEN="${GITEA_TOKEN:-3935ecfe08a1f2baf043bde1a317b337f60650d0}"
REPO="netanelzucaim/semantic"
BASE_BRANCH="main"
API="$GITEA_URL/api/v1/repos/$REPO"
AUTH="Authorization: token $GITEA_TOKEN"

# Each entry: "branch|pr-title|pr-body"
declare -a TEST_CASES=(
  "test/tc1-nati|TC1 Single Level|feat(nati): add dashboard"
  "test/tc2-plugins-docker|TC2 Nested Plugin|fix(plugins/docker): resolve socket error"
  "test/tc3-bulk-explosion|TC3 Bulk Explosion|feat(base/argo, nati, plugins/git): global auth update"
  "test/tc4-deeply-nested|TC4 Deeply Nested|chore(base/infra/networking/firewall): update rules"
)

for entry in "${TEST_CASES[@]}"; do
  IFS="|" read -r branch title body <<< "$entry"

  echo "==> $branch"

  # Delete branch if it exists, then recreate fresh from main
  curl -sf -X DELETE "$API/branches/$branch" \
    -H "$AUTH" > /dev/null 2>&1 || true
  curl -sf -X POST "$API/branches" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"new_branch_name\":\"$branch\",\"old_branch_name\":\"$BASE_BRANCH\"}" \
    > /dev/null

  # Add a trigger file with random suffix so the branch can be re-created each run
  rand=$(head -c 6 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 6)
  trigger_file=".triggers/${branch//\//-}-${rand}"
  content=$(echo -n "$branch-$rand" | base64)
  curl -sf -X POST "$API/contents/$trigger_file" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"message\":\"chore: trigger for $branch\",\"content\":\"$content\",\"branch\":\"$branch\"}" \
    > /dev/null 2>&1 || true

  # Create PR
  pr_number=$(curl -sf -X POST "$API/pulls" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"title\":\"$title\",\"head\":\"$branch\",\"base\":\"$BASE_BRANCH\",\"body\":\"$body\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('number','?'))")

  echo "    PR #$pr_number: $title"
  echo "    Body: $body"
done

echo ""
echo "Done. View PRs at $GITEA_URL/$REPO/pulls"
