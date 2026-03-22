import subprocess
import re
import os


def load_cliff_parsers(toml_path):
    """
    Reads cliff.toml and extracts commit_parsers and bump config.

    Returns (parsers, bump_cfg) where:
      parsers  = [{"message": str, "group": str, "bump_type": str|None, "skip": bool}, ...]
      bump_cfg = {"features_always_bump_minor": bool,
                  "breakage_always_bump_major": bool,
                  "custom_major_increment_regex": str|None}

    Parsers are ordered — first match wins (same as git-cliff).
    Returns ([], {}) on any read/parse error.
    """
    try:
        with open(toml_path) as f:
            content = f.read()
    except OSError:
        return [], {}

    parsers = []
    cp_match = re.search(r'commit_parsers\s*=\s*\[(.*?)\]', content, re.DOTALL)
    if cp_match:
        for entry in re.finditer(r'\{([^}]+)\}', cp_match.group(1)):
            kv_str = entry.group(1)
            p = {}
            for kv in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', kv_str):
                p[kv.group(1)] = kv.group(2)
            skip_m = re.search(r'\bskip\s*=\s*(true|false)', kv_str)
            p['skip'] = skip_m.group(1) == 'true' if skip_m else False
            if 'message' in p:
                parsers.append(p)

    bump_cfg = {
        'features_always_bump_minor': True,
        'breakage_always_bump_major': True,
        'custom_major_increment_regex': None,
    }
    for key in ('features_always_bump_minor', 'breakage_always_bump_major'):
        m = re.search(rf'{key}\s*=\s*(true|false)', content)
        if m:
            bump_cfg[key] = m.group(1) == 'true'
    m = re.search(r'custom_major_increment_regex\s*=\s*"([^"]*)"', content)
    if m:
        bump_cfg['custom_major_increment_regex'] = m.group(1)

    return parsers, bump_cfg


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

    scopeless_re = r"^([a-z]+)(!?):\s*(.*)"

    for line in body.splitlines():
        stripped = line.strip()
        match = re.match(pattern, stripped, re.IGNORECASE)
        if match:
            msg_type, raw_scopes, breaking, description = match.groups()
            for scope in raw_scopes.split(','):
                release_set.add(f"{msg_type.lower()}({scope.strip()}){breaking}: {description.strip()}")
            continue

        # Warn about scopeless lines (valid at depth=0 but not here)
        if re.match(scopeless_re, stripped, re.IGNORECASE):
            print(f">>> WARN: '{stripped}' — no scope found, line ignored.")
            print(f"          SCOPE_DEPTH=1/2 requires a scope: use 'type(scope): msg'  e.g. 'fix(nati): msg'")
            print(f"          For a single-service repo use SCOPE_DEPTH=0 instead.")

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


def _bump_priority(msg, parsers=None, bump_cfg=None):
    """
    Returns version bump priority for deduplication.
      3 — major bump  (breaking type, ! bang, bump_type=major, or custom_major_increment_regex)
      2 — minor bump  (feat / bump_type=minor / features_always_bump_minor group)
      1 — patch bump  (fix and other non-skip types)
      0 — skip        (matches a skip=true parser, or no parser matched)

    When parsers is provided (loaded from cliff.toml), priority is driven entirely
    by commit_parsers — first matching parser wins, same as git-cliff.
    Falls back to hardcoded logic when parsers is None or empty.
    """
    # ! bang notation is always a breaking change (Conventional Commits standard)
    if re.search(r'\([^)]+\)!:', msg) or re.match(r'^[a-z]+!:', msg):
        return 3

    if parsers:
        bump_cfg = bump_cfg or {}
        custom_major_re = bump_cfg.get('custom_major_increment_regex')
        features_minor = bump_cfg.get('features_always_bump_minor', True)

        if custom_major_re and re.search(custom_major_re, msg):
            return 3

        for p in parsers:
            if re.search(p['message'], msg):
                if p.get('skip'):
                    return 0
                if p.get('bump_type') == 'major':
                    return 3
                if p.get('bump_type') == 'minor':
                    return 2
                if features_minor and 'feature' in p.get('group', '').lower():
                    return 2
                return 1
        return 0  # no parser matched

    # Fallback: hardcoded (used when called without cliff.toml parsers)
    type_match = re.match(r'^([a-z]+)\(', msg)
    if not type_match:
        return 0
    msg_type = type_match.group(1)
    return {'breaking': 3, 'feat': 2}.get(msg_type, 1)


