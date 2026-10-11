import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium, expect } from '@playwright/test';

const base = process.argv[2] || 'http://127.0.0.1:3210';
const output = path.resolve(process.argv[3] || '.local/ranks-smoke');
const names = ['Novice', 'Beginner', 'Intermediate', 'Advanced', 'Expert', 'Elite', 'Master', 'Legendary'];
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' });
  for (const [label, route] of [['coach', '/c/demo'], ['client', '/r/demo']]) {
    const response = await page.goto(new URL(route, base).href);
    assert.equal(response.status(), 200);
    const ladder = page.getByRole('list', { name: 'Ranks, lowest to highest' });
    await expect(ladder).toBeVisible({ timeout: 30000 });
    assert.deepEqual(await ladder.locator('li').allTextContents(), names);
    assert(!/Chud Chicken|Godmode Griffin|Ascended Brodie/.test(await page.locator('body').innerText()));
    const palette = await ladder.locator('li > span:first-child').evaluateAll(nodes => nodes.map(node => getComputedStyle(node).backgroundColor));
    const bodies = page.locator('svg[aria-label$="view of the body heat map"]');
    await expect(bodies).toHaveCount(2);
    await expect(bodies.locator('radialGradient')).toHaveCount(0);
    const fills = await bodies.locator('polygon:has(title)').evaluateAll(nodes => nodes.map(node => getComputedStyle(node).fill));
    assert(fills.length >= 16, 'both bodies render their muscle polygons');
    assert(fills.some(fill => palette.includes(fill)), 'trained muscles rendered');
    for (const fill of fills) assert([...palette, 'rgb(82, 82, 91)'].includes(fill), `unexpected muscle color ${fill}`);
    // Wait for the actual reveal to finish rather than capturing its dark initial state.
    await expect.poll(() => bodies.locator('polygon:has(title)').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).opacity === '1'))).toBe(true);
    await page.screenshot({ path: path.join(output, `${label}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${label} fits mobile viewport`);
    assert(await ladder.locator('li > span:last-child').evaluateAll(nodes => nodes.every(node => node.scrollWidth <= node.clientWidth)), `${label} rank names are not truncated`);
    await page.screenshot({ path: path.join(output, `${label}-mobile.png`), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1100 });
    console.log(`PASS ${label}: eight plain ranks, exact body colors, no body gradients, mobile layout`);
    if (label === 'client' && process.argv.includes('--video')) {
      await bodies.locator('polygon').filter({ has: page.locator('title', { hasText: /^quads$/ }) }).first().click();
      await page.getByRole('button', { name: 'Watch', exact: false }).first().click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      await expect.poll(() => dialog.locator('video').evaluate(video => video.readyState), { timeout: 30000 }).toBeGreaterThanOrEqual(2);
      await page.screenshot({ path: path.join(output, 'workout-video.png'), fullPage: true });
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      console.log('PASS client: muscle selection opens playable workout footage and Escape closes it');
    }
  }
  const image = await page.request.get(new URL('/api/recap-image/demo', base).href);
  assert.equal(image.status(), 200);
  assert.match(image.headers()['content-type'], /image\/png/);
  const bytes = await image.body();
  assert.equal(bytes.readUInt32BE(16), 1080);
  assert.equal(bytes.readUInt32BE(20), 1920);
  await writeFile(path.join(output, 'recap.png'), bytes);
  console.log('PASS recap: 1080×1920 PNG generated');
} finally {
  await browser.close();
}
