import subprocess
import re
import os
import shlex
import tomllib


def load_cliff_parsers(toml_path):
    """
    Reads cliff.toml and extracts commit_parsers and bump config.

    Returns (parsers, bump_cfg) where:
      parsers  = [{"message": str, "group": str, "bump_type": str, "skip": bool}, ...]
      bump_cfg = {"features_always_bump_minor": bool,
                  "breakage_always_bump_major": bool,
                  "custom_major_increment_regex": str|None}

    Parsers are ordered — first match wins (same as git-cliff).
    Returns ([], {}) on any read/parse error.
    """
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return [], {}

    raw_parsers = data.get("git", {}).get("commit_parsers", [])
    parsers = [
        {
            "message":   p.get("message", ""),
            "group":     p.get("group", ""),
            "bump_type": p.get("bump_type", ""),
            "skip":      bool(p.get("skip", False)),
        }
        for p in raw_parsers
        if "message" in p
    ]

    raw_bump = data.get("bump", {})
    bump_cfg = {
        "features_always_bump_minor":  raw_bump.get("features_always_bump_minor", True),
        "breakage_always_bump_major":  raw_bump.get("breakage_always_bump_major", True),
        "custom_major_increment_regex": raw_bump.get("custom_major_increment_regex", None),
    }

    return parsers, bump_cfg


def run_command(command):
    """Executes shell commands and captures output."""
    return subprocess.run(command, shell=True, capture_output=True, text=True)


def _known_commit_types(parsers):
    """
    Returns the set of raw message patterns from cliff.toml commit_parsers.
    These ARE the known commit types — no extraction, no transformation.

    Examples (given the default cliff.toml):
      {"^breaking\\((.*)\\)", "^breaking", "^feat\\((.*)\\)", "^feat", ...}
    """
    types = set()
    for p in parsers:
        msg = p.get("message", "")
        if msg:
            types.add(msg)
    return types


def parse_pr_body(body, parsers=None):
    """
    Parses PR body lines matching: type(scope)[loc1, loc2]!: description

    Returns dict[location -> set[commit_str]] where:
      - location is a path string:
          ""          -> root (CHANGELOG at PLUGIN_BASE, tag v1.0.0)
          "nati"      -> nati/ (tag nati-v1.0.0)
          "base/argo" -> base/argo/ (tag base-argo-v1.0.0)
      - commit_str is the line with [locations] removed — passed as-is to git-cliff.
          git-cliff (filter_unconventional = true) validates bang/colon/description.
          feat(auth)[nati]!: add login  ->  feat(auth)!: add login
          feat[nati]: add login          ->  feat: add login

    Multi-line blocks:
      After bracket removal, all following lines are collected as continuation
      until the next line that matches a parser pattern with '['.
      Blank lines are included;

    Empty [] means root location (empty string key in the returned dict).
    """
    if parsers is None:
        parsers = []

    if not parsers:
        print(">>> ERROR: cliff.toml commit_parsers has no valid message patterns — cannot parse commits.")
        return {}

    bracket_re = re.compile(r'\[([^[\]]*)\]')

    def _match_line(current_line):
        """Return bracket_match if line matches any parser pattern with [ immediately after. First-match-wins."""
        for p in parsers:
            msg = p.get("message", "")
            if not msg:
                continue
            pattern_match = re.match(msg, current_line)
            if pattern_match and current_line[pattern_match.end():pattern_match.end()+1] == '[':
                bracket_match = bracket_re.match(current_line, pattern_match.end())
                if bracket_match:
                    return bracket_match
        return None

    result = {}
    lines = body.splitlines() if body else []
    i = 0

    while i < len(lines):
        current_line = lines[i]
        bracket_match = _match_line(current_line)

        if bracket_match:
            raw_locs  = bracket_match.group(1)
            locations = [loc.strip() for loc in raw_locs.split(",")]
            commit_str = current_line[:bracket_match.start()] + current_line[bracket_match.end():]

            i += 1
            continuation = []
            while i < len(lines):
                if _match_line(lines[i]):
                    break
                continuation.append(lines[i])
                i += 1
            if continuation:
                commit_str = commit_str.rstrip() + " " + "\n".join(continuation)

            for loc in locations:
                result.setdefault(loc, set()).add(commit_str)
        else:
            i += 1

    return result


