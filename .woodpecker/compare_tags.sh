#!/bin/sh

set -euo pipefail

# FAIL_ON_MISMATCH=true  → exit 1 on any mismatch  (default)
# FAIL_ON_MISMATCH=false → print warning and continue
FAIL_ON_MISMATCH="${FAIL_ON_MISMATCH:-true}"

# ── Build slug lists ──────────────────────────────────────────────────────────

while IFS= read -r dir; do
  [ -z "$dir" ] && continue
  echo "$dir" | tr '/' '-'
done < changed_dirs.txt | sort -u > /tmp/changed_slugs.txt

while IFS= read -r line; do
  [ -z "$line" ] && continue
  ver="${line##*-}"
  slug="${line%-${ver}}"
  echo "${slug%-}"
done < new_tags.txt | sort -u > /tmp/tag_slugs.txt

# ── Summary ───────────────────────────────────────────────────────────────────

changed_count=$(grep -c . /tmp/changed_slugs.txt 2>/dev/null || echo 0)
released_count=$(grep -c . /tmp/tag_slugs.txt 2>/dev/null || echo 0)

echo ""
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│              COMPARE CHANGED DIRS vs RELEASED TAGS          │"
echo "└─────────────────────────────────────────────────────────────┘"
echo ""
echo "  Changed dirs  : ${changed_count}"
echo "  Released tags : ${released_count}"
echo ""
echo ">>> Changed dir slugs:"
cat /tmp/changed_slugs.txt | sed 's/^/    /'
echo ""
echo ">>> Released tag slugs:"
cat /tmp/tag_slugs.txt | sed 's/^/    /'
echo ""

# ── Diff ──────────────────────────────────────────────────────────────────────

missing_tags=$(comm -23 /tmp/changed_slugs.txt /tmp/tag_slugs.txt)
missing_dirs=$(comm -13 /tmp/changed_slugs.txt /tmp/tag_slugs.txt)

has_mismatch=false

if [ -n "$missing_tags" ]; then
  has_mismatch=true
  echo "┌─────────────────────────────────────────────────────────────┐"
  echo "│  FILES CHANGED but NO release tag produced                  │"
  echo "└─────────────────────────────────────────────────────────────┘"
  echo "  These components had file changes but were not released."
  echo "  To release them, add a conventional commit line to your PR body:"
  echo ""
  echo "$missing_tags" | while IFS= read -r slug; do
    [ -z "$slug" ] && continue
    path=$(echo "$slug" | tr '-' '/')
    echo "    feat[${path}]: <describe your change>"
  done
  echo ""
  echo "  Then re-run the pipeline."
  echo ""
fi

if [ -n "$missing_dirs" ]; then
  has_mismatch=true
  echo "┌─────────────────────────────────────────────────────────────┐"
  echo "│  RELEASE TAG produced but NO matching changed dir           │"
  echo "└─────────────────────────────────────────────────────────────┘"
  echo "  These components were released but no file changes were detected."
  echo "  Possible causes:"
  echo "    - The PR body references a component that was not actually modified"
  echo "    - The changed-files plugin filtered out the relevant files"
  echo "    - The component path in the PR body does not match the directory name"
  echo ""
  echo "$missing_dirs" | while IFS= read -r slug; do
    [ -z "$slug" ] && continue
    path=$(echo "$slug" | tr '-' '/')
    echo "    Released: ${slug}  →  expected dir: ${path}/"
  done
  echo ""
fi

# ── Result ────────────────────────────────────────────────────────────────────

if [ "$has_mismatch" = "false" ]; then
  echo "✔  All changed dirs are covered by a released tag. Pipeline continues."
  exit 0
fi

if [ "$FAIL_ON_MISMATCH" = "true" ]; then
  echo "✘  Mismatch detected and FAIL_ON_MISMATCH=true — failing pipeline." >&2
  echo "   Set FAIL_ON_MISMATCH=false in the pipeline step to downgrade to a warning." >&2
  exit 1
else
  echo "⚠  Mismatch detected — FAIL_ON_MISMATCH=false, continuing pipeline."
fi
