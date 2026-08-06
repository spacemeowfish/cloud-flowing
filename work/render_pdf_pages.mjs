import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const [pdfPath, outputDir] = process.argv.slice(2);
if (!pdfPath || !outputDir) {
  throw new Error("Usage: node render_pdf_pages.mjs <input.pdf> <output-dir>");
}

const modulesRoot = process.env.CODEX_NODE_MODULES;
if (!modulesRoot) {
  throw new Error("CODEX_NODE_MODULES must point to the bundled node_modules directory");
}
const require = createRequire(pathToFileURL(path.join(modulesRoot, "_codex_anchor.js")));
const { createCanvas } = require("@napi-rs/canvas");
const pdfjs = await import(pathToFileURL(path.join(modulesRoot, "pdfjs-dist/legacy/build/pdf.mjs")).href);

fs.mkdirSync(outputDir, { recursive: true });
const data = new Uint8Array(fs.readFileSync(pdfPath));
const pdf = await pdfjs.getDocument({ data, disableWorker: true, useSystemFonts: true }).promise;

for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
  const page = await pdf.getPage(pageNumber);
  const viewport = page.getViewport({ scale: 2 });
  const canvas = createCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
  const context = canvas.getContext("2d");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvasContext: context, viewport, canvas }).promise;
  const outputPath = path.join(outputDir, `page-${String(pageNumber).padStart(2, "0")}.png`);
  fs.writeFileSync(outputPath, canvas.toBuffer("image/png"));
}

process.stdout.write(`${pdf.numPages}\n`);