def _expand_locations(location_to_commits, root_path, exclude_regex=""):
    """
    Expands wildcard locations and applies SCOPE_EXCLUDE_REGEX.

    Wildcard rules:
      [*]       -> all direct subdirs of root_path
      [base/*]  -> all subdirs of root_path/base/
      [""]      -> root, passes through as-is

    SCOPE_EXCLUDE_REGEX is applied to ALL locations including root ("").
    Returns new dict with wildcards replaced by concrete locations.
    If there are no wildcards and no exclusions, returns the original dict unchanged.
    """
    has_wildcard = any("*" in loc for loc in location_to_commits)
    has_exclude = bool(exclude_regex)

    if not has_wildcard and not has_exclude:
        return location_to_commits

    result = {}

    for loc, commits in location_to_commits.items():
        if loc == "*":
            # [*] -> all direct subdirs of root_path
            try:
                subdirs = sorted(
                    e for e in os.listdir(root_path)
                    if os.path.isdir(os.path.join(root_path, e))
                )
            except OSError:
                subdirs = []
            for subdir in subdirs:
                if exclude_regex and re.search(exclude_regex, subdir):
                    print(f">>> SKIP: location '{subdir}' excluded by SCOPE_EXCLUDE_REGEX")
                    continue
                result.setdefault(subdir, set()).update(commits)

        elif loc.endswith("/*"):
            # [base/*] -> all subdirs of root_path/base/
            parent = loc[:-2]
            scan_dir = os.path.join(root_path, parent)
            try:
                subdirs = sorted(
                    f"{parent}/{e}" for e in os.listdir(scan_dir)
                    if os.path.isdir(os.path.join(scan_dir, e))
                )
            except OSError:
                subdirs = []
            for subdir in subdirs:
                if exclude_regex and re.search(exclude_regex, subdir):
                    print(f">>> SKIP: location '{subdir}' excluded by SCOPE_EXCLUDE_REGEX")
                    continue
                result.setdefault(subdir, set()).update(commits)

        else:
            # Explicit location (including "" for root)
            if exclude_regex and re.search(exclude_regex, loc):
                display = loc if loc else "(root)"
                print(f">>> SKIP: location '{display}' excluded by SCOPE_EXCLUDE_REGEX")
                continue
            result.setdefault(loc, set()).update(commits)

    return result


def _print_cliff_rules(parsers, bump_cfg):
    """Prints a human-readable summary of cliff.toml commit_parsers."""
    print(">>> cliff.toml bump rules:")
    print(f"    features_always_bump_minor  = {bump_cfg.get('features_always_bump_minor', True)}")
    print(f"    breakage_always_bump_major  = {bump_cfg.get('breakage_always_bump_major', True)}")
    custom = bump_cfg.get("custom_major_increment_regex")
    if custom:
        print(f"    custom_major_increment_regex = {custom}")

    if not parsers:
        print("    (no commit_parsers found — git-cliff will use its defaults)")
        return

    bump_labels = {3: "MAJOR", 2: "MINOR", 1: "PATCH", 0: "SKIP "}
    print("    commit_parsers (first match wins):")
    for p in parsers:
        pattern = p.get("message", "?")
        group   = p.get("group", "")
        skip    = p.get("skip", False)
        btype   = p.get("bump_type", "")

        if skip:
            level = 0
        elif btype == "major":
            level = 3
        elif btype == "minor":
            level = 2
        elif bump_cfg.get("features_always_bump_minor", True) and "feature" in group.lower():
            level = 2
        else:
            level = 1

        label = bump_labels.get(level, "?    ")
        group_str = f" -> {group}" if group else ""
        print(f"      [{label}]  pattern={pattern!r}{group_str}")

    print("    No parser matched         -> SKIP (no release)")
    print("    Note: '!' bang always -> MAJOR")