def deduplicate_by_scope(messages, parsers=None, bump_cfg=None):
    """
    For each scope, keeps only the highest-priority message.
    If two commits target the same scope (e.g. feat(nati) and breaking(nati)),
    the one with the higher bump priority wins.
    Priority: breaking / ! (3) > feat (2) > fix/others (1) > skip (0).
    """
    by_scope = {}
    for msg in messages:
        scope_match = re.search(r'\(([^)]+)\)', msg)
        if not scope_match:
            continue
        scope = scope_match.group(1)
        priority = _bump_priority(msg, parsers, bump_cfg)
        if scope not in by_scope or priority > _bump_priority(by_scope[scope], parsers, bump_cfg):
            by_scope[scope] = msg
    return set(by_scope.values())


def _print_cliff_rules(parsers, bump_cfg):
    """
    Prints a human-readable summary of how cliff.toml commit_parsers
    map commit types to version bump levels.
    """
    print(">>> cliff.toml bump rules:")
    print(f"    features_always_bump_minor  = {bump_cfg.get('features_always_bump_minor', True)}")
    print(f"    breakage_always_bump_major  = {bump_cfg.get('breakage_always_bump_major', True)}")
    custom = bump_cfg.get('custom_major_increment_regex')
    if custom:
        print(f"    custom_major_increment_regex = {custom}")

    if not parsers:
        print("    (no commit_parsers found — using hardcoded fallback)")
        return

    bump_labels = {3: "MAJOR", 2: "MINOR", 1: "PATCH", 0: "SKIP "}
    print("    commit_parsers (first match wins):")
    for p in parsers:
        pattern = p.get('message', '?')
        group   = p.get('group', '')
        skip    = p.get('skip', False)
        btype   = p.get('bump_type', '')

        if skip:
            level = 0
        elif btype == 'major':
            level = 3
        elif btype == 'minor':
            level = 2
        elif bump_cfg.get('features_always_bump_minor', True) and 'feature' in group.lower():
            level = 2
        else:
            level = 1 if not skip else 0

        label = bump_labels.get(level, '?    ')
        group_str = f" → {group}" if group else ""
        print(f"      [{label}]  pattern={pattern!r}{group_str}")

    print("    No parser matched         → SKIP (no release)")
    print("    Note: '!' bang (e.g. feat!: or feat(scope)!:) always → MAJOR, checked before any parser — even skip types are overridden")


def _print_message_classification(messages, parsers, bump_cfg):
    """
    For each commit message, prints which cliff.toml parser rule it matched
    and what bump level that produces.
    """
    bump_labels = {3: "MAJOR", 2: "MINOR", 1: "PATCH", 0: "SKIP "}
    print(">>> Commit classification:")
    for msg in sorted(messages):
        priority = _bump_priority(msg, parsers, bump_cfg)
        label = bump_labels.get(priority, "?    ")
        # Find the matched parser pattern for display
        rule_str = "no parser matched"
        if re.search(r'\([^)]+\)!:', msg) or re.match(r'^[a-z]+!:', msg):
            rule_str = "! bang → always MAJOR (Conventional Commits standard)"
        elif parsers:
            custom_major_re = bump_cfg.get('custom_major_increment_regex') if bump_cfg else None
            if custom_major_re and re.search(custom_major_re, msg):
                rule_str = f"custom_major_increment_regex={custom_major_re!r}"
            else:
                for p in parsers:
                    if re.search(p['message'], msg):
                        rule_str = f"pattern={p['message']!r}"
                        if p.get('group'):
                            rule_str += f" → {p['group']}"
                        break
                        
        print(f"    [{label}]  {msg!r}  ({rule_str})")


