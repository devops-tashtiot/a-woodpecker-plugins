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
After each step, report the output to the user. If any step fails, stop and explain the error.
