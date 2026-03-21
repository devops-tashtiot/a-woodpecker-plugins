import subprocess
import re
import os


def run_command(command):
    """Executes shell commands and captures output."""
    return subprocess.run(command, shell=True, capture_output=True, text=True)


def parse_pr_body(body):
    """
    Parses PR body for lines like 'type(scope1, scope2): message'.
    Returns a set of unique Conventional Commit strings.
    Used for SCOPE_DEPTH=1 and SCOPE_DEPTH=2.
    Supports: feat(scope): msg  AND  feat(scope)!: msg (breaking change)
    """
    release_set = set()
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


def parse_pr_body_polyrepo(body):
    """
    Parses PR body for scopeless lines like 'feat: message'.
    Used for SCOPE_DEPTH=0 (polyrepo — single component, no scope needed).
    """
    release_set = set()
    pattern = r"^([a-z]+)(!?):\s*(.*)"

    if not body:
        return release_set

    for line in body.splitlines():
        match = re.match(pattern, line.strip(), re.IGNORECASE)
        if match:
            msg_type, breaking, description = match.groups()
            release_set.add(f"{msg_type.lower()}{breaking}: {description.strip()}")

    return release_set


def discover_scopes(root_path, depth, parent_prefix=None):
    """
    Discovers component directories based on SCOPE_DEPTH.

    parent_prefix given (e.g. "base"):
        Returns all subdirs of root_path/base/ prefixed with "base/".
        e.g. ["base/nati", "base/check"]
        Used for feat(base/*) at depth=2.

    depth=1, no parent:
        Returns direct subdir names of root_path.
        e.g. ["nati", "plugins", "base"]
        Used for feat(*) at depth=1.

    depth=2, no parent:
        Returns all "top/sub" paths two levels deep.
        e.g. ["base/nati", "base/check", "plugins/docker"]
        (not triggered by expand_wildcard — feat(*) is invalid at depth=2)
    """
    if parent_prefix:
        scan_dir = os.path.join(root_path, parent_prefix)
        try:
            return [
                f"{parent_prefix}/{e}"
                for e in os.listdir(scan_dir)
                if os.path.isdir(os.path.join(scan_dir, e))
            ]
        except OSError:
            return []

    elif depth == 1:
        try:
            return [
                e for e in os.listdir(root_path)
                if os.path.isdir(os.path.join(root_path, e))
            ]
        except OSError:
            return []

    elif depth == 2:
        scopes = []
        try:
            for top in os.listdir(root_path):
                top_path = os.path.join(root_path, top)
                if not os.path.isdir(top_path):
                    continue
                try:
                    for sub in os.listdir(top_path):
                        if os.path.isdir(os.path.join(top_path, sub)):
                            scopes.append(f"{top}/{sub}")
                except OSError:
                    continue
        except OSError:
            pass
        return scopes

    return []


def expand_wildcard(messages, root_path, depth, exclude_regex=""):
    """
    Expands wildcard scopes and filters excluded scopes.

    Wildcard rules:
      feat(*): msg  at depth=1 → all direct subdirs of root_path
      feat(base/*): msg at depth=2 → all subdirs under root_path/base/
      feat(*): msg  at depth=2 → INVALID, warns and skips

    SCOPE_EXCLUDE_REGEX is applied to ALL scopes — both wildcard-resolved
    and explicitly written ones (e.g. feat(nati) is skipped if nati matches).

    If there are no wildcards and no exclusions, the original messages object
    is returned unchanged (same reference — preserves identity).
    """
    has_wildcard = any(re.search(r'\(\*\)|\([^)]+/\*\)', msg) for msg in messages)
    has_exclude = bool(exclude_regex)

    if not has_wildcard and not has_exclude:
        return messages  # nothing to do — return same object

    result = set()
    scope_pattern = r'^([a-z]+)\(([^)]+)\)(!?):\s*(.*)'

    for msg in messages:
        match = re.match(scope_pattern, msg)
        if not match:
            result.add(msg)
            continue

        msg_type, scope, breaking, description = match.groups()

        if scope == '*':
            # feat(*) — only valid at depth=1
            if depth == 2:
                print(f">>> WARN: feat(*) is invalid at SCOPE_DEPTH=2. "
                      f"Use feat(prefix/*): msg. Skipping.")
                continue
            for s in discover_scopes(root_path, depth):
                if exclude_regex and re.search(exclude_regex, s):
                    print(f">>> SKIP: scope '{s}' excluded by SCOPE_EXCLUDE_REGEX")
                    continue
                result.add(f"{msg_type}({s}){breaking}: {description}")

        elif scope.endswith('/*'):
            # feat(base/*) — expand all children of the prefix
            parent = scope[:-2]
            for s in discover_scopes(root_path, depth, parent_prefix=parent):
                if exclude_regex and re.search(exclude_regex, s):
                    print(f">>> SKIP: scope '{s}' excluded by SCOPE_EXCLUDE_REGEX")
                    continue
                result.add(f"{msg_type}({s}){breaking}: {description}")

        else:
            # Explicit scope — still apply exclude_regex
            if exclude_regex and re.search(exclude_regex, scope):
                print(f">>> SKIP: scope '{scope}' excluded by SCOPE_EXCLUDE_REGEX")
                continue
            result.add(msg)

    return result


def _bump_priority(msg):
    """
    Returns version bump priority for deduplication.
      3 — breaking type or ! (major bump)
      2 — feat (minor bump)
      1 — everything else (patch bump)
    """
    type_match = re.match(r'^([a-z]+)\(', msg)
    if not type_match:
        return 0
    msg_type = type_match.group(1)
    if re.search(r'\([^)]+\)!', msg):
        return 3
    return {'breaking': 3, 'feat': 2}.get(msg_type, 1)


