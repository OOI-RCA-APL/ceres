// @ts-check

import prettier from '@vue/eslint-config-prettier'
import imports from 'eslint-plugin-import'
import unusedImports from 'eslint-plugin-unused-imports'

import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt([
  prettier,
  {
    plugins: {
      imports: imports,
      'unused-imports': unusedImports,
    },
    rules: {
      'max-len': ['warn', 100, 2, { ignoreStrings: true }],
      'no-undef': 'off', // Handled by TypeScript.
      'prefer-const': 'off', // For `$ref` macros to use `let` properly.
      '@typescript-eslint/no-unused-vars': 'warn',
      'imports/no-unresolved': 'off',
      'imports/order': ['warn', { 'newlines-between': 'always', alphabetize: { order: 'asc' } }],
      'unused-imports/no-unused-imports': 'warn',
      'vue/attributes-order': ['warn', { alphabetical: true }],
      'vue/block-order': ['warn', { order: ['script', 'template', 'style'] }],
      'vue/multi-word-component-names': 'off',
      'vue/require-default-prop': 'off',
    },
  },
])
