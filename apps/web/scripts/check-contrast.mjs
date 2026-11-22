/** Check AA contrast of shared text tokens on each surface. Run with node scripts/check-contrast.mjs. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const css = await readFile(new URL("../app/tokens.css", import.meta.url), "utf8");
const tokens = Object.fromEntries([...css.matchAll(/--([a-z-]+):\s*(#[\da-f]{6})/gi)].map(match => [match[1], match[2]]));
function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
}
for (const foreground of ["ink", "ink-muted", "ink-subtle", "brand", "positive", "attention", "critical"]) {
  for (const background of ["canvas", "surface", "surface-raised"]) {
    const values = [luminance(tokens[foreground]), luminance(tokens[background])].sort((a, b) => b - a);
    const ratio = (values[0] + .05) / (values[1] + .05);
    assert.ok(ratio >= 4.5, `${foreground} on ${background}: ${ratio.toFixed(2)} fails AA`);
    console.log(`${foreground} on ${background}: ${ratio.toFixed(2)}:1 PASS`);
  }
}