def release():
    # ── Load env vars ─────────────────────────────────────────────────────────
    pr_body = os.getenv("PR_BODY", "")
    root_path = os.getenv("PLUGIN_BASE", ".")
    output_tags_file = os.getenv("OUTPUT_TAGS_FILE", "")
    scope_depth = int(os.getenv("SCOPE_DEPTH", "1"))
    exclude_regex = os.getenv("SCOPE_EXCLUDE_REGEX", "")
    _script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
    global_toml = os.path.join(_script_dir, "cliff.toml")

    if not os.path.exists(global_toml):
        print(f">>> ERROR: Global cliff.toml not found at {global_toml}")
        return

    parsers, bump_cfg = load_cliff_parsers(global_toml)
    _print_cliff_rules(parsers, bump_cfg)

    # ── depth=0: polyrepo (no scope in PR body) ───────────────────────────────
    if scope_depth == 0:
        messages = parse_pr_body_polyrepo(pr_body)
        if not messages:
            print(">>> No release commits detected in PR Body.")
            return

        _print_message_classification(messages, parsers, bump_cfg)

        # Filter out skip-only commits before picking the best
        messages = {m for m in messages if _bump_priority(m, parsers, bump_cfg) > 0}
        if not messages:
            print(">>> No release commits detected in PR Body.")
            return

        # Pick the single highest-priority message for the version bump
        best_msg = max(messages, key=lambda m: _bump_priority(m, parsers, bump_cfg))
        component_tag_pattern = r"^v[0-9]+\.[0-9]+\.[0-9]+$"

        existing_tags = run_command("git tag -l 'v*' --sort=-version:refname")
        latest_tag = existing_tags.stdout.strip().splitlines()[0] if existing_tags.stdout.strip() else None

        if latest_tag:
            bumped = run_command(
                f"git cliff --config {global_toml} "
                f"--tag-pattern '{component_tag_pattern}' "
                f"--bump --bumped-version "
                f"--with-commit '{best_msg}' --prepend"
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

    _print_message_classification(messages, parsers, bump_cfg)

    # Filter commits that cliff.toml marks as skip (e.g. chore, docs, ci)
    messages = {m for m in messages if _bump_priority(m, parsers, bump_cfg) > 0}
    if not messages:
        print(">>> No release commits detected in PR Body.")
        return

    # Expand wildcards + apply SCOPE_EXCLUDE_REGEX to all scopes
    messages = expand_wildcard(messages, root_path, scope_depth, exclude_regex)

    # Collect ALL messages per scope BEFORE dedup (for changelog — scenario B)
    all_by_scope = {}
    for _m in messages:
        _s = re.search(r'\(([^)]+)\)', _m)
        if _s:
            all_by_scope.setdefault(_s.group(1), set()).add(_m)

    # Deduplicate: highest priority message per scope drives the version bump only
    messages = deduplicate_by_scope(messages, parsers, bump_cfg)

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

        # All commits for this scope: breaking (!) first, then by priority descending
        all_scope_msgs = sorted(
            all_by_scope.get(rel_path, {full_msg}),
            key=lambda m: _bump_priority(m, parsers, bump_cfg),
            reverse=True,
        )
        with_commit_args = " ".join(f"--with-commit '{m}'" for m in all_scope_msgs)

        changelog_path = os.path.join(full_path, 'CHANGELOG.md')
        output_flag = f"--prepend {changelog_path}"
        cliff_cmd = (
            f"git cliff --config {global_toml} "
            f"--include-path '{rel_path}/**/*' "
            f"--tag-pattern '{component_tag_pattern}' "
            f"--unreleased "
            f"--tag '{new_tag}' "
            f"{with_commit_args} "
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