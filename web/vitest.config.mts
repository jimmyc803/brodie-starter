import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": import.meta.dirname,
      // server-only throws outside React Server Components; tests run the server modules directly.
      "server-only": path.join(import.meta.dirname, "tests/server-only-stub.ts"),
    },
  },
  test: { include: ["tests/**/*.test.ts"], exclude: ["tests/parseProgram.test.ts"] },
});
