// Screenshot every slide of an HTML deck at 1920x1080 and dump titles + speaker notes.
//
//   node export_slides.mjs <deck.html> <outDir>
//
// Writes <outDir>/slide-NN.png and <outDir>/slides.json. Exits non-zero when a slide
// overflows the canvas or has a broken image, so a bad export never reaches the PDF.
import puppeteer from "puppeteer";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [deckPath, outDir] = process.argv.slice(2);
if (!deckPath || !outDir) {
  console.error("usage: node export_slides.mjs <deck.html> <outDir>");
  process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || undefined,
  args: ["--no-sandbox", "--allow-file-access-from-files"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(path.resolve(deckPath)).href + "?export", { waitUntil: "networkidle0", timeout: 60000 });
await page.evaluate(() => document.fonts.ready);
const total = await page.evaluate(() => window.deckTotal);
const meta = [];
let bad = 0;
for (let i = 0; i < total; i++) {
  await page.evaluate((n) => window.deckShow(n), i);
  await new Promise((r) => setTimeout(r, 700));
  const info = await page.evaluate((n) => {
    const s = document.querySelectorAll(".slide")[n];
    const overflow = [...s.querySelectorAll("*")].some((el) => {
      const r = el.getBoundingClientRect();
      return r.bottom > 1081 || r.right > 1921;
    });
    const broken = [...s.querySelectorAll("img")]
      .filter((img) => !img.complete || img.naturalWidth === 0)
      .map((img) => img.getAttribute("src"));
    return { title: s.dataset.title, notes: s.querySelector(".notes")?.textContent.trim() || "", overflow, broken };
  }, i);
  const file = `slide-${String(i + 1).padStart(2, "0")}.png`;
  await page.screenshot({ path: path.join(outDir, file), clip: { x: 0, y: 0, width: 1920, height: 1080 } });
  meta.push({ file, ...info });
  if (info.overflow || info.broken.length) bad++;
  console.log(`${i + 1}\t${info.title}\toverflow=${info.overflow}\tbroken=${info.broken.join(",") || "-"}`);
}
fs.writeFileSync(path.join(outDir, "slides.json"), JSON.stringify(meta, null, 2));
await browser.close();
process.exit(bad ? 1 : 0);
