#!/bin/bash


echo "Detecting changed plugin folders..."
touch changedFiles.txt
grep '^plugins/' changedFiles.txt | cut -d '/' -f 1,2 | sort -u > changed_folders.txt

while IFS= read -r dir; do
    dir=$(echo "$dir" | tr -d '"\r')
    if [ -z "$dir" ] || [ ! -d "$dir" ]; then continue; fi

    echo ""
    echo "======================================="
    echo "--- Processing: $dir ---"
    echo "======================================="

    CURRENT_VERSION=$(cat "$dir/VERSION" 2>/dev/null || echo "1.0.0")
    echo "Current version: $CURRENT_VERSION"
    
    # 2. Mock Tag Logic
    MOCK_TAG="$CURRENT_VERSION"
    if git rev-parse HEAD~1 >/dev/null 2>&1; then
        git tag -f "$MOCK_TAG" HEAD~1 > /dev/null 2>&1
        RANGE="$MOCK_TAG..HEAD"
    else
        RANGE="HEAD"
    fi

    echo "Calculating next version..."
    
    # We capture only the version string, redirecting the -vv logs to stderr
    NEXT_VERSION=$( (git-cliff "$RANGE" \
        --bumped-version \
        -vv \
        --include-path "$dir/**" | tee /dev/stderr) || echo "")

    git tag -d "$MOCK_TAG" > /dev/null 2>&1 || true

    if [ -z "$NEXT_VERSION" ] || [ "$NEXT_VERSION" = "$CURRENT_VERSION" ]; then
        echo "⚠️ Git-cliff did not detect a bump. Forcing manual patch..."
        NEXT_VERSION=$(echo "$CURRENT_VERSION" | awk -F. 'BEGIN{OFS="."} {$NF=$NF+1; print}')
    else
        echo "✅ Success! Calculated bump: $NEXT_VERSION"
    fi

    echo -n "$NEXT_VERSION" > "$dir/VERSION"
    
    echo "Updating CHANGELOG.md..."
    git-cliff --unreleased \
        --tag "$NEXT_VERSION" \
        --include-path "$dir/**" \
        --prepend "$dir/CHANGELOG.md" \
        --strip all || true

done < changed_folders.txt

# 4. Cleanup

echo ""
echo "Versioning completed successfully."