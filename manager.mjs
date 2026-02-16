// manager.mjs
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

const prevSha = process.env.CI_PREV_COMMIT_SHA;
const currSha = process.env.CI_COMMIT_SHA || 'HEAD';
const diffRange = (!prevSha || prevSha.startsWith('000000')) ? `HEAD~1 ${currSha}` : `${prevSha} ${currSha}`;

try {
  const diffOutput = execSync(`git diff --name-only ${diffRange}`).toString();
  const changedPlugins = [...new Set(
    diffOutput.split('\n')
      .filter(file => file.startsWith('plugins/'))
      .map(file => file.split('/')[1])
  )];

  for (const plugin of changedPlugins) {
    const pluginDir = path.join('plugins', plugin);
    if (!fs.existsSync(pluginDir)) continue;

    console.log(`\n🚀 Releasing plugin: ${plugin}`);

    // Create dummy package.json if it doesn't exist
    const pkgPath = path.join(pluginDir, 'package.json');
    if (!fs.existsSync(pkgPath)) {
      fs.writeFileSync(pkgPath, JSON.stringify({ name: plugin, version: "0.0.0-dev", private: true }, null, 2));
    }

    // Run semantic-release using the root config
    execSync('npx semantic-release --extends ../../release.config.js', {
      cwd: pluginDir,
      env: { ...process.env, PLUGIN_NAME: plugin },
      stdio: 'inherit'
    });
  }
} catch (err) {
  process.exit(1);
}