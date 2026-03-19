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
    pattern = r"^([a-z]+)\(([^)]+)\):\s*(.*)"
    
    if not body:
        return release_set

    for line in body.splitlines():
        match = re.match(pattern, line.strip(), re.IGNORECASE)
        if match:
            msg_type, raw_scopes, description = match.groups()
            for scope in raw_scopes.split(','):
                # Clean up and reconstruct: feat(base/argo): message
                release_set.add(f"{msg_type.lower()}({scope.strip()}): {description.strip()}")
    
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
        tag_template = f"{path_slug}-v" + "{{ version }}"
        
        print(f"--- Processing: {path_slug} ---")

        # 4. ONE-SHOT Execution: Use global TOML, specific path history, and PR message
        cliff_cmd = (
            f"git cliff --config {global_toml} "
            f"--include-path '{rel_path}/**/*' " 
            f"--bump "
            f"--tag '{tag_template}' "
            f"--body '{full_msg}' "
            f"--output {os.path.join(full_path, 'CHANGELOG.md')}"
        )
        
        res = run_command(cliff_cmd)
        
        if res.returncode == 0:
            # Extract the new version from git-cliff output for confirmation
            v_match = re.search(r"bumped to (\d+\.\d+\.\d+)", res.stdout + res.stderr)
            version = v_match.group(1) if v_match else "updated"
            print(f">>> SUCCESS: Created {path_slug}-v{version}")
        else:
            print(f">>> ERROR for {path_slug}: {res.stderr.strip()}")

if __name__ == "__main__":
    release()
