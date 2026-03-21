release.py
This Python script serves as the Orchestrator. It identifies which components need a release, explodes the scopes, and executes the git-cliff command for each.
cliff.toml
The global configuration file that defines the SemVer rules and the Changelog format.
The technical specification for the system. This allows an AI to understand how the logic flows and how paths are mapped.

🏗️ Technical Specification: Stateless Monorepo Tagger
1. The Input Schema (The "Explosion" Logic)
This section explains how to convert a human-readable PR body into a machine-readable workload.

Trigger Pattern: The AI looks for the Regex ^([a-z]+)\(([^)]+)\):\s*(.*).

Multi-Scope Handling: It specifies that comma-separated values inside the parentheses () must be treated as independent release targets.

Example: feat(base/argo, nati): msg translates to two distinct execution contexts:

Context 1: Path: base/argo, Type: feat, Msg: msg

Context 2: Path: nati, Type: feat, Msg: msg

2. Path & Tag Mapping (The "Slug" Logic)
LLMs need to know how "Human Paths" map to "Git Tags" to avoid naming collisions.

Normalization: Any forward slash / in a scope is converted to a hyphen -.

Hierarchical Examples:

base/argo → base-argo

plugins/auth/check → plugins-auth-check

Versioning: The tag suffix is always -v followed by the SemVer calculated by git-cliff.

3. The "Stateless" Constraint
The system is designed to be Stateless to ensure the PR body is the source of truth.

Source of Truth: The PR body line is the only commit message considered for the current bump.

History Lookup: git-cliff uses the tag pattern to find the last version, but it does not use the Git log for the current change—it uses the --body flag provided by the script.

Isolation: The --include-path acts as a "filter fence," ensuring that a release for nati never looks at tags or history belonging to base/argo.
Based on the refactored logic where we shifted from a standard Hash Map (Dictionary) to a Set of Conventional Commit strings, the output is designed to be a clean, de-duplicated list of instructions.If your PR Body looks like this:Plaintextfeat(base/argo, nati): update core security
fix(plugins/check): resolve login timeout
The output of the parse_pr_body function (the "Hash Map" equivalent) will look like this in Python:Python{
    "feat(base/argo): update core security",
    "feat(nati): update core security",
    "fix(plugins/check): resolve login timeout"
}
Why this format is better than a standard Map:Explosion: Notice how feat(base/argo, nati) was split into two separate strings. This allows the script to iterate through them as unique release events.Uniqueness: Because it's a set(), if you accidentally typed the same line twice in your PR, Python would automatically merge them into one, preventing you from accidentally creating the same Git tag twice.One-Shot Ready: Each string in this set is already a perfectly formatted Conventional Commit. The script simply hands this exact string to git-cliff via the --body flag.How it translates to Execution:When the loop runs, it extracts the path from the parentheses to determine where to work:String in SetExtracted PathActionfeat(base/argo): ...base/argoBumps base/argo to a new Minor version.feat(nati): ...natiBumps nati to a new Minor version.fix(plugins/check): ...plugins/checkBumps plugins/check to a new Patch version.
4. Woodpecker Integration & Workspace
Pipeline Location: .woodpecker/ contains the YAML definitions.

Plugin Source: plugins/ contains the actual Go/Python/Bash code for each plugin.

Isolation: The --include-path ensures that changing the code in plugins/docker only triggers a version bump for that specific plugin, even if other plugins exist in the same parent folder.

5. The "Stateless" Constraint
Source of Truth: The PR body line is the only context for the bump.

History Lookup: git-cliff finds the last tag matching the prefix to determine the base version but ignores global history for the current increment.


🧪 Testing & Validation Suite
Claude must validate the following test cases to ensure the release_set (Hashmap equivalent) and the resulting path_slug are correct.

Test Case 1: Standard Monorepo (Single Level)
Input: feat(nati): add dashboard

Expected Output:

Path: nati

Slug: nati

Command Argument: --include-path 'nati/**/*'

Generated Tag: nati-v1.1.0

Test Case 2: Mono-of-Monorepo (Nested Plugins)
Input: fix(plugins/docker): resolve socket error

Expected Output:

Path: plugins/docker

Slug: plugins-docker

Command Argument: --include-path 'plugins/docker/**/*'

Generated Tag: plugins-docker-v1.0.1

Test Case 3: Bulk Explosion (Mixed Levels)
Input: feat(base/argo, nati, plugins/git): global auth update

Expected Output (3 Operations):

Path: base/argo | Slug: base-argo | Tag: base-argo-v...

Path: nati | Slug: nati | Tag: nati-v...

Path: plugins/git | Slug: plugins-git | Tag: plugins-git-v...

Test Case 4: Deeply Nested Hierarchy
Input: chore(base/infra/networking/firewall): update rules

Expected Output:

Path: base/infra/networking/firewall

Slug: base-infra-networking-firewall

Command Argument: --include-path 'base/infra/networking/firewall/**/*'