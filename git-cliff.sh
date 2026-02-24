#!/bin/bash
set -e

# ==============================================================================
# SCRIPT LOGIC OVERVIEW:
# 1. DIRECTORY PARSING:
#    - Reads paths from $CHANGED_FOLDERS_FILE (e.g., plugins/nati/core).
#    - Extracts PLUGIN_NAME as the first subdirectory after the root (e.g., nati).
#    - Targets a changelog file named after the plugin: $PLUGIN_NAME.md.
#
# 2. VERSIONING STRATEGY:
#    - NEW PLUGINS: If no 'VERSION' file exists, initializes with $INITIAL_TAG_FALLBACK.
#    - EXISTING PLUGINS: 
#      - Creates a temporary Git tag on HEAD~1 matching the current version.
#      - Uses 'git-cliff --bumped-version' to calculate the next Semantic Version.
#      - If git-cliff detects no version change, it falls back to a manual +1 patch bump.
#
# 3. STRICT VALIDATION & ERROR HANDLING:
#    - If git-cliff returns an empty string or non-numeric junk (not X.Y.Z), the 
#      script cleans up the temporary tag and EXITS with code 1 immediately.
#
# 4. CHANGELOG UPDATES:
#    - INITIAL: Uses '--output' (create) or '--prepend' (top) if the file exists.
#    - UPDATES: Appends new release notes to the BOTTOM of the file using '>>'.
# ==============================================================================

# --- Configuration & Environment ---
INPUT_FILE=${CHANGED_FOLDERS_FILE:-"changed_folders.txt"}
CONFIG_FILE=${GIT_CLIFF_CONFIG:-"cliff.toml"}
DEFAULT_INITIAL_TAG=${INITIAL_TAG_FALLBACK:-"1.0.0"}

if [ ! -f "$INPUT_FILE" ]; then
    echo "⚠️ Input file $INPUT_FILE not found."
    exit 0
fi

while IFS= read -r dir; do
    # Cleanup directory path string
    dir=$(echo "$dir" | tr -d '"\r' | xargs)
    if [ -z "$dir" ] || [ ! -d "$dir" ]; then continue; fi

    # EXTRACTION: Get name after first slash (e.g., plugins/nati/check -> nati)
    PLUGIN_NAME=$(echo "$dir" | cut -d'/' -f2)
    CHANGELOG_NAME="${PLUGIN_NAME}.md"
    CHANGELOG_PATH="$dir/$CHANGELOG_NAME"

    echo -e "\n📦 Processing Plugin: $PLUGIN_NAME (Path: $dir)"
    echo "======================================="

    # --- 1. Handle New Plugins (Initial Release) ---
    if [ ! -f "$dir/VERSION" ]; then
        echo "No VERSION file found. Using default initial tag: $DEFAULT_INITIAL_TAG"
        
        if [ ! -f "$CHANGELOG_PATH" ]; then
            echo "Creating NEW changelog: $CHANGELOG_NAME"
            git-cliff --config "$CONFIG_FILE" HEAD \
                --tag "$DEFAULT_INITIAL_TAG" \
                --include-path "$dir/**" \
                --output "$CHANGELOG_PATH" \
                --strip all
        else
            echo "Initial tag block: File exists. PREPENDING to $CHANGELOG_NAME"
            git-cliff --config "$CONFIG_FILE" HEAD \
                --tag "$DEFAULT_INITIAL_TAG" \
                --include-path "$dir/**" \
                --prepend "$CHANGELOG_PATH" \
                --strip all
        fi
            
        echo -n "$DEFAULT_INITIAL_TAG" > "$dir/VERSION"
        continue 
    fi

    # --- 2. Existing Plugins - Get Current Version ---
    CURRENT_VERSION=$(cat "$dir/VERSION")
    
    # --- 3. Setup Mock Tag for Range Calculation ---
    MOCK_TAG="$CURRENT_VERSION"
    REAL_TAG_EXISTS=false

    if git rev-parse "$MOCK_TAG" >/dev/null 2>&1; then
        REAL_TAG_EXISTS=true
        echo "ℹ️ Real tag $MOCK_TAG exists. Using for range."
        RANGE="$MOCK_TAG..HEAD"
    else
        if git rev-parse HEAD~1 >/dev/null 2>&1; then
            git tag -f "$MOCK_TAG" HEAD~1 > /dev/null 2>&1
            RANGE="$MOCK_TAG..HEAD"
        else
            RANGE="HEAD"
        fi
    fi

    # --- 4. Calculate Bump & STRICT VALIDATION ---
    RAW_OUT=$(git-cliff --config "$CONFIG_FILE" "$RANGE" --bumped-version --include-path "$dir/**" 2>/dev/stderr || echo "")
    NEXT_VERSION=$(echo "$RAW_OUT" | xargs)

    # ERROR HANDLING: Exit if git-cliff returns absolutely nothing
    if [ -z "$NEXT_VERSION" ]; then
        echo "❌ FATAL: git-cliff returned an empty string for $dir." >&2
        [ "$REAL_TAG_EXISTS" = false ] && git tag -d "$MOCK_TAG" >/dev/null 2>&1 || true
        exit 1
    fi

    # ERROR HANDLING: Exit if result is not a valid Semantic Version (X.Y.Z)
    if [[ ! "$NEXT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "❌ FATAL: git-cliff returned invalid junk: '$NEXT_VERSION'" >&2
        [ "$REAL_TAG_EXISTS" = false ] && git tag -d "$MOCK_TAG" >/dev/null 2>&1 || true
        exit 1
    fi

    # --- 5. Cleanup Mock Tag ---
    if [ "$REAL_TAG_EXISTS" = false ]; then
        git tag -d "$MOCK_TAG" > /dev/null 2>&1 || true
    fi

    # --- 6. Fallback (Manual Patch if version didn't change) ---
    if [ "$NEXT_VERSION" = "$CURRENT_VERSION" ]; then
        echo "⚠️ No bump detected by git-cliff. Applying manual patch..."
        NEXT_VERSION=$(echo "$CURRENT_VERSION" | awk -F. 'BEGIN{OFS="."} {$NF=$NF+1; print}')
    else
        echo "✅ Success! Calculated bump: $NEXT_VERSION"
    fi

    # --- 7. Final File Updates ---
    echo -n "$NEXT_VERSION" > "$dir/VERSION"

    if [ ! -f "$CHANGELOG_PATH" ]; then
        echo "File missing. Creating $CHANGELOG_NAME"
        git-cliff --config "$CONFIG_FILE" HEAD~1..HEAD \
            --tag "$NEXT_VERSION" \
            --include-path "$dir/**" \
            --output "$CHANGELOG_PATH" \
            --strip all
    else
        echo "Appending update to BOTTOM of $CHANGELOG_NAME"
        # Appends a newline and then the new version content to the end of the file
        echo -e "\n" >> "$CHANGELOG_PATH"
        git-cliff --config "$CONFIG_FILE" HEAD~1..HEAD \
            --tag "$NEXT_VERSION" \
            --include-path "$dir/**" \
            --strip all >> "$CHANGELOG_PATH"
    fi

    echo "✅ Updated $PLUGIN_NAME to $NEXT_VERSION"

done < "$INPUT_FILE"