#!/bin/bash
set -e

while IFS= read -r dir; do
    dir=$(echo "$dir" | tr -d '"\r')
    if [ -z "$dir" ] || [ ! -d "$dir" ]; then continue; fi

    echo ""
    echo "======================================="
    echo "--- Processing: $dir ---"
    echo "======================================="

    # 1. Handle New Plugins (No VERSION file)
    if [ ! -f "$dir/VERSION" ]; then
        echo "No VERSION file found. Fetching initial_tag from config..."
        CONF_INITIAL_TAG=$(git-cliff --print-config | grep -oP 'initial_tag\s*=\s*"\K[^"]+' || echo "1.0.0")
        
        echo "Creating initial CHANGELOG.md with version $CONF_INITIAL_TAG..."
        # USE --output here because the file likely doesn't exist
        git-cliff HEAD~1..HEAD \
            --tag "$CONF_INITIAL_TAG" \
            --include-path "$dir/**" \
            --output "$dir/CHANGELOG.md" \
            --strip all || exit 1
            
        echo -n "$CONF_INITIAL_TAG" > "$dir/VERSION"
        echo "Initial processing complete."
        continue 
    fi

    # 2. Existing Plugins - Validate Version
    CURRENT_VERSION=$(cat "$dir/VERSION")
    if [[ ! "$CURRENT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "❌ ERROR: Invalid version format in $dir/VERSION" >&2
        exit 1
    fi

    # 3. Setup Mock Tag
    MOCK_TAG="$CURRENT_VERSION"
    if git rev-parse HEAD~1 >/dev/null 2>&1; then
        git tag -f "$MOCK_TAG" HEAD~1 > /dev/null 2>&1
        RANGE="$MOCK_TAG..HEAD"
    else
        RANGE="HEAD"
    fi

    # 4. Calculate Version
    RAW_OUT=$(git-cliff "$RANGE" --bumped-version --include-path "$dir/**" 2>/dev/stderr || echo "")
    NEXT_VERSION=$(echo "$RAW_OUT" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' || echo "")
    git tag -d "$MOCK_TAG" > /dev/null 2>&1 || true

    # 5. Fallback Bump
    if [ -z "$NEXT_VERSION" ] || [ "$NEXT_VERSION" = "$CURRENT_VERSION" ]; then
        NEXT_VERSION=$(echo "$CURRENT_VERSION" | awk -F. 'BEGIN{OFS="."} {$NF=$NF+1; print}')
    fi

    # 6. Update Files
    echo -n "$NEXT_VERSION" > "$dir/VERSION"

    echo "Updating CHANGELOG.md..."
    
    # CHECK: Create if missing, Prepend if exists
    if [ ! -f "$dir/CHANGELOG.md" ]; then
        CLIFF_CMD="--output"
    else
        CLIFF_CMD="--prepend"
    fi

    git-cliff HEAD~1..HEAD \
        --tag "$NEXT_VERSION" \
        --include-path "$dir/**" \
        $CLIFF_CMD "$dir/CHANGELOG.md" \
        --strip all || exit 1

done < changed_folders.txt