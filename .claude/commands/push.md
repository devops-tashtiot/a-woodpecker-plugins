Run the following steps in order inside the `semantic/` directory:

1. Ensure the git remote URL has credentials embedded:
   ```
   git remote set-url origin http://netanelzucaim:Zn12345Zn12345@localhost:3000/netanelzucaim/semantic.git
   ```

2. Pull latest changes from remote with rebase (stash any uncommitted changes first):
   ```
   git stash; git pull --rebase origin main; git stash pop 2>/dev/null || true
   ```

3. Remove all CHANGELOG.md files and all git tags:
   ```
   find . -name "CHANGELOG.md" -not -path "./.git/*" -delete
   git tag -l | xargs -r git tag -d
   ```

4. Stage all changes and commit with message "update":
   ```
   git add -A && git commit -m "update" || echo "nothing to commit"
   ```

5. Push local commits to main:
   ```
   git push origin main
   ```

6. Force delete all remote tags:
   ```
   git ls-remote --tags origin | awk '{print $2}' | grep -v '{}' | sed 's|refs/tags/||' | xargs -r -I{} git push origin :refs/tags/{}
   ```

After each step, report the output to the user. If any step fails, stop and explain the error.