def _print_location_commits(location_to_commits):
    """Prints commits grouped by location."""
    print(">>> Commits to process:")
    for loc in sorted(location_to_commits):
        display_loc = loc if loc else "(root)"
        print(f"    [{display_loc}]")
        for commit in sorted(location_to_commits[loc]):
            print(f"      {commit!r}")


def release():
    # ── Load env vars ─────────────────────────────────────────────────────────
    pr_body             = os.getenv("PLUGIN_MESSAGE", "")
    root_path           = os.getenv("PLUGIN_BASE", ".")
    output_tags_file    = os.getenv("PLUGIN_OUTPUT_TAGS_FILE", "")
    exclude_regex       = os.getenv("PLUGIN_SCOPE_EXCLUDE_REGEX", "")
    debug               = os.getenv("PLUGIN_DEBUG", "false").lower() == "true"
    initial_tag_version = os.getenv("PLUGIN_INITIAL_TAG", "1.0.0").lstrip("v")
    version_prefix      = "v" if os.getenv("PLUGIN_V_PREFIX", "").lower() == "true" else ""

    _bundled_toml = os.path.join(os.path.dirname(__file__), "cliff.toml")
    global_toml   = os.getenv("PLUGIN_CLIFF_TOML") or ("./cliff.toml" if os.path.exists("./cliff.toml") else _bundled_toml)
    cliff_cmd_base = f"git cliff --config {global_toml}" + (" -vv" if debug else "")

    if not os.path.exists(global_toml):
        print(f">>> ERROR: cliff.toml not found at {global_toml}")
        return

    parsers, bump_cfg = load_cliff_parsers(global_toml)

    if debug:
        _print_cliff_rules(parsers, bump_cfg)

    # ── Parse PR body ─────────────────────────────────────────────────────────
    location_to_commits = parse_pr_body(pr_body, parsers)

    if not location_to_commits:
        print(">>> No release commits detected in PR Body.")
        return

    if debug:
        _print_location_commits(location_to_commits)

    # ── Expand wildcards + apply exclusions ───────────────────────────────────
    location_to_commits = _expand_locations(location_to_commits, root_path, exclude_regex)

    if not location_to_commits:
        print(">>> No components to release after expansion/filtering.")
        return

    # ── Process each location ─────────────────────────────────────────────────
    for location in sorted(location_to_commits):
        commits = location_to_commits[location]
        is_root = (location == "")

        # Slug and tag components
        vp = re.escape(version_prefix)
        if is_root:
            path_slug             = ""
            tag_prefix            = version_prefix
            tag_glob              = f"{version_prefix}[0-9]*"
            component_tag_pattern = f"^{vp}[0-9]+\\.[0-9]+\\.[0-9]+$"
            full_path             = os.path.normpath(root_path)
        else:
            path_slug             = location.replace("/", "-").replace("\\", "-")
            tag_prefix            = f"{path_slug}-{version_prefix}"
            tag_glob              = f"{path_slug}-{version_prefix}[0-9]*"
            component_tag_pattern = f"^{path_slug}-{vp}[0-9]+\\.[0-9]+\\.[0-9]+$"
            full_path             = os.path.normpath(os.path.join(root_path, location))

        display_name = location if location else "(root)"
        print(f"--- Processing: {display_name} ---")

        # Skip non-existent directories (root is always assumed to exist)
        if not is_root and not os.path.isdir(full_path):
            print(f">>> SKIP: Directory '{location}' does not exist.")
            continue

        # ── STEP 1: FIND EXISTING TAGS ────────────────────────────────────────
        existing_tags_result = run_command(f"git tag -l '{tag_glob}' --sort=-version:refname")
        all_matching_tags = existing_tags_result.stdout.strip().splitlines()
        latest_tag = all_matching_tags[0] if all_matching_tags else None

        if debug:
            print(f">>> [DEBUG] Tag glob:          '{tag_glob}'")
            print(f">>> [DEBUG] All matching tags: {all_matching_tags or '(none)'}")
            first_tag = f"{tag_prefix}{initial_tag_version}"
            print(f">>> [DEBUG] Latest tag (base): "
                  f"{latest_tag or f'(none — first release → will use {first_tag})'}")

        # Build --with-commit args (shell-safe quoting handles special chars)
        all_commits = sorted(commits)
        with_commit_args = " ".join(f"--with-commit {shlex.quote(c)}" for c in all_commits)

        if debug:
            print(f">>> [DEBUG] Commits: {all_commits}")

        # ── STEP 2: CALCULATE VERSION ─────────────────────────────────────────
        if latest_tag:
            bump_cmd = " ".join(filter(None, [
                cliff_cmd_base,
                f"--tag-pattern '{component_tag_pattern}'",
                "--bump --bumped-version",
                with_commit_args,
                "-- HEAD..HEAD",
            ]))

            if debug:
                print(f">>> [DEBUG] bump_cmd: {bump_cmd}")

            bumped = run_command(bump_cmd)

            if debug:
                print(f">>> [DEBUG] bump stdout: {bumped.stdout.strip()}")
                if bumped.stderr.strip():
                    print(">>> [DEBUG] bump stderr:")
                    for line in bumped.stderr.strip().splitlines():
                        print(f"    {line}")

            new_tag = bumped.stdout.strip()
            if not new_tag:
                print(f">>> SKIP: no releasable commits for {display_name}")
                continue

            if debug:
                print(f">>> [DEBUG] Calculated new_tag: {new_tag!r}")
        else:
            new_tag = f"{tag_prefix}{initial_tag_version}"
            if debug:
                print(f">>> [DEBUG] No existing tag — first release: {new_tag}")

        # ── STEP 3: GENERATE CHANGELOG ────────────────────────────────────────
        changelog_path = os.path.join(full_path, "CHANGELOG.md")
        if os.path.exists(changelog_path):
            output_flag = f"--prepend {changelog_path}"
            if debug:
                print(f">>> [DEBUG] CHANGELOG exists — using --prepend")
        else:
            output_flag = f"--output {changelog_path}"
            if debug:
                print(f">>> [DEBUG] CHANGELOG not found — using --output")

        cliff_cmd = " ".join(filter(None, [
            cliff_cmd_base,
            f"--tag-pattern '{component_tag_pattern}'",
            f"--tag '{new_tag}'",
            with_commit_args,
            output_flag,
            "-- HEAD..HEAD",
        ]))

        if debug:
            print(f">>> [DEBUG] cliff_cmd: {cliff_cmd}")

        res = run_command(cliff_cmd)

        if debug:
            print(f">>> [DEBUG] cliff stdout: {res.stdout.strip()}")
            if res.stderr.strip():
                print(">>> [DEBUG] cliff stderr:")
                for line in res.stderr.strip().splitlines():
                    print(f"    {line}")

        if res.returncode != 0:
            print(f">>> ERROR generating changelog for {display_name}: {res.stderr.strip()}")
            continue

        # ── STEP 4: RECORD TAG ────────────────────────────────────────────────
        # Tags are created in the CI "Push changelogs to Git" step so they land
        # on the commit that includes the CHANGELOG.md changes.
        print(f">>> SUCCESS: Prepared {new_tag} (tag will be created after changelog commit)")
        if output_tags_file:
            with open(output_tags_file, "a") as f:
                f.write(f"{new_tag}\n")


if __name__ == "__main__":
    release()
