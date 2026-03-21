# kaniko-monorepo-cliff

Woodpecker CI plugin that reads the tags produced by the **MasterVersions plugin** (semantic versioning via git-cliff), resolves each tag to a `Dockerfile` on disk, and builds + pushes the Docker image via Kaniko.

Designed to run as the final step of the release pipeline, right after the MasterVersions plugin creates the git tags.

---

## How it works

1. Reads a list of tags from the file written by the MasterVersions plugin (e.g. `new_tags.txt`)
2. For each tag, extracts the **slug** and **version**
3. Scans `PLUGIN_BASE` to find the `Dockerfile` whose parent directory matches the slug
4. Builds and pushes the image via `/kaniko/executor`

### Tag → path resolution

| Tag | PLUGIN_BASE | Resolved path | Dockerfile |
|-----|-------------|---------------|------------|
| `harel-v1.3.4` | `check/plugins` | `harel` | `check/plugins/harel/Dockerfile` |
| `netanel-1.0.0` | `check/plugins` | `netanel` | `check/plugins/netanel/Dockerfile` |
| `check-plugins-harel-v1.3.4` | `.` | `check/plugins/harel` | `check/plugins/harel/Dockerfile` |
| `v1.5.6` | `check/plugins/harel` | `.` (root) | `check/plugins/harel/Dockerfile` |

### Supported tag formats

All of the following are understood — no fixed format is assumed:

```
harel-v1.3.4          slug=harel           version=v1.3.4
plugins-netanel-1.0.0 slug=plugins-netanel  version=1.0.0
netanel-1.8           slug=netanel          version=1.8
1.5.6                 slug=(empty)          version=1.5.6  → Dockerfile at PLUGIN_BASE root
```

---

## Variables

### Required

| Variable | Description |
|----------|-------------|
| `PLUGIN_BASE` | Directory to scan for Dockerfiles. Set to wherever your component folders live. |
| `PLUGIN_USERNAME` | Registry username |
| `PLUGIN_PASSWORD` | Registry password |
| `PLUGIN_TAGS_FILE` **or** `PLUGIN_TAGS` | Tags to process. File path (newline-separated) or inline comma/newline-separated string. |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGIN_REGISTRY` | `index.docker.io` | Docker registry |
| `PLUGIN_REPO` | `""` | Image repository/namespace prefix |
| `PLUGIN_DOCKERFILE` | `Dockerfile` | Dockerfile filename to look for |
| `PLUGIN_ALIASES` | *(not set)* | Comma-separated alias tags pushed alongside the version tag. Not set by default — only the exact version tag is pushed. |
| `PLUGIN_DRY_RUN` | `false` | Set to `"true"` to skip the actual push (`--no-push`) |
| `PLUGIN_LOG_LEVEL` | `info` | Kaniko log verbosity |
| `PLUGIN_SKIP_TLS_VERIFY` | `false` | Set to `"true"` to add `--skip-tls-verify` |
| `PLUGIN_INSECURE` | `false` | Set to `"true"` to add `--insecure` |

### PLUGIN_ALIASES examples

```yaml
# Push version tag only (default — no aliases)
# → registry/repo/harel:v1.3.4

# Push version + latest
PLUGIN_ALIASES: "latest"
# → registry/repo/harel:v1.3.4
# → registry/repo/harel:latest

# Push version + prod + staging
PLUGIN_ALIASES: "prod,staging"
# → registry/repo/harel:v1.3.4
# → registry/repo/harel:prod
# → registry/repo/harel:staging
```

---

## Pipeline integration

The MasterVersions plugin must write its created tags to a file using `OUTPUT_TAGS_FILE`.
This file is then passed to `kaniko-monorepo-cliff` via `PLUGIN_TAGS_FILE`.

### Full `.woodpecker/Build.yaml` example

```yaml
clone:
  git:
    image: woodpeckerci/plugin-git
    settings:
      depth: 0
      tags: true

when:
  - event: push
    branch: main

steps:
  - name: Fetch PR body
    image: alpine/curl:latest
    environment:
      GITEA_TOKEN: ...
      GITEA_URL: ...
    commands:
      - |
        PR_BODY=$(curl -sf \
          -H "Authorization: token $GITEA_TOKEN" \
          "$GITEA_URL/api/v1/repos/$CI_REPO/pulls?state=closed&limit=50" \
          | grep -o '"body":"[^"]*"' | head -1 \
          | sed 's/"body":"//;s/"$//')
        echo "$PR_BODY" > pr_body.txt

  - name: Run MasterVersions
    image: netanelzucaim123/python-git-cliff:latest
    environment:
      PLUGIN_BASE: "."
      OUTPUT_TAGS_FILE: "new_tags.txt"
      GITEA_TOKEN: ...
      GITEA_URL: ...
    commands:
      - export PR_BODY="$(cat pr_body.txt)"
      - python3 release.py

  - name: Push changelogs to Git
    image: alpine/git
    commands:
      - git config --global user.email "ci-bot@example.com"
      - git config --global user.name "CI Bot"
      - git config --global safe.directory '*'
      - git remote set-url origin "http://ci-bot:TOKEN@gitea/REPO.git"
      - git add -- '*/CHANGELOG.md'
      - |
        if ! git diff --cached --quiet; then
          git commit -m "chore(release): update CHANGELOG.md files [skip ci]"
          git push --force origin HEAD:main
        else
          echo "No changelog changes to commit."
        fi
      - git push --force --tags origin

  - name: Build and push plugin images
    image: netanelzucaim123/kaniko-monorepo-cliff:latest
    environment:
      PLUGIN_BASE: "."           # adjust to your component root, e.g. "check/plugins"
      PLUGIN_REGISTRY: "index.docker.io"
      PLUGIN_REPO: "netanelzucaim123"
      PLUGIN_TAGS_FILE: "new_tags.txt"
      PLUGIN_ALIASES: "latest"   # optional — omit to push version tag only
      PLUGIN_USERNAME:
        from_secret: docker_username
      PLUGIN_PASSWORD:
        from_secret: docker_password
```

---

## Building the plugin image

```bash
docker build -t netanelzucaim123/kaniko-monorepo-cliff:latest .
docker push netanelzucaim123/kaniko-monorepo-cliff:latest
```
