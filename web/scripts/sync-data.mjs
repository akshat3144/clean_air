// Copy the model's artifacts into public/data/ so the built app can fetch
// /data/*.json. This is the JS twin of scripts/02_publish_artifacts.py: that
// one runs after a fit on a machine with Python, this one runs inside `npm run
// build` on Vercel, which has the repo but no Python. Same files, same place.
//
// public/data/ is gitignored on purpose -- data/artifacts/ is the one source.
import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = resolve(web, "..", "data", "artifacts");
const dst = join(web, "public", "data");

if (!existsSync(src)) {
  // Vercel with "Include source files outside of the Root Directory" turned
  // off, or a checkout of web/ alone. Say so rather than build a site that
  // 404s on every tab.
  console.error(`sync-data: ${src} not found -- build from the repo root`);
  process.exit(1);
}

mkdirSync(dst, { recursive: true });
const files = readdirSync(src).filter((f) => f.endsWith(".json"));
for (const f of files) cpSync(join(src, f), join(dst, f));
console.log(`sync-data: ${files.length} artifacts -> public/data/`);
