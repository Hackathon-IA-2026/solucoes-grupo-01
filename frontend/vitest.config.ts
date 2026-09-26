import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./app/test/setup.ts"],
    exclude: ["tests/e2e/**", "node_modules/**", "build/**"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["app/**/*.{ts,tsx}"],
      exclude: ["app/**/*.test.{ts,tsx}", "app/test/**", "app/routes/**", "app/root.tsx", "app/routes.ts"],
    },
  },
});
