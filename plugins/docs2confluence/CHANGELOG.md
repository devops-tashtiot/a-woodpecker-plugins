## [1.6.10] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.6.9] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.6.10] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.6.9] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.6.10] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.6.9] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

### Other

- Adding local
- Start
- Check
- Check
- Check
- Check

## [1.6.10] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.6.9] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.1.5] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.1.4] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.1.3] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.1.2] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.1.1] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.0.9] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.0.5] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [0.1.3] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [0.1.2] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [0.1.1] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [0.1.0] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.0.12] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.0.11] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.0.10] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

## [1.0.9] - 2026-02-23

### Features

- Add retry mechanism for failed requests
- Add retry mechanism for failed requests

#!/bin/bash

echo "Detecting changed plugin folders..."

# 1. Identify which folders under plugins/ changed in the last commit
# We assume 'changedFiles.txt' was generated via: 
# git diff-tree --no-commit-id --name-only -r HEAD > changedFiles.txt
grep '^plugins/' changedFiles.txt | cut -d '/' -f 1,2 | sort -u > changed_folders.txt

while IFS= read -r dir; do
    # Clean directory name
    dir=$(echo "$dir" | tr -d '"\r')

    # Skip if not a directory (handles deleted folders)
    if [ -z "$dir" ] || [ ! -d "$dir" ]; then
        continue
    fi

    echo ""
    echo "======================================="
    echo "--- Processing: $dir ---"
    
    # Print the specific commit git-cliff is looking at for this folder
    COMMIT_INFO=$(git log -1 --pretty=format:"%h - %s" HEAD -- "$dir/**")
    echo "Last Commit affecting this path: $COMMIT_INFO"
    echo "======================================="

    # 1️⃣ Get CURRENT version from file (default to 1.0.0 if missing)
    CURRENT_VERSION=$(cat "$dir/VERSION" 2>/dev/null || echo "1.0.0")
    echo "Current version: $CURRENT_VERSION"

    # 2️⃣ Calculate NEXT version using git-cliff
    # --provided-tag: Tells git-cliff to treat the file version as the 'last tag'
    # --bumped-version: Calculates the next SemVer based on commit types (feat/fix)
    NEXT_VERSION=$(git-cliff HEAD~1..HEAD \
        --bumped-version \
        --provided-tag "$CURRENT_VERSION" \
        --include-path "$dir/**" 2>/dev/null || echo "")

    # 3️⃣ Logic check: If git-cliff returns empty or same version, force a patch bump
    if [ -z "$NEXT_VERSION" ] || [ "$NEXT_VERSION" = "$CURRENT_VERSION" ]; then
        echo "No semantic 'feat' or 'fix' detected. Forcing manual patch bump..."
        # awk splits by '.' and increments the last digit
        NEXT_VERSION=$(echo "$CURRENT_VERSION" | awk -F. 'BEGIN{OFS="."} {$NF=$NF+1; print}')
    else
        echo "Git-cliff detected a Conventional Bump!"
    fi

    echo "Final Version for $dir: $NEXT_VERSION"

    # 4️⃣ Update the VERSION file
    echo -n "$NEXT_VERSION" > "$dir/VERSION"

    # 5️⃣ Update the CHANGELOG.md
    if [ ! -f "$dir/CHANGELOG.md" ]; then
        echo "Creating initial CHANGELOG.md..."
        touch "$dir/CHANGELOG.md"
    fi

    # Prepend the last commit to the changelog
    # --tag sets the header in the changelog to our new version
    # --strip all prevents double headers/footers when prepending
    git-cliff HEAD~1..HEAD \
        --tag "$NEXT_VERSION" \
        --include-path "$dir/**" \
        --prepend "$dir/CHANGELOG.md" \
        --strip all || true

done < changed_folders.txt

echo ""
echo "Versioning completed successfully."