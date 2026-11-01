import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';

/**
 * 单测直接跑 TypeScript 源码，不依赖先 build。
 * workspace 包名通过 alias 指到各自的 src 入口；新增 workspace 包时在这里补一行。
 */
export default defineConfig({
  resolve: {
    alias: {
      '@sample/catalog': fileURLToPath(
        new URL('./packages/catalog/src/index.ts', import.meta.url),
      ),
    },
  },
  test: {
    include: ['packages/*/tests/**/*.test.ts'],
    environment: 'node',
  },
});
