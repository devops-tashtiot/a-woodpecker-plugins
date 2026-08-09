import json
import subprocess
import re
import os
import shlex
import sys
import tomllib
from urllib.request import urlopen, Request


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


def _normalize_changelog_levels(changelog_level):
    """
    Normalize the changelog-level spec into a set of allowed integer depths, or None.

    Accepts:
      None                   -> None (no depth enforcement)
      an int (e.g. 2)        -> {2}
      a str "2"              -> {2}
      a comma-separated str  -> {2, 3, 4}   (e.g. "2,3,4" or "2, 3, 4")
      an iterable of ints    -> set(...)

    Raises ValueError if any value is not a non-negative integer, or if a
    string/iterable spec yields no usable numbers.
    """
    if changelog_level is None:
        return None
    if isinstance(changelog_level, bool):
        # bool is a subclass of int — reject it so True/False can't sneak in as 1/0.
        raise ValueError("changelog level must be an integer, not a bool")
    if isinstance(changelog_level, int):
        values = [changelog_level]
    elif isinstance(changelog_level, str):
        values = [int(p.strip()) for p in changelog_level.split(",") if p.strip() != ""]
        if not values:
            raise ValueError("no changelog levels parsed from string")
    else:
        values = [int(x) for x in changelog_level]
        if not values:
            raise ValueError("no changelog levels provided")
    levels = set(values)
    if any(l < 0 for l in levels):
        raise ValueError("changelog levels must be non-negative")
    return levels


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

    changelog_level (int | str | Iterable[int] | None):
      Enforces the expected depth of every location in the PR body. May allow a
      single depth or several at once — pass an int (2), a string ("2"), a
      comma-separated string ("2,3,4"), or any iterable of ints. It is normalized
      to a set of allowed depths via _normalize_changelog_levels().
      Depth is the number of path segments:
        depth 0  -> root (empty bracket [])
        depth 1  -> "nati"           (0 slashes)
        depth 2  -> "plugins/docker" (1 slash)
        depth 3  -> "base/infra/x"   (2 slashes)
      A location is accepted iff its depth is one of the allowed depths.
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

    levels = _normalize_changelog_levels(changelog_level)

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
        """True if location's depth is one of the allowed changelog levels.

        Depth = number of path segments: root ("") is depth 0, "nati" is depth 1,
        "plugins/docker" is depth 2, etc. `levels` is a set of allowed depths, or
        None to disable the check."""
        if levels is None:
            return True
        if location == "":
            return 0 in levels
        # Reject empty segments: leading /, trailing /, or consecutive //
        if "" in location.split("/"):
            return False
        return (location.count("/") + 1) in levels

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
                    allowed = ",".join(str(l) for l in sorted(levels))
                    if loc == "":
                        return (f"'' — empty location (depth 0), not in allowed "
                                f"PLUGIN_CHANGELOG_LEVEL depth(s) [{allowed}]")
                    segments = loc.split("/")
                    if "" in segments:
                        if loc.startswith("/"):
                            return f"'{loc}' — leading slash, missing component name before first '/'"
                        if loc.endswith("/"):
                            return f"'{loc}' — trailing slash, missing component name after last '/'"
                        return f"'{loc}' — consecutive '//', missing component name between slashes"
                    actual_depth = loc.count("/") + 1
                    return (
                        f"'{loc}' — wrong depth: {actual_depth} path segment(s), "
                        f"but PLUGIN_CHANGELOG_LEVEL allows depth(s) [{allowed}]"
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


def _bump_subject(commit):
    """
    Subject line used for bump-level detection. If the subject has no
    description after the type/colon (e.g. 'feat:' with the real text on
    the next line), the first non-blank continuation line is folded in
    instead — otherwise git-cliff sees a bare 'feat:' and silently falls
    back to a patch bump. A subject that already has real text after the
    colon (e.g. 'feat: real subject') is left as-is, unchanged.
    """
    lines = commit.splitlines()
    subject = lines[0]
    if re.search(r':\s*$', subject):
        for line in lines[1:]:
            if line.strip():
                return f"{subject} {line.strip()}"
    return subject


def _has_releasable_commits(commits, parsers):
    """Returns True if at least one commit's subject matches a non-skip parser."""
    for commit in commits:
        subject = commit.splitlines()[0]
        for p in parsers:
            msg = p.get("message", "")
            if not msg:
                continue
            if re.match(msg, subject):
                if not p.get("skip", False):
                    return True
                break  # first-match-wins; this commit is skip=true
    return False


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


def _retrieve_pull_request_message():
    """pull_request event -> fetch the PR description from the Bitbucket Server API."""
    try:
        token      = os.environ["PLUGIN_BITBUCKET_TOKEN"]
        server_url = os.environ["CI_FORGE_URL"]
        repo_owner = os.environ["CI_REPO_OWNER"]
        repo_name  = os.environ["CI_REPO_NAME"]
        pr_number  = os.environ["CI_COMMIT_PULL_REQUEST"]
    except KeyError as e:
        print(f">>> ERROR: missing {e} — required to fetch the PR description from Bitbucket.")
        return None
    api_url = f"{server_url}/rest/api/1.0/projects/{repo_owner}/repos/{repo_name}/pull-requests/{pr_number}"
    print(f">>> [INFO] Fetching PR #{pr_number} from {api_url}")
    try:
        req = Request(api_url, headers={"Authorization": f"Bearer {token}"})
        pr = json.loads(urlopen(req).read())
    except Exception as e:
        print(f">>> ERROR: could not fetch PR #{pr_number} from Bitbucket: {e}")
        return None
    print(f">>> [INFO] PR #{pr.get('id')} — title: {pr.get('title', '')}")
    return pr.get("description", "")


def _retrieve_manual_message():
    """manual event -> use the PLUGIN_MESSAGE env var as-is.

    Echoes the exact message back to the user, loudly and in full, so that on a
    manual run there is never any doubt about what was actually submitted — the
    #1 cause of a "no release commits detected" run is a mistyped or wrong
    PLUGIN_MESSAGE (e.g. pasting an image reference instead of a `feat[loc]:`
    line), which is invisible unless the message is printed back.
    """
    message = os.getenv("PLUGIN_MESSAGE", "")
    if not message:
        print(">>> ERROR: PLUGIN_MESSAGE is empty — required for a manual run.")
        return None

    lines = message.splitlines()
    print("")
    print("\033[1;33m==================================================================\033[0m")
    print("\033[1;33m>>> PLUGIN_MESSAGE — this is the EXACT message YOU entered for this\033[0m")
    print("\033[1;33m>>> manual run. Every release below is parsed from these lines.\033[0m")
    print("\033[1;33m==================================================================\033[0m")
    print("\033[33m>>> [INFO] Source: PLUGIN_MESSAGE env var (used as-is, not stripped)\033[0m")
    print("\033[36m>>> ----------------------- BEGIN PLUGIN_MESSAGE -----------------------\033[0m")
    for n, line in enumerate(lines, 1):
        # Number every line and mark whitespace so leading spaces / tabs (which
        # silently stop a line from matching a commit pattern) are visible.
        marked = line.replace("\t", "\\t")
        print(f"\033[36m>>> {n:>3} | {marked}\033[0m")
    print("\033[36m>>> ------------------------ END PLUGIN_MESSAGE ------------------------\033[0m")
    print("\033[1;33m>>> If nothing releases below, re-check the message above: a leading\033[0m")
    print("\033[1;33m>>> space, a wrong type, or a missing [location] makes a line IGNORED.\033[0m")
    print("\033[1;33m==================================================================\033[0m")
    print("")
    return message


def _retrieve_push_message():
    """
    Any other event -> assume a push carrying a PR merge commit, and extract
    the DESCRIPTION section from `git log -1 --pretty=%B` (see
    INCIDENT_PULL_REQUEST_CLOSED_TRAP.md for why a push event, not
    pull_request_closed, is used to detect a merge).
    """
    result = run_command("git log -1 --pretty=%B")
    message = result.stdout
    marker = "DESCRIPTION"
    if marker in message:
        return message.split(marker, 1)[1].strip()
    print(f">>> WARNING: no '{marker}' section found in commit message — using the full message as-is")
    return message.strip()


def _retrieve_message():
    """
    Determines the release message. Dispatches on CI_PIPELINE_EVENT. Returns
    the message string, or None if it could not be determined (an error has
    already been printed).
    """
    event = os.getenv("CI_PIPELINE_EVENT", "manual")
    print(f">>> [INFO] Retrieving message directly (CI_PIPELINE_EVENT={event})")

    match event:
        case "pull_request":
            return _retrieve_pull_request_message()
        case "manual":
            return _retrieve_manual_message()
        case _:
            return _retrieve_push_message()


def release():
    # ── Validate required env vars ────────────────────────────────────────────
    missing = []
    if not os.getenv("PLUGIN_CHANGELOG_LEVEL"):
        missing.append(
            "  PLUGIN_CHANGELOG_LEVEL — integer depth of component locations in your PR body.\n"
            "    Level 0 -> root only: feat[][...]   Level 1 -> top-level: feat[nati][...]\n"
            "    Level 2 -> nested:    feat[plugins/docker][...]   Example: PLUGIN_CHANGELOG_LEVEL=1\n"
            "    May be a comma-separated list to allow several depths at once, e.g. PLUGIN_CHANGELOG_LEVEL=2,3,4"
        )
    if not os.getenv("PLUGIN_BASE_PATH"):
        missing.append(
            "  PLUGIN_BASE_PATH — root directory; all [location] paths are resolved relative to this.\n"
            "    Example: PLUGIN_BASE_PATH=."
        )
    if missing:
        print(">>> ERROR: Missing required environment variables:\n")
        for m in missing:
            print(m)
        sys.exit(1)

    # ── Load env vars ─────────────────────────────────────────────────────────
    try:
        changelog_levels = _normalize_changelog_levels(os.getenv("PLUGIN_CHANGELOG_LEVEL"))
    except (TypeError, ValueError):
        print(">>> ERROR: PLUGIN_CHANGELOG_LEVEL must be a non-negative integer, or a "
              "comma-separated list of them (e.g. 1 or 2,3,4).")
        return

    pr_body = _retrieve_message()
    if pr_body is None:
        sys.exit(1)
    # Write the retrieved message out to pr_body.txt so later steps in the
    # same pipeline workspace (which grep it for override values like
    # PLUGIN_BASE_PATH) keep working without needing a separate fetch step.
    with open("pr_body.txt", "w") as _f:
        _f.write(pr_body)
    root_path           = os.getenv("PLUGIN_BASE_PATH")
    output_tags_file      = os.getenv("PLUGIN_OUTPUT_TAGS_FILE", "")
    output_locations_file = os.getenv("PLUGIN_OUTPUT_LOCATIONS_FILE", "")
    if output_tags_file:
        open(output_tags_file, "w").close()
    if output_locations_file:
        open(output_locations_file, "w").close()
    exclude_regex       = os.getenv("PLUGIN_SCOPE_EXCLUDE_REGEX", "")
    try:
        verbose = int(os.getenv("PLUGIN_VERBOSE", "0"))
    except ValueError:
        verbose = 0
    initial_tag_version = os.getenv("PLUGIN_INITIAL_TAG", "1.0.0").lstrip("v")
    version_prefix      = "v" if os.getenv("PLUGIN_V_PREFIX", "true").lower() == "true" else ""

    _bundled_toml = os.path.join(os.path.dirname(__file__), "cliff.toml")
    global_toml   = os.getenv("PLUGIN_CLIFF_TOML") or ("./cliff.toml" if os.path.exists("./cliff.toml") else _bundled_toml)
    _cliff_verbose = " -vv" if verbose >= 2 else (" -v" if verbose == 1 else "")
    cliff_cmd_base = f"git cliff --config {global_toml}{_cliff_verbose}"

    if not os.path.exists(global_toml):
        print(f">>> ERROR: cliff.toml not found at {global_toml}")
        return

    parsers, bump_cfg = load_cliff_parsers(global_toml)

    _print_cliff_rules(parsers, bump_cfg, global_toml)

    print(f">>> PLUGIN_CHANGELOG_LEVEL={','.join(str(l) for l in sorted(changelog_levels))}")
    print(f">>> PLUGIN_BASE_PATH='{root_path}' — root directory; all [location] paths are resolved relative to this")

    # ── Parse PR body ─────────────────────────────────────────────────────────
    location_to_commits = parse_pr_body(pr_body, parsers, changelog_level=changelog_levels)

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

    if output_locations_file:
        with open(output_locations_file, "w") as f:
            for loc in sorted(location_to_commits):
                f.write(f"{loc}\n")
        print(f">>> [INFO] Locations written to '{output_locations_file}': {sorted(location_to_commits)}")

    if had_wildcards:
        print("\033[1;4;33m>>> COMMITS AFTER WILDCARD EXPANSION:\033[0m")
        print("\033[33m    Wildcards replaced with concrete component paths.\033[0m")
        for loc in sorted(location_to_commits):
            display_loc = loc if loc else ""
            print(f"    [{display_loc}]")
            for commit in sorted(location_to_commits[loc]):
                print("      " + commit.replace("\n", "\n      "))

    # ── Resolve branch for ancestry-correct tag lookup ────────────────────────
    # See HOTFIX_TAG_RESOLUTION.md for the full design rationale. In short: a
    # plain `git fetch` (NO --tags/--no-tags) lets git's tag auto-follow attach
    # only tags whose commit is reachable from the fetched branch — which keeps
    # tag lookups branch-scoped (a mainline nati-v2.0.0 never lands on a hotfix
    # cut from nati-v1.0.0) WITHOUT any custom filtering. Explicitly fetching
    # --tags was tried and rejected: it materializes those unrelated tags and
    # git-cliff's --bump then picks the globally-highest one, breaking hotfix
    # resolution.
    #
    # The clone step's `tags: false` can persist as remote.origin.tagOpt=--no-tags
    # and block auto-follow, so reset it defensively first.
    run_command("git config --unset-all remote.origin.tagOpt")

    is_pr = os.getenv("CI_PIPELINE_EVENT") == "pull_request"
    resolve_branch = os.getenv("CI_COMMIT_TARGET_BRANCH") if is_pr else os.getenv("CI_COMMIT_BRANCH")

    # Fetch the branch into an explicit refs/remotes/origin/<branch> destination
    # (auto-follow only fires during a real fetch negotiation, which an explicit
    # destination refspec forces even for the already-checked-out branch).
    #
    # This step's git has no Bitbucket credentials of its own (the clone step's
    # plugin-git image holds them, not this image), so a plain `git fetch`
    # against Bitbucket returns 401 -> "could not read Username". Authenticate
    # with the same PLUGIN_BITBUCKET_TOKEN used for the PR-body fetch, sent as an
    # `Authorization: Bearer` header via `-c http.extraHeader` — the only scheme
    # Bitbucket DC HTTP tokens accept, and the same pattern the mirror-to-github
    # pipeline uses. The header only affects http(s) transports, so it's inert
    # for a local-path remote or the later local `git describe`/git-cliff calls.
    token = os.getenv("PLUGIN_BITBUCKET_TOKEN", "")
    auth_opt = f'-c http.extraHeader="Authorization: Bearer {token}" ' if token else ""

    resolved_ref = "HEAD"
    if resolve_branch:
        fetch_result = run_command(f"git {auth_opt}fetch origin {resolve_branch}:refs/remotes/origin/{resolve_branch}")
        if fetch_result.returncode == 0:
            resolved_ref = f"refs/remotes/origin/{resolve_branch}"
            print(f">>> [INFO] Resolving tags against {'target' if is_pr else 'current'} branch '{resolve_branch}'")
        else:
            print(f">>> WARNING: could not fetch branch '{resolve_branch}' ({fetch_result.stderr.strip()}) — falling back to HEAD")

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
        existing_tags_result = run_command(f"git describe --tags --abbrev=0 --match '{tag_glob}' {resolved_ref}")
        latest_tag = existing_tags_result.stdout.strip() or None

        print(f">>> [INFO] Tag glob:          '{tag_glob}'")
        first_tag = f"{tag_prefix}{initial_tag_version}"
        print(f">>> [INFO] Latest tag (base): "
              f"{latest_tag or f'(none — first release → will use {first_tag})'}")

        # Build --with-commit args (shell-safe quoting handles special chars)
        all_commits = sorted(commits)
        with_commit_args = " ".join(f"--with-commit {shlex.quote(c)}" for c in all_commits)
        # For bump calculation only, pass only the subject of each commit (see
        # _bump_subject). git-cliff with conventional_commits=false applies
        # [bump] rules (custom_minor_increment_regex, custom_major_increment_regex)
        # against the commit subject. When a commit has a body attached without
        # a blank-line separator (as usual conventional commit should be looked),
        # git-cliff fails to isolate the subject and falls back to a patch bump
        # regardless of the regex it matched.... Reducing to just the subject
        # fixes this — it alone is sufficient to determine the bump level. The
        # full multiline string is still passed to the changelog command where
        # the body content is needed.
        bump_commit_args = " ".join(
            f"--with-commit {shlex.quote(_bump_subject(c))}" for c in all_commits
        )

        print(f">>> [INFO] Commits: {all_commits}")

        # ── STEP 2: CALCULATE VERSION ─────────────────────────────────────────
        if latest_tag:
            # --tag-pattern stays the FULL unrestricted component glob (never
            # narrowed) — git-cliff validates the computed next version against
            # it too, so a narrowed pattern would reject a breaking bump crossing
            # e.g. 1.0.0 -> 2.0.0 (see HOTFIX_TAG_RESOLUTION.md §2). Branch
            # scoping is handled by which tags physically exist after the
            # auto-follow fetch, not by this regex.
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
            if not _has_releasable_commits(all_commits, parsers):
                # Unlike git-cliff (which emits a fallback 0.1.0 tag with a "No releases found"
                # warning), we intentionally skip — skip=true means not meant to trigger a release.
                print(f">>> SKIP: no releasable commits for {display_name} (all commits are skip=true).")
                continue
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

        created_tags.append(new_tag)

    if created_tags:
        # ── STEP 4: RECORD TAGS ───────────────────────────────────────────────
        for tag in created_tags:
            if output_tags_file:
                with open(output_tags_file, "a") as f:
                    f.write(f"{tag}\n")
                print(f">>> [INFO] Tag '{tag}' written to '{output_tags_file}'")
        print("")
        print("\033[1;34m>>> Tags to be created by pipeline:\033[0m")
        for tag in created_tags:
            print(f"\033[1;34m    {tag}\033[0m")
    else:
        print("\033[1;34m>>> No new tags created.\033[0m")


if __name__ == "__main__":
    release()





