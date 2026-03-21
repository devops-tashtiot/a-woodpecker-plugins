Run the following steps in order inside the `semantic/` directory:

1. Remove all CHANGELOG.md files and all git tags:
   ```
   find . -name "CHANGELOG.md" -not -path "./.git/*" -delete
   git tag -l | xargs -r git tag -d
   ```

2. Stage all changes and commit with message "update":
   ```
   git add -A && git commit -m "update"
   ```

3. Ensure the git remote URL has credentials embedded:
   ```
   git remote set-url origin http://netanelzucaim:Zn12345Zn12345@localhost:3000/netanelzucaim/semantic.git
   ```

4. Pull latest changes from remote with rebase:
   ```
   git pull --rebase origin main
   ```

5. Push local commits to main:
   ```
   git push origin main
   ```

6. Clean all remote tags and CHANGELOG.md files from origin:
   - Delete all remote tags:
     ```
     git ls-remote --tags origin | awk '{print $2}' | grep -v '{}' | sed 's|refs/tags/||' | xargs -r -I{} git push origin :refs/tags/{}
     ```
   - Push the clean state (no CHANGELOG.md files, no tags):
     ```
     git push --force origin HEAD:main
     ```

7. Create all test PRs via the Gitea MCP tool (`mcp__gitea__pull_request_write`).
   For each PR: create a feature branch from main, add a dummy commit, then open a PR
   with the body containing BOTH the conventional commit line AND any env var overrides
   needed (SCOPE_DEPTH=, PLUGIN_BASE=, SCOPE_EXCLUDE_REGEX=).

   The full set of PRs to create covers every scenario from `test_release_docker.sh`
   and `test_release.py`:

   **Section 0 — Depth=0 (polyrepo, no scope):**
   - `feat: add polyrepo feature` + `SCOPE_DEPTH=0`
   - `fix: polyrepo bugfix` + `SCOPE_DEPTH=0`
   - `feat!: breaking polyrepo change` + `SCOPE_DEPTH=0`

   **Section 1 — Depth=1 (standard monorepo, single slug tags):**
   - `feat(nati): add dashboard` + `SCOPE_DEPTH=1`
   - `fix(nati): resolve login timeout` + `SCOPE_DEPTH=1`
   - `feat!(nati): breaking nati change` + `SCOPE_DEPTH=1`

   **Section 1b — Depth=1, multi-scope explosion:**
   - `feat(nati, harel): shared feature` + `SCOPE_DEPTH=1`

   **Section 2 — Depth=2 (nested monorepo):**
   - `fix(plugins/docker): resolve socket error` + `SCOPE_DEPTH=2`
   - `feat(base/argo): update core security` + `SCOPE_DEPTH=2`
   - `feat(base/argo, nati): bulk update` + `SCOPE_DEPTH=2`
   - `chore(base/infra/networking/firewall): update rules` + `SCOPE_DEPTH=2`

   **Wildcard — depth=1:**
   - `feat(*): upgrade all` + `SCOPE_DEPTH=1`

   **Wildcard — depth=2 group prefix:**
   - `feat(plugins/*): upgrade all plugins` + `SCOPE_DEPTH=2`

   **Exclude regex:**
   - `feat(*): upgrade all with exclude` + `SCOPE_DEPTH=1` + `SCOPE_EXCLUDE_REGEX=^docs$|^shared$`

   **Dedup — same scope multiple lines, highest priority wins:**
   - Multi-line body:
     ```
     fix(nati): small fix
     feat(nati): bigger feature
     ```
     + `SCOPE_DEPTH=1`

   **OUTPUT_TAGS_FILE — verify tags are written:**
   - `feat(harel): output tags test` + `SCOPE_DEPTH=1`

   **Skip types from cliff.toml (chore/docs/ci):**
   - `chore(nati): routine maintenance` + `SCOPE_DEPTH=1`
   - `docs(nati): update readme` + `SCOPE_DEPTH=1`
   - `ci(nati): update pipeline` + `SCOPE_DEPTH=1`

   **PLUGIN_BASE override:**
   - `feat(harel): plugin base test` + `SCOPE_DEPTH=1` + `PLUGIN_BASE=plugins`

After each step, report the output to the user. If any step fails, stop and explain the error.
