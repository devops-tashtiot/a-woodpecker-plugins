# Woodpecker CI/CD Plugins Repository

## 🎯 Purpose

This repository serves as a **collaborative hub** for all DevOps engineers in our organization to develop, share, and maintain [Woodpecker CI/CD](https://woodpecker-ci.org/) plugins. 

### What is This Repository For?

This is a centralized location where our team can:

- **Write Woodpecker Plugins**: Develop custom plugins that extend Woodpecker CI/CD functionality to meet our organization's specific needs
- **Collaborate & Innovate**: Share ideas, implementations, and best practices for plugin development
- **Peer Review**: Review and approve each other's plugins to ensure quality, security, and reliability
- **Unified Management**: Maintain all our custom Woodpecker plugins in one place with automated versioning and releases

### What are Woodpecker Plugins?

[Woodpecker](https://woodpecker-ci.org/) is a lightweight, cloud-native CI/CD server. Plugins are Docker containers that perform specific tasks in your CI/CD pipelines (e.g., deploying applications, sending notifications, running tests, managing infrastructure). This repository enables our DevOps team to create custom plugins tailored to our unique workflows and infrastructure.

## 🤝 Collaboration is Key

This repository thrives on teamwork:

- **Contribute Your Ideas**: Every DevOps engineer can propose and implement new plugins
- **Code Review Process**: All plugin changes go through peer review before being released
- **Shared Ownership**: We collectively maintain and improve our plugin ecosystem
- **Knowledge Sharing**: Learn from each other's implementations and approaches

## 🛠️ Technical Overview

This project is a **monorepo** that uses [Semantic Release](https://semantic-release.gitbook.io/) to automate versioning and Docker image publishing for multiple Woodpecker plugins. Each plugin is independently versioned and released based on conventional commit messages.

## 📁 Project Structure

```
semantic/
├── plugins/              # Plugin directories (each is an independent module)
│   ├── harel/           # Plugin: harel
│   ├── lagziel/         # Plugin: lagziel
│   └── netanel/         # Plugin: netanel
├── .github/
│   └── workflows/
│       ├── release.yml  # Automated release workflow
│       └── lint.yml     # Commit message validation for PRs
├── commitlint.config.js # Commit message validation rules
├── release.config.js    # Semantic-release configuration
├── manager.mjs          # Release manager for monorepo
└── package.json         # Project dependencies
```

## 🚀 How It Works

### Automatic Woodpecker Plugin Publishing

When you push commits to the `main` branch that modify files in the `plugins/` directory (after peer review and approval), the system automatically builds and publishes your Woodpecker plugin:

1. **Commit Validation**: The system validates that your commit message follows the [Conventional Commits](https://www.conventionalcommits.org/) format
2. **Change Detection**: The `manager.mjs` script detects which Woodpecker plugin(s) were modified
3. **Version Bump**: Semantic-release automatically determines the next version based on the commit type
4. **Docker Build & Push**: A Docker image for your Woodpecker plugin is built and pushed to Docker Hub with the new version tag
5. **Git Tag**: A git tag is created (e.g., `harel-v1.2.3`)
6. **Changelog**: The `CHANGELOG.md` file in the plugin directory is updated
7. **Ready to Use**: Your Woodpecker plugin is now available for use in CI/CD pipelines across the organization

## 📝 Commit Message Format

All commits **must** follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Requirements

- **Type**: Must be one of: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`
- **Scope**: **Required** and must match a plugin directory name in `plugins/`
- **Description**: A short summary of the change

### Valid Commit Types

| Type | Description | Version Bump |
|------|-------------|--------------|
| `feat` | A new feature | Minor (1.x.0) |
| `fix` | A bug fix | Patch (1.0.x) |
| `docs` | Documentation changes | Patch (1.0.x) |
| `style` | Code style changes | Patch (1.0.x) |
| `refactor` | Code refactoring | Patch (1.0.x) |
| `perf` | Performance improvements | Patch (1.0.x) |
| `test` | Adding or updating tests | Patch (1.0.x) |
| `chore` | Maintenance tasks | Patch (1.0.x) |

### Available Scopes (Woodpecker Plugin Names)

The scope must match one of the existing Woodpecker plugin directories:
- `harel`
- `lagziel`
- `netanel`

**Note**: When you create a new Woodpecker plugin, its directory name becomes a valid scope automatically.

## ✅ Valid Commit Examples

### Feature Addition (Minor Version Bump)
```bash
git commit -m "feat(harel): add new authentication feature"
```
This triggers:
- Version bump from `1.2.3` → `1.3.0`
- Woodpecker plugin Docker image: `username/harel:1.3.0`

### Bug Fix (Patch Version Bump)
```bash
git commit -m "fix(netanel): resolve connection timeout issue"
```
This triggers:
- Version bump from `1.2.3` → `1.2.4`
- Woodpecker plugin Docker image: `username/netanel:1.2.4`

### Documentation Update (Patch Version Bump)
```bash
git commit -m "docs(lagziel): update plugin usage documentation"
```
This triggers:
- Version bump from `1.0.0` → `1.0.1`
- Woodpecker plugin Docker image: `username/lagziel:1.0.1`

### Refactoring (Patch Version Bump)
```bash
git commit -m "refactor(harel): improve error handling logic"
```

## ❌ Invalid Commit Examples

```bash
# ❌ Missing scope
git commit -m "feat: add new feature"

# ❌ Invalid scope (doesn't match plugin directory)
git commit -m "feat(invalid-plugin): add feature"

# ❌ Invalid type
git commit -m "update(harel): update code"

# ❌ Not following conventional format
git commit -m "Updated some files in harel"
```

## 🔄 Release Workflow

The release process is fully automated via GitHub Actions:

### 1. Push to Main Branch
```bash
git add plugins/harel/Dockerfile
git commit -m "feat(harel): update base image to alpine"
git push origin main
```

### 2. Automated Steps (GitHub Actions)

**Validation Job** (`validate-commits`):
- Fetches commit history
- Validates all commit messages
- Ensures scopes match plugin directories
- Fails if any commit is invalid

**Release Job** (`release`):
- Runs only if validation passes
- Installs dependencies
- Logs into Docker Hub
- Executes `manager.mjs` which:
  - Detects changed plugins via `git diff`
  - For each changed plugin:
    - Runs semantic-release
    - Bumps version in `package.json`
    - Builds Docker image with new version tag
    - Pushes image to Docker Hub
    - Updates `CHANGELOG.md`
    - Creates git tag (e.g., `harel-v1.3.0`)
    - Commits changes back to repository

### 3. Result
- New Docker image available: `dockerhub-username/harel:1.3.0`
- Git tag created: `harel-v1.3.0`
- Updated `CHANGELOG.md` in plugin directory
- Updated `package.json` with new version

## 🏷️ Versioning Strategy

This project follows [Semantic Versioning](https://semver.org/) (SemVer):

```
MAJOR.MINOR.PATCH
  │     │     │
  │     │     └─ Bug fixes, docs, refactors (fix, docs, refactor, etc.)
  │     └─────── New features (feat)
  └───────────── Breaking changes (BREAKING CHANGE in commit body)
```

### Breaking Changes

To trigger a **major** version bump, include `BREAKING CHANGE:` in the commit body:

```bash
git commit -m "feat(harel): redesign API

BREAKING CHANGE: The authentication endpoint has been completely redesigned.
Old clients will need to update their integration."
```

This bumps version from `1.2.3` → `2.0.0`

## 🛠️ Development Workflow

### Adding a New Woodpecker Plugin

When you have an idea for a new Woodpecker plugin that could benefit the team:

1. **Discuss Your Idea**: Share your plugin concept with the team (via issues, discussions, or team meetings)

2. Create a new directory under `plugins/`:
   ```bash
   mkdir plugins/mynewplugin
   ```

3. Add a `Dockerfile` for your Woodpecker plugin:
   ```dockerfile
   FROM alpine:latest
   # Add your plugin logic here
   # Woodpecker will execute this when the plugin runs in a pipeline
   ENTRYPOINT ["/app/plugin.sh"]
   ```

4. Commit with the new plugin scope:
   ```bash
   git add plugins/mynewplugin
   git commit -m "feat(mynewplugin): initial Woodpecker plugin setup"
   git push origin main
   ```

The system will automatically:
- Recognize `mynewplugin` as a valid scope
- Create initial version `1.0.0`
- Build and push Docker image
- Make it available for use in Woodpecker pipelines

### Collaborating via Pull Requests

**This is where the collaboration happens!** When working on plugin improvements:

1. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/improve-harel-plugin
   ```

2. **Make Your Changes**: Implement your plugin improvements or new features

3. **Commit with Proper Format**:
   ```bash
   git commit -m "feat(harel): add retry mechanism for failed requests"
   git push origin feature/improve-harel-plugin
   ```

4. **Open a Pull Request**: Create a PR and request reviews from fellow DevOps engineers

5. **Peer Review**: Team members review your code, suggest improvements, and approve changes

6. **Merge After Approval**: Once approved, merge to `main` and the plugin is automatically released

The PR validation workflow (`lint.yml`) ensures all commits follow our standards before merging.

## 📋 GitHub Actions Workflows

### `release.yml` (Main Branch Only)
Triggers on: Push to `main` branch with changes in `plugins/**`

Jobs:
1. **validate-commits**: Validates all commit messages
2. **release**: Builds and publishes Woodpecker plugin Docker images

### `lint.yml` (Pull Requests)
Triggers on: Pull request creation/update

Jobs:
1. **commitlint**: Validates all commits in the PR

## 🎮 Using Woodpecker Plugins in Your Pipelines

Once a plugin is published, any team member can use it in their Woodpecker CI/CD pipelines:

```yaml
# .woodpecker.yml example
steps:
  - name: run-custom-plugin
    image: dockerhub-username/harel:1.3.0  # Our custom Woodpecker plugin
    settings:
      # Plugin-specific settings here
      param1: value1
      param2: value2
```

Check each plugin's documentation in its directory for specific usage instructions and available settings.

## 🔐 Required Secrets

Configure these secrets in your GitHub repository settings:

| Secret | Description |
|--------|-------------|
| `DOCKER_REG_USERNAME` | Docker Hub username |
| `DOCKER_REG_PASSWORD` | Docker Hub password or access token |
| `GITHUB_TOKEN` | Automatically provided by GitHub Actions |

## 📚 Additional Resources

- [Conventional Commits Specification](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
- [Semantic Release Documentation](https://semantic-release.gitbook.io/)
- [Commitlint](https://commitlint.js.org/)

## 💡 Tips for Plugin Development

- **Always specify a scope**: The scope is mandatory and must match a plugin directory name
- **Use meaningful descriptions**: Write clear, concise commit messages that explain what your plugin does
- **One plugin per commit**: Keep changes focused on a single plugin for cleaner releases
- **Document your plugins**: Add README files in plugin directories to help team members understand usage
- **Test before pushing**: Ensure your Woodpecker plugin works in a test pipeline before committing
- **Ask for feedback**: Don't hesitate to request reviews from experienced team members
- **Share knowledge**: Add comments and documentation to help others learn from your implementation
- **Check your commits locally**: Run `npx commitlint --from HEAD~1` before pushing
- **Review the CHANGELOG**: Each plugin maintains its own changelog in its directory

## 🆘 Troubleshooting

### "Commit message validation failed"
- Check that your commit follows the format: `type(scope): description`
- Ensure the scope matches a plugin directory name exactly
- Verify the type is one of the valid types listed above

### "Docker build failed"
- Ensure the `Dockerfile` in your plugin directory is valid
- Check Docker Hub credentials are configured correctly
- Review the GitHub Actions logs for detailed error messages

### "No release triggered"
- Ensure changes are in the `plugins/` directory
- Verify commits are being pushed to the `main` branch
- Check that commit messages follow conventional format

---

## 🙋 Getting Help & Contributing

**Have Questions?** Open an issue in the repository or reach out to fellow DevOps engineers in the team.

**Want to Contribute?** We welcome all contributions! Whether it's a new plugin idea, an improvement to an existing plugin, or documentation updates - your input makes our shared plugin ecosystem better for everyone.

**Remember**: This repository is built on collaboration. Every plugin you create, every review you provide, and every idea you share helps the entire DevOps team work more efficiently with Woodpecker CI/CD.
