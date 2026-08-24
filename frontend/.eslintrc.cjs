/* ESLint 8 flat-config predecessor; matches the React 18 + Vite setup. */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  settings: { react: { version: 'detect' } },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
  ],
  rules: {
    // The API returns snake_case; forcing camelCase at the boundary would
    // obscure which fields are ours and which are the server's.
    camelcase: 'off',
    // Prop-types are redundant here — the payload shapes are documented in the
    // API layer and validated server-side by pydantic.
    'react/prop-types': 'off',
    'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
  },
  ignorePatterns: ['dist', 'node_modules'],
};
