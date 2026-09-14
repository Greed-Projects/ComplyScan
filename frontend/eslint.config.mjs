import { defineConfig, globalIgnores } from "eslint/config";
import nextPlugin from "@next/eslint-plugin-next";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores([
    ".next/**",
    "node_modules/**",
    "out/**",
    "build/**",
    "dist/**",
    "next-env.d.ts",
  ]),

  ...tseslint.configs.recommended,

  reactHooks.configs.flat.recommended,

  {
    files: ["**/*.{js,jsx,ts,tsx}"],

    plugins: {
      "@next/next": nextPlugin,
    },

    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
    },
  },
]);