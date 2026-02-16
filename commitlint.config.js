const fs = require('fs');
const path = require('path');

// Dynamically read plugin directory names
const pluginsDir = path.join(__dirname, 'plugins');

if (!fs.existsSync(pluginsDir)) {
  console.warn('Warning: plugins directory not found. No scopes will be valid.');
}

const validScopes = fs.existsSync(pluginsDir)
  ? fs.readdirSync(pluginsDir).filter(item => {
      return fs.statSync(path.join(pluginsDir, item)).isDirectory();
    })
  : [];

module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // Scope must match a plugin folder name from plugins/ directory
    'scope-enum': [2, 'always', validScopes],
    'scope-empty': [0, 'never'], // Allow empty scope (0 = disabled)
  },
  ignores: [
    // Ignore the initial planning commit that was created before validation was added
    (commit) => commit.trim() === 'Initial plan',
  ],
};
