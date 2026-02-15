import { put } from "@vercel/blob";
import { readFileSync, readdirSync } from "fs";
import { join, basename } from "path";

const MODELS_DIR = new URL("../public/models", import.meta.url).pathname;

const token = process.env.BLOB_READ_WRITE_TOKEN;
if (!token) {
  console.error("Missing BLOB_READ_WRITE_TOKEN environment variable");
  process.exit(1);
}

const files = readdirSync(MODELS_DIR).filter((f) => f.endsWith(".ply"));

if (files.length === 0) {
  console.error("No .ply files found in public/models/");
  process.exit(1);
}

console.log(`Uploading ${files.length} PLY files to Vercel Blob...\n`);

for (const file of files) {
  const filePath = join(MODELS_DIR, file);
  const data = readFileSync(filePath);

  const blob = await put(`models/${file}`, data, {
    access: "public",
    addRandomSuffix: false,
    allowOverwrite: true,
    token,
  });

  console.log(`  ${file} → ${blob.url}`);
}

console.log("\nDone! Set VITE_BLOB_URL to the base URL (everything before /models/).");
