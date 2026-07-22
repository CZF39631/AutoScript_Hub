import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // Data-loading effects in this app intentionally update loading state before
      // subscribing/fetching. The connection loop itself is covered by a timer test.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
  {
    files: ['src/contexts/*.jsx'],
    rules: {
      // Context modules intentionally export both providers and their consumer hooks.
      'react-refresh/only-export-components': 'off',
    },
  },
])
