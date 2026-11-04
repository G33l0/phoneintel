// Renders the PHONEINTEL logo assets: NODE_PATH=$(npm root -g) node render.js
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const assets = path.join(__dirname, "..", "app", "assets");
const svg = fs.readFileSync(path.join(__dirname, "logo.svg"), "utf8");
const markOnly = svg.replace('<g id="bgshape">', '<g id="bgshape" style="display:none">');
const bgOnly = svg.replace('<g id="mark">', '<g id="mark" style="display:none">').replace('rx="112"', 'rx="0"');
const sized = (s, w, h, style = "") => s.replace('width="512" height="512"', `width="${w}" height="${h}" style="${style}"`);
const page = (body, w, h, bg = "transparent", extra = "") =>
  `<html><body style="margin:0;width:${w}px;height:${h}px;background:${bg};overflow:hidden;${extra}">${body}</body></html>`;

(async () => {
  const browser = await chromium.launch();
  const tab = await browser.newPage({ deviceScaleFactor: 1 });
  const shot = async (name, html, w, h, transparent = true) => {
    await tab.setViewportSize({ width: w, height: h });
    await tab.setContent(html);
    await tab.screenshot({ path: path.join(assets, name), omitBackground: transparent });
  };
  await shot("icon.png", page(sized(svg, 512, 512), 512, 512), 512, 512);
  const inner = Math.round(432 * 0.62), off = Math.round((432 - inner) / 2);
  await shot("adaptive_fg.png", page(sized(markOnly, inner, inner, `position:absolute;left:${off}px;top:${off}px`), 432, 432), 432, 432);
  await shot("adaptive_bg.png", page(sized(bgOnly, 432, 432), 432, 432), 432, 432, false);
  await shot("logo_mark.png", page(sized(markOnly, 512, 512), 512, 512), 512, 512);
  const splash = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;font-family:'DejaVu Sans Mono',monospace">
    ${sized(svg, 420, 420)}
    <div style="margin-top:48px;color:#00ff7a;font-size:76px;font-weight:700;letter-spacing:14px">PHONEINTEL</div>
    <div style="margin-top:14px;color:#5fae80;font-size:28px;letter-spacing:6px">BUSINESS MESSAGES ON THE GO</div></div>`;
  await shot("presplash.png", page(splash, 1024, 1024, "#030604"), 1024, 1024, false);
  await browser.close();
  console.log("ok");
})();
