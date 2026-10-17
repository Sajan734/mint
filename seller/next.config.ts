import type { NextConfig } from "next";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** One .env for the whole repo (../.env). Values already set in the environment win; no file means defaults. */
function loadRootEnv(): void {
  let text = "";
  try {
    text = readFileSync(resolve(process.cwd(), "..", ".env"), "utf8");
  } catch {
    return;
  }
  for (const line of text.split(/\r?\n/)) {
    const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^(['"])(.*)\1$/, "$2");
  }
}
loadRootEnv();

const nextConfig: NextConfig = {
  // Browser code reads these; pass them explicitly so they are inlined however the app is started.
  env: Object.fromEntries(Object.entries(process.env).filter(([k]) => k.startsWith("NEXT_PUBLIC_"))) as Record<string, string>,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
