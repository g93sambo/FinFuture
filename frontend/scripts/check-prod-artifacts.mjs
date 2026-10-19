// Fails when development-only artifacts are left in the shipped frontend source.
// Run with `npm run check:prod` (also part of CI).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src/", import.meta.url));

const rules = [
  { name: "console.log/debug left in code", re: /\bconsole\.(log|debug|trace)\s*\(/ },
  { name: "debugger statement", re: /^\s*debugger\s*;?\s*$/m },
  { name: "lorem ipsum placeholder", re: /lorem ipsum/i },
  { name: "hard-coded localhost URL", re: /https?:\/\/(localhost|127\.0\.0\.1)(?![^\n]*allow-localhost)/ },
  { name: "unfinished-work marker shown to users", re: /\b(TODO|FIXME|XXX)\b/ },
];

// The API base URL falls back to localhost for `next dev`; production builds must set NEXT_PUBLIC_API_URL.
const allow = { "lib/api.ts": ["hard-coded localhost URL"] };

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* files(p);
    else if (/\.(tsx?|jsx?|mjs)$/.test(name)) yield p;
  }
}

const problems = [];
for (const file of files(root)) {
  const rel = relative(root, file).replace(/\\/g, "/");
  const text = readFileSync(file, "utf8");
  for (const rule of rules) {
    if ((allow[rel] ?? []).includes(rule.name)) continue;
    const lines = text.split("\n");
    lines.forEach((line, i) => {
      if (rule.re.test(line)) problems.push(`${rel}:${i + 1}  ${rule.name}`);
    });
  }
}

if (problems.length) {
  console.error(`Development artifacts found:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}
console.info("No development artifacts found in frontend/src.");
