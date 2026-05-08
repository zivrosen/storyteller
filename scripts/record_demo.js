/**
 * Record a short demo of the bedtime-story UI:
 *   - load /
 *   - type a prompt
 *   - submit
 *   - let the SSE stream drive the timeline + render the story
 *   - capture the run as webm (later converted to gif by record_demo.sh)
 *
 * Pre-req: server running on http://127.0.0.1:8000.
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const OUT_DIR = path.resolve(__dirname, '..', 'docs');
const VIDEO_DIR = path.join(OUT_DIR, '_video');

// Viewport sized for a snappy README embed (not too tall).
const VIEWPORT = { width: 900, height: 1100 };

const PROMPT = 'A story about Alice and her cat Bob, who finds a quiet star in the garden.';

async function main() {
  fs.mkdirSync(VIDEO_DIR, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2, // crisper text in the recording
    recordVideo: { dir: VIDEO_DIR, size: VIEWPORT },
  });
  const page = await context.newPage();

  await page.goto('http://127.0.0.1:8000/');
  await page.waitForSelector('#story-input');

  // Pause briefly so viewers see the empty composer before typing.
  await page.waitForTimeout(700);

  // Type the prompt at a human-ish cadence.
  await page.locator('#story-input').click();
  await page.keyboard.type(PROMPT, { delay: 18 });

  await page.waitForTimeout(500);
  await page.locator('#tell-btn').click();

  // Wait for the story to render. Cap at 90s to avoid hanging the recorder.
  await page.waitForSelector('#story:not(.hidden)', { timeout: 90_000 });

  // Linger on the rendered story for a couple seconds so reviewers
  // see the final state.
  await page.waitForTimeout(2500);

  await context.close();
  await browser.close();

  // Move the (only) video file to a stable name.
  const files = fs.readdirSync(VIDEO_DIR).filter((f) => f.endsWith('.webm'));
  if (!files.length) {
    console.error('No video produced.');
    process.exit(1);
  }
  const src = path.join(VIDEO_DIR, files[0]);
  const dst = path.join(OUT_DIR, 'demo.webm');
  fs.renameSync(src, dst);
  fs.rmdirSync(VIDEO_DIR);
  console.log(`Wrote ${dst}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