def deduplicate_by_scope(messages):
    """
    For each scope, keeps only the highest-priority message.
    If two commits target the same scope (e.g. feat(nati) and breaking(nati)),
    the one with the higher bump priority wins.
    Priority: breaking / ! (3) > feat (2) > fix/chore/others (1).
    """
    by_scope = {}
    for msg in messages:
        scope_match = re.search(r'\(([^)]+)\)', msg)
        if not scope_match:
            continue
        scope = scope_match.group(1)
        if scope not in by_scope or _bump_priority(msg) > _bump_priority(by_scope[scope]):
            by_scope[scope] = msg
    return set(by_scope.values())


def release():
    # ── Load env vars ─────────────────────────────────────────────────────────
    pr_body = os.getenv("PR_BODY", "")
    root_path = os.getenv("PLUGIN_BASE", ".")
    output_tags_file = os.getenv("OUTPUT_TAGS_FILE", "")
    scope_depth = int(os.getenv("SCOPE_DEPTH", "1"))
    exclude_regex = os.getenv("SCOPE_EXCLUDE_REGEX", "")
    global_toml = os.path.join(root_path, "cliff.toml")

    if not os.path.exists(global_toml):
        print(f">>> ERROR: Global cliff.toml not found at {global_toml}")
        return

    # ── depth=0: polyrepo (no scope in PR body) ───────────────────────────────
    if scope_depth == 0:
        messages = parse_pr_body_polyrepo(pr_body)
        if not messages:
            print(">>> No release commits detected in PR Body.")
            return

        # Pick the single highest-priority message for the version bump
        best_msg = max(messages, key=_bump_priority)
        component_tag_pattern = r"^v[0-9]+\.[0-9]+\.[0-9]+$"

        existing_tags = run_command("git tag -l 'v*' --sort=-version:refname")
        latest_tag = existing_tags.stdout.strip().splitlines()[0] if existing_tags.stdout.strip() else None

        if latest_tag:
            bumped = run_command(
                f"git cliff --config {global_toml} "
                f"--tag-pattern '{component_tag_pattern}' "
                f"--bump --bumped-version "
                f"--with-commit '{best_msg}'"
            )
            new_tag = bumped.stdout.strip()
        else:
            new_tag = "v1.0.0"

        tag_res = run_command(f"git tag {new_tag}")
        if tag_res.returncode != 0:
            print(f">>> ERROR tagging {new_tag}: {tag_res.stderr.strip()}")
            return

        changelog_path = os.path.join(root_path, 'CHANGELOG.md')
        output_flag = f"--prepend {changelog_path}" if os.path.exists(changelog_path) else f"--output {changelog_path}"
        cliff_cmd = (
            f"git cliff --config {global_toml} "
            f"--tag-pattern '{component_tag_pattern}' "
            f"--unreleased "
            f"--tag '{new_tag}' "
            f"--with-commit '{best_msg}' "
            f"{output_flag}"
        )
        res = run_command(cliff_cmd)
        if res.returncode == 0:
            print(f">>> SUCCESS: Created {new_tag}")
            if output_tags_file:
                with open(output_tags_file, "a") as f:
                    f.write(f"{new_tag}\n")
        else:
            print(f">>> ERROR: {res.stderr.strip()}")
        return

    # ── depth=1 or depth=2: monorepo / nested monorepo ───────────────────────
    messages = parse_pr_body(pr_body)
    if not messages:
        print(">>> No Conventional Commits detected in PR Body.")
        return

    # Expand wildcards + apply SCOPE_EXCLUDE_REGEX to all scopes
    messages = expand_wildcard(messages, root_path, scope_depth, exclude_regex)

    # Deduplicate: if same scope appears with different types, highest priority wins
    messages = deduplicate_by_scope(messages)

    if not messages:
        print(">>> No components to release after expansion/filtering.")
        return

    for full_msg in messages:
        path_match = re.search(r"\(([^)]+)\)", full_msg)
        if not path_match:
            continue

        rel_path = path_match.group(1)
        full_path = os.path.normpath(os.path.join(root_path, rel_path))

        if not os.path.isdir(full_path):
            print(f">>> SKIP: Directory '{rel_path}' does not exist.")
            continue

        path_slug = rel_path.replace("/", "-").replace("\\", "-")
        print(f"--- Processing: {path_slug} ---")

        existing_tags = run_command(f"git tag -l '{path_slug}-v*' --sort=-version:refname")
        latest_tag = existing_tags.stdout.strip().splitlines()[0] if existing_tags.stdout.strip() else None

        component_tag_pattern = f"^{path_slug}-v[0-9]+\\.[0-9]+\\.[0-9]+$"

        if latest_tag:
            bumped = run_command(
                f"git cliff --config {global_toml} "
                f"--include-path '{rel_path}/**/*' "
                f"--tag-pattern '{component_tag_pattern}' "
                f"--bump --bumped-version "
                f"--with-commit '{full_msg}'"
            )
            new_tag = bumped.stdout.strip()
        else:
            new_tag = f"{path_slug}-v1.0.0"

        tag_res = run_command(f"git tag {new_tag}")
        if tag_res.returncode != 0:
            print(f">>> ERROR tagging {new_tag}: {tag_res.stderr.strip()}")
            continue

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
            if output_tags_file:
                with open(output_tags_file, "a") as f:
                    f.write(f"{new_tag}\n")
        else:
            print(f">>> ERROR for {path_slug}: {res.stderr.strip()}")


if __name__ == "__main__":
    release()
