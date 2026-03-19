import subprocess
import re
import os

def run_command(command):
    """Executes shell commands and captures output."""
    return subprocess.run(command, shell=True, capture_output=True, text=True)

def parse_pr_body(body):
    """
    Parses PR body to find lines like 'type(scope1, scope2): message'.
    Returns a set of unique Conventional Commit strings.
    """
    release_set = set()
    # Supports: feat(scope): msg  AND  feat(scope)!: msg  (breaking change)
    pattern = r"^([a-z]+)\(([^)]+)\)(!?):\s*(.*)"

    if not body:
        return release_set

    for line in body.splitlines():
        match = re.match(pattern, line.strip(), re.IGNORECASE)
        if match:
            msg_type, raw_scopes, breaking, description = match.groups()
            for scope in raw_scopes.split(','):
                release_set.add(f"{msg_type.lower()}({scope.strip()}){breaking}: {description.strip()}")
    
    return release_set

def release():
    # Load Environment Variables
    pr_body = os.getenv("PR_BODY", "")
    root_path = os.getenv("PLUGIN_MONOREPO_PATH", ".")
    global_toml = os.path.join(root_path, "cliff.toml")
    
    if not os.path.exists(global_toml):
        print(f">>> ERROR: Global cliff.toml not found at {global_toml}")
        return

    # 1. Extract Workload
    messages = parse_pr_body(pr_body)
    if not messages:
        print(">>> No Conventional Commits detected in PR Body.")
        return

    # 2. Process each component
    for full_msg in messages:
        # Extract the relative path from the scope: (base/argo) -> base/argo
        path_match = re.search(r"\(([^)]+)\)", full_msg)
        if not path_match: continue
            
        rel_path = path_match.group(1)
        full_path = os.path.normpath(os.path.join(root_path, rel_path))
        
        if not os.path.isdir(full_path):
            print(f">>> SKIP: Directory '{rel_path}' does not exist.")
            continue
        
        # 3. Create unique Tag Slug: "base/argo" -> "base-argo"
        path_slug = rel_path.replace("/", "-").replace("\\", "-")

        print(f"--- Processing: {path_slug} ---")


        # 4. Check if this component has ever been tagged
        existing_tags = run_command(f"git tag -l '{path_slug}-v*' --sort=-version:refname")
        latest_tag = existing_tags.stdout.strip().splitlines()[0] if existing_tags.stdout.strip() else None

        # Restrict tag lookup to this component only
        component_tag_pattern = f"^{path_slug}-v[0-9]+\\.[0-9]+\\.[0-9]+$"

        if latest_tag:
            # Existing component: calculate next version
            bumped = run_command(
                f"git cliff --config {global_toml} "
                f"--include-path '{rel_path}/**/*' "
                f"--tag-pattern '{component_tag_pattern}' "
                f"--bump --bumped-version "
                f"--with-commit '{full_msg}'"
            )
            new_tag = bumped.stdout.strip()
        else:
            # First release
            new_tag = f"{path_slug}-v1.0.0"

        # Create the git tag FIRST so git-cliff sees it as the "latest" tag
        tag_res = run_command(f"git tag {new_tag}")
        if tag_res.returncode != 0:
            print(f">>> ERROR tagging {new_tag}: {tag_res.stderr.strip()}")
            continue
        # Generate changelog entry:
        # --unreleased  → only the virtual --with-commit (HEAD is already tagged, 0 real unreleased commits)
        # --tag '{new_tag}' → label those commits as the new version (not [unreleased])
        # --prepend/--output → accumulate entries in the file
        changelog_path = os.path.join(full_path, 'CHANGELOG.md')
        output_flag = f"--prepend {changelog_path}" if os.path.exists(changelog_path) else f"--output {changelog_path}"
        cliff_cmd = (
            f"git cliff --config {global_toml} "
            f"--include-path '{rel_path}/**/*' "
            f"--tag-pattern '{component_tag_pattern}' "
            f"--unreleased "
            f"--tag '{new_tag}' "
            f"--with-commit '{full_msg}' "
            f"{output_flag}"
        )

        res = run_command(cliff_cmd)

        if res.returncode == 0:
            print(f">>> SUCCESS: Created {new_tag}")
        else:
            print(f">>> ERROR for {path_slug}: {res.stderr.strip()}")

if __name__ == "__main__":
    release()
