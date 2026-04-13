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
        "features_always_bump_minor":   raw_bump.get("features_always_bump_minor",  None),
        "breakage_always_bump_major":   raw_bump.get("breakage_always_bump_major",  None),
        "custom_major_increment_regex": raw_bump.get("custom_major_increment_regex", None),
        "custom_minor_increment_regex": raw_bump.get("custom_minor_increment_regex", None),
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
      {"^breaking", "^feat", ...}
    """
    types = set()
    for p in parsers:
        msg = p.get("message", "")
        if msg:
            types.add(msg)
    return types


def parse_pr_body(body, parsers=None, changelog_level=None):
    """
    Parses PR body lines matching: type[loc1, loc2]!: description

    Returns dict[location -> set[commit_str]] where:
      - location is a path string:
          ""          -> root (CHANGELOG at PLUGIN_BASE_PATH, tag v1.0.0)
          "nati"      -> nati/ (tag nati-v1.0.0)
          "base/argo" -> base/argo/ (tag base-argo-v1.0.0)
      - commit_str is the line with [locations] removed — passed as-is to git-cliff.
          feat[nati]!: add login  ->  feat!: add login
          feat[nati]: add login          ->  feat: add login

    changelog_level (int | None):
      Enforces the expected depth of every location in the PR body.
        level 0  -> only root (empty bracket []) is accepted
        level N  -> locations with exactly N-1 forward slashes:
                    1 -> "nati"           (0 slashes)
                    2 -> "plugins/docker" (1 slash)
                    3 -> "base/infra/x"   (2 slashes)
      If ANY location in a line fails the check:
        - Any in-progress continuation from the previous commit is finalized
          (the inner loop already breaks on any commit-pattern line, so the
          previous commit is completed naturally before we reach this check).
        - The current line is skipped (logged) and the loop moves to i+1.

    Multi-line blocks:
      After bracket removal, all following lines are collected as continuation
      until the next commit-pattern line (matched by _match_line, regardless
      of level). A level-failing commit line therefore acts as a commit
      boundary and ends the preceding continuation.
      Blank lines are included.

    Empty [] means root location (empty string key in the returned dict).
    """
    if parsers is None:
        parsers = []

    if not parsers:
        print(">>> ERROR: cliff.toml commit_parsers has no valid message patterns — cannot parse commits.")
        return {}

    bracket_re = re.compile(r'\[([^[\]]*)\]')

    def _match_line(current_line):
        """Return bracket_match if line matches any parser pattern with [ immediately after,
        and after the closing ] has at most one ! then :. First-match-wins."""
        for p in parsers:
            msg = p.get("message", "")
            if not msg:
                continue
            pattern_match = re.match(msg, current_line)
            if pattern_match and current_line[pattern_match.end():pattern_match.end()+1] == '[':
                bracket_match = bracket_re.match(current_line, pattern_match.end())
                if bracket_match and re.match(r'^!?:', current_line[bracket_match.end():]):
                    return bracket_match
        return None

    def _matches_level(location):
        """Returns True if location satisfies the required changelog_level."""
        if changelog_level is None:
            return True
        if changelog_level == 0:
            return location == ""
        if location == "":
            return False
        # Reject empty segments: leading /, trailing /, or consecutive //
        if "" in location.split("/"):
            return False
        return location.count("/") == changelog_level - 1

    result = {}
    lines = body.splitlines() if body else []
    i = 0

    while i < len(lines):
        current_line = lines[i]
        bracket_match = _match_line(current_line)

        if bracket_match:
            raw_locs  = bracket_match.group(1)
            locations = [loc.strip() for loc in raw_locs.split(",")]

            # Level check — any failing location: skip this line, move to next
            failed = [loc for loc in locations if not _matches_level(loc)]
            if failed:
                def _level_reason(loc):
                    if changelog_level == 0:
                        return f"'{loc}' — non-empty location, level 0 expects empty []"
                    if loc == "":
                        return f"'' — empty location, a component name is required at level {changelog_level}"
                    segments = loc.split("/")
                    if "" in segments:
                        if loc.startswith("/"):
                            return f"'{loc}' — leading slash, missing component name before first '/'"
                        if loc.endswith("/"):
                            return f"'{loc}' — trailing slash, missing component name after last '/'"
                        return f"'{loc}' — consecutive '//', missing component name between slashes"
                    actual = loc.count("/")
                    expected_slashes = changelog_level - 1
                    return (
                        f"'{loc}' — wrong depth: location has {actual} slash(es) ({actual + 1} path segment(s)), "
                        f"but PLUGIN_CHANGELOG_LEVEL={changelog_level} requires exactly {expected_slashes} slash(es) "
                        f"({changelog_level} path segment(s)). "
                        f"Example of a valid location at level {changelog_level}: "
                        f"{'/'.join(['component'] * changelog_level)}"
                    )

                reasons = "; ".join(_level_reason(loc) for loc in failed)
                print(f">>> SKIP: '{current_line.rstrip()}' — {reasons}")
                i += 1
                continue

            commit_str = current_line[:bracket_match.start()] + current_line[bracket_match.end():]
            loc_display = ", ".join(f"'{loc}'" if loc else "''" for loc in locations)
            print(f">>> ACCEPT: '{current_line.rstrip()}' — location(s) {loc_display}")

            # Collect continuation lines until the next commit-pattern line.
            # A level-failing commit line still matches _match_line and will
            # break this loop — finalizing this commit cleanly.
            i += 1
            continuation = []
            while i < len(lines):
                if _match_line(lines[i]):
                    break
                continuation.append(lines[i])
                if lines[i].strip():
                    print(f">>> CONTINUATION: '{lines[i].rstrip()}' — body of above commit")
                i += 1
            if continuation:
                commit_str = commit_str.rstrip() + "\n" + "\n".join(continuation)

            for loc in locations:
                result.setdefault(loc, set()).add(commit_str)
        else:
            if current_line.strip():
                print(f">>> IGNORED: '{current_line.rstrip()}' — does not match any commit pattern")
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
                    print(f"\033[33m    >>> SKIP: location '{subdir}' excluded by SCOPE_EXCLUDE_REGEX\033[0m")
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
                    print(f"\033[33m    >>> SKIP: location '{subdir}' excluded by SCOPE_EXCLUDE_REGEX\033[0m")
                    continue
                result.setdefault(subdir, set()).update(commits)

        else:
            # Explicit location (including "" for root)
            if exclude_regex and re.search(exclude_regex, loc):
                display = loc if loc else ""
                print(f"\033[33m    >>> SKIP: location '{display}' excluded by SCOPE_EXCLUDE_REGEX\033[0m")
                continue
            result.setdefault(loc, set()).update(commits)

    return result


def _print_cliff_rules(parsers, bump_cfg, toml_path=None):
    """Prints the raw cliff.toml content and commit line structure examples."""

    # ── Print commit_parsers section from cliff.toml as-is ───────────────────
    if toml_path:
        try:
            with open(toml_path) as f:
                lines = f.readlines()
            print(">>> cliff.toml commit_parsers:")
            inside = False
            for line in lines:
                if not inside and "commit_parsers" in line and "[" in line:
                    inside = True
                if inside:
                    print(f"    {line}", end="")
                    if line.rstrip().endswith("]"):
                        break
        except OSError:
            print(f">>> cliff.toml: (could not read {toml_path})")
    print("")

    if not parsers:
        print(">>> (no commit_parsers found — git-cliff will use its defaults)")
        return

    # ── Commit line structure ─────────────────────────────────────────────────
    print(">>> How a commit line must look:")
    print("      type[location]: description")
    print("      type[location]!: description")
    print("")
    print("    Rules:")
    print("      - 'type' must start at the very beginning of the line — NO leading spaces")
    print("      - 'type' must be lowercase and must be one of the commit types defined in the")
    print("        cliff.toml commit_parsers shown above (e.g. feat, fix, chore, ...). Any other")
    print("        type is either skipped or treated as unreleasable, depending on your cliff.toml")
    print("      - '[location]' must follow the type immediately — no space between them")
    print("      - After ']' ONLY ':' or '!:' are valid — anything else (space, '!!', etc.)")
    print("        causes the line to be treated as continuation text of the previous commit")
    print("      - '!' forces a major bump regardless of type")
    print("      - Multiple locations: type[loc1, loc2]: description")
    print("")
    print("    Examples based on your cliff.toml:")

    seen = set()
    for p in parsers:
        pattern = p.get("message", "")
        skip    = p.get("skip", False)
        tname   = pattern.lstrip("^").split("\\")[0].split("(")[0].rstrip()
        if tname and tname not in seen:
            seen.add(tname)
            suffix = "  (no release)" if skip else ""
            print(f"      {tname}[myservice]: your description here{suffix}")


def _print_location_commits(location_to_commits):
    """Prints commits grouped by location."""
    # \033[1;4;33m = Bold (1) + Underline (4) + Yellow (33)
    print("\033[1;4;33m>>> COMMITS TO PROCESS:\033[0m")
    print("\033[33m    Each [location] is the component whose CHANGELOG.md will be updated and versioned.\033[0m")
    print("\033[33m    The commits listed under it are the exact entries that will be written into that changelog.\033[0m")
    for loc in sorted(location_to_commits):
        display_loc = loc if loc else ""
        print(f"    [{display_loc}]")
        for commit in sorted(location_to_commits[loc]):
    #  \n inside a commit string will render as an actual newline with proper indentation, instead of showing as a literal \n.
            print("      " + commit.replace("\n", "\n      "))


def release():
    # ── Validate required env vars ────────────────────────────────────────────
    if not os.getenv("PLUGIN_CHANGELOG_LEVEL"):
        print(">>> ERROR: PLUGIN_CHANGELOG_LEVEL is required but not set.")
        print("           This variable enforces the expected depth of component locations in your PR body.")
        print("           It prevents accidentally releasing at the wrong level of your monorepo.")
        print("")
        print("           Level 0 -> root only:                  feat[][...] (empty bracket)")
        print("           Level 1 -> top-level dirs:             feat[nati][...]")
        print("           Level 2 -> one level nested:           feat[plugins/docker][...]")
        print("           Level 3 -> two levels nested:          feat[base/infra/docker][...]")
        print("")
        print("           Example: PLUGIN_CHANGELOG_LEVEL=1")
        return

    # ── Load env vars ─────────────────────────────────────────────────────────
    try:
        changelog_level = int(os.getenv("PLUGIN_CHANGELOG_LEVEL"))
    except (TypeError, ValueError):
        print(">>> ERROR: PLUGIN_CHANGELOG_LEVEL must be a non-negative integer (e.g. 1).")
        return

    message_file = os.getenv("PLUGIN_MESSAGE_FILE", "")
    if not message_file:
        print(">>> ERROR: PLUGIN_MESSAGE_FILE is required but not set.")
        print("           Set it to the path of the file containing the PR/commit message.")
        print("           Example: PLUGIN_MESSAGE_FILE=pr_body.txt")
        return
    try:
        with open(message_file) as _f:
            pr_body = _f.read()
    except OSError as e:
        print(f">>> ERROR: Cannot read PLUGIN_MESSAGE_FILE='{message_file}': {e}")
        return
    root_path           = os.getenv("PLUGIN_BASE_PATH", ".")
    output_tags_file    = os.getenv("PLUGIN_OUTPUT_TAGS_FILE", "")
    exclude_regex       = os.getenv("PLUGIN_SCOPE_EXCLUDE_REGEX", "")
    try:
        verbose = int(os.getenv("PLUGIN_VERBOSE", "0"))
    except ValueError:
        verbose = 0
    initial_tag_version = os.getenv("PLUGIN_INITIAL_TAG", "1.0.0").lstrip("v")
    version_prefix      = "v" if os.getenv("PLUGIN_V_PREFIX", "").lower() == "true" else ""

    _bundled_toml = os.path.join(os.path.dirname(__file__), "cliff.toml")
    global_toml   = os.getenv("PLUGIN_CLIFF_TOML") or ("./cliff.toml" if os.path.exists("./cliff.toml") else _bundled_toml)
    _cliff_verbose = " -vv" if verbose >= 2 else (" -v" if verbose == 1 else "")
    cliff_cmd_base = f"git cliff --config {global_toml}{_cliff_verbose}"

    if not os.path.exists(global_toml):
        print(f">>> ERROR: cliff.toml not found at {global_toml}")
        return

    parsers, bump_cfg = load_cliff_parsers(global_toml)

    _print_cliff_rules(parsers, bump_cfg, global_toml)

    print(f">>> PLUGIN_CHANGELOG_LEVEL={changelog_level}")
    print(f">>> PLUGIN_BASE_PATH='{root_path}' — root directory; all [location] paths are resolved relative to this")

    # ── Parse PR body ─────────────────────────────────────────────────────────
    location_to_commits = parse_pr_body(pr_body, parsers, changelog_level=changelog_level)

    if not location_to_commits:
        print(">>> No release commits detected in PR Body.")
        return

    _print_location_commits(location_to_commits)

    # ── Expand wildcards + apply exclusions ───────────────────────────────────
    had_wildcards = any("*" in loc for loc in location_to_commits)
    location_to_commits = _expand_locations(location_to_commits, root_path, exclude_regex)

    if not location_to_commits:
        print(">>> No components to release after expansion/filtering.")
        return

    if had_wildcards:
        print("\033[1;4;33m>>> COMMITS AFTER WILDCARD EXPANSION:\033[0m")
        print("\033[33m    Wildcards replaced with concrete component paths.\033[0m")
        for loc in sorted(location_to_commits):
            display_loc = loc if loc else ""
            print(f"    [{display_loc}]")
            for commit in sorted(location_to_commits[loc]):
                print("      " + commit.replace("\n", "\n      "))

    # ── Process each location ─────────────────────────────────────────────────
    created_tags = []
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
        print("")
        print(f"\033[1;31m--- Processing: {display_name} ---\033[0m")
        print("")

        # Skip non-existent directories (root is always assumed to exist)
        if not is_root and not os.path.isdir(full_path):
            print(f">>> SKIP: Directory '{location}' does not exist.")
            continue

        # ── STEP 1: FIND EXISTING TAGS ────────────────────────────────────────
        existing_tags_result = run_command(f"git tag -l '{tag_glob}' --sort=-version:refname")
        all_matching_tags = existing_tags_result.stdout.strip().splitlines()
        latest_tag = all_matching_tags[0] if all_matching_tags else None

        print(f">>> [INFO] Tag glob:          '{tag_glob}'")
        first_tag = f"{tag_prefix}{initial_tag_version}"
        print(f">>> [INFO] Latest tag (base): "
              f"{latest_tag or f'(none — first release → will use {first_tag})'}")

        # Build --with-commit args (shell-safe quoting handles special chars)
        all_commits = sorted(commits)
        with_commit_args = " ".join(f"--with-commit {shlex.quote(c)}" for c in all_commits)
        # For bump calculation only, pass only the first line (subject) of each commit.
        # git-cliff with conventional_commits=false applies [bump] rules
        # (custom_minor_increment_regex, custom_major_increment_regex) against the commit
        # subject. When a commit has a body attached without a blank-line separator(
        # as usual conventional commit should be looked),
        # git-cliff fails to isolate the subject and falls back to a patch bump regardless
        # of the regex it matched.... Stripping to the first line fixes this — the subject alone
        # is sufficient to determine the bump level. The full multiline string is still
        # passed to the changelog command where the body content is needed.
        bump_commit_args = " ".join(
            f"--with-commit {shlex.quote(c.splitlines()[0])}" for c in all_commits
        )

        print(f">>> [INFO] Commits: {all_commits}")

        # ── STEP 2: CALCULATE VERSION ─────────────────────────────────────────
        if latest_tag:
            bump_cmd = " ".join(filter(None, [
                cliff_cmd_base,
                f"--tag-pattern '{component_tag_pattern}'",
                "--bump --bumped-version",
                bump_commit_args,
                "-- HEAD..HEAD",
            ]))
            print(f">>> [VERBOSE] For bump calculation only, pass only the first line (subject) of each commit.")
            print(f">>> [VERBOSE] bump_cmd: {bump_cmd}")

            bumped = run_command(bump_cmd)

            print(f">>> [VERBOSE] bump stdout: {bumped.stdout.strip()}")
            if bumped.stderr.strip():
                print(">>> [VERBOSE] bump stderr:")
                for line in bumped.stderr.strip().splitlines():
                    print(f"    {line}")

            new_tag = bumped.stdout.strip()
            if not new_tag:
                print(f">>> SKIP: no releasable commits for {display_name}")
                continue

            if new_tag == latest_tag:
                print(f">>> SKIP: bumped version equals latest tag ({latest_tag}) — no releasable commits for {display_name}")
                continue

            print(f">>> [INFO] Calculated new_tag: {new_tag}")
        else:
            new_tag = f"{tag_prefix}{initial_tag_version}"
            print(f">>> [INFO] No existing tag — first release: {new_tag}")

        # ── STEP 3: GENERATE CHANGELOG ────────────────────────────────────────
        changelog_path = os.path.join(full_path, "CHANGELOG.md")
        if os.path.exists(changelog_path):
            output_flag = f"--prepend {changelog_path}"
            print(f">>> [INFO] CHANGELOG exists — using --prepend")
        else:
            output_flag = f"--output {changelog_path}"
            print(f">>> [INFO] CHANGELOG not found — using --output")

        cliff_cmd = " ".join(filter(None, [
            cliff_cmd_base,
            f"--tag-pattern '{component_tag_pattern}'",
            f"--tag '{new_tag}'",
            with_commit_args,
            output_flag,
            "-- HEAD..HEAD",
        ]))

        print(f">>> [VERBOSE] cliff_cmd: {cliff_cmd}")

        res = run_command(cliff_cmd)

        print(f">>> [VERBOSE] cliff stdout: {res.stdout.strip()}")
        if res.stderr.strip():
            print(">>> [VERBOSE] cliff stderr:")
            for line in res.stderr.strip().splitlines():
                print(f"    {line}")

        if res.returncode != 0:
            print(f">>> ERROR generating changelog for {display_name}: {res.stderr.strip()}")
            continue

        # ── STEP 4: CREATE TAG AND RECORD ────────────────────────────────────
        tag_result = run_command(f"git tag -f {shlex.quote(new_tag)}")
        if tag_result.returncode != 0:
            print(f">>> ERROR creating tag '{new_tag}': {tag_result.stderr.strip()}")
            continue
        print(f">>> [INFO] Tag '{new_tag}' created locally")

        created_tags.append(new_tag)
        if output_tags_file:
            with open(output_tags_file, "a") as f:
                f.write(f"{new_tag}\n")
            print(f">>> [INFO] Tag '{new_tag}' written to '{output_tags_file}'")


    if created_tags:
        print("")
        print("\033[1;34m>>> New tags created:\033[0m")
        for tag in created_tags:
            print(f"\033[1;34m    {tag}\033[0m")
    else:
        print("\033[1;34m>>> No new tags created.\033[0m")


if __name__ == "__main__":
    release()



