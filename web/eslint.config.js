import js from '@eslint/js';
import importX from 'eslint-plugin-import-x';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

// Unit strings are backend-owned (`ChannelSpec.unit`, `ShapContribution.unit`)
// and are rendered verbatim. This selector makes a frontend unit lookup table a
// lint error rather than a review finding; the list mirrors backend.md §3.1 and
// exists only here, never in shipped code.
const UNIT_KEY_SELECTOR =
  'ObjectExpression > Property[key.value=/^(K|rpm|W|min|s|Hz|g|%|N·m|g²\\/Hz|°C|µm)$/]';

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'dist-mock/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'public/mockServiceWorker.js',
      'src/contracts/api.ts',
      'src/contracts/ws.ts',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'jsx-a11y': jsxA11y,
      'import-x': importX,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'separate-type-imports' },
      ],
      '@typescript-eslint/no-non-null-assertion': 'error',
      'no-restricted-syntax': [
        'error',
        {
          selector: UNIT_KEY_SELECTOR,
          message:
            'No unit lookup tables. Render ChannelSpec.unit / ShapContribution.unit verbatim via formatUnit().',
        },
      ],
      'import-x/no-restricted-paths': [
        'error',
        {
          zones: [
            {
              target: './src',
              from: './src/mock',
              except: ['./'],
              message:
                'Mock code must never be reachable from application code (frontend.md §1.1).',
            },
          ],
        },
      ],
      eqeqeq: ['error', 'smart'],
      'no-console': ['error', { allow: ['warn', 'error', 'debug'] }],
    },
  },
  {
    // Mock code may import mock code; test files may reach for the mocks.
    files: ['src/mock/**/*.{ts,tsx}', '**/__tests__/**/*.{ts,tsx}', 'vitest.setup.ts'],
    rules: { 'import-x/no-restricted-paths': 'off' },
  },
  {
    files: ['**/__tests__/**/*.{ts,tsx}', 'e2e/**/*.ts'],
    rules: {
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
    },
  },
  {
    // Plugin configs ship untyped rule records; the config file itself is not
    // application code and is not worth a cast per plugin.
    files: ['*.config.{ts,js}', 'vitest.setup.ts'],
    rules: {
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
    },
  },
);
