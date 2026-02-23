## [1.1.0] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests
- Change doc2confluence
- Change doc2confluence

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.0.1] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests
- Change doc2confluence
- Change doc2confluence

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.0.1] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests
- Change doc2confluence
- Change doc2confluence

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.0.1] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests
- Change doc2confluence
- Change doc2confluence

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

#!/bin/bash
echo "Detecting changed plugin folders..."
touch changedFiles.txt
grep '^plugins/' changedFiles.txt | cut -d '/' -f 1,2 | sort -u > changed_folders.txt

# 1. Create a temp file with a .toml extension
TEMP_CONFIG="temp_cliff_config.toml"
sed 's/filter_unconventional = true/filter_unconventional = false/' cliff.toml > "$TEMP_CONFIG"

while IFS= read -r dir; do
    dir=$(echo "$dir" | tr -d '"\r')
    if [ -z "$dir" ] || [ ! -d "$dir" ]; then continue; fi

    echo ""
    echo "======================================="
    echo "--- Processing: $dir ---"
    echo "======================================="

    CURRENT_VERSION=1.0.0
    echo "Current version: $CURRENT_VERSION"
    
    # 2. Mock Tag Logic
    MOCK_TAG="$CURRENT_VERSION"
    if git rev-parse HEAD~2 >/dev/null 2>&1; then
        git tag -f "$MOCK_TAG" HEAD~2 > /dev/null 2>&1
        RANGE="$MOCK_TAG..HEAD"
    else
        RANGE="HEAD"
    fi

    echo "Calculating next version..."
    
    # 3. Use the .toml temp file
    # We capture only the version string, redirecting the -vv logs to stderr
    NEXT_VERSION=$( (git-cliff "$RANGE" \
        --bumped-version \
        -vv \
        --include-path "$dir/**" \
        --config "$TEMP_CONFIG" ))

    git tag -d "$MOCK_TAG" > /dev/null 2>&1 || true
    echo "next version is "$NEXT_VERSION""
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
        --config "$TEMP_CONFIG" \
        --strip all || true

done < changed_folders.txt

# 4. Cleanup
rm -f "$TEMP_CONFIG"

echo ""
echo "Versioning completed successfully."