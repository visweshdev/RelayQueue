import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.RELAYQUEUE_URL || 'http://localhost:8000';
const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await mkdir('output/browser-checks', { recursive: true });
await context.tracing.start({ screenshots: true, snapshots: true });
async function open() { await page.goto(base); }
async function connect() {
  await page.getByLabel('Access key', { exact: true }).fill('dev-key-1');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.getByText('Workspace connected', { exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector('#refresh').disabled === false);
}
async function sampleRace() {
  await open();
  await page.locator('nav a[href="#upload"]').click();
  // Deliberately ignore abort so the test also covers an already-resolved transport.
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => String(url).includes('sample.csv')
      ? new Promise(resolve => { window.releaseSample = () => resolve(new Response('sku,quantity,unit_price\nSAMPLE,1,1.00\n')); })
      : original(url, options);
  });
  await page.getByRole('button', { name: 'Use sample data', exact: true }).click();
  await page.waitForFunction(() => typeof window.releaseSample === 'function');
  await page.locator('#file').setInputFiles({ name: 'my-sales.csv', mimeType: 'text/csv', buffer: Buffer.from('sku,quantity,unit_price\nOWN,1,2.00\n') });
  await page.evaluate(async () => { window.releaseSample(); await new Promise(resolve => setTimeout(resolve, 0)); });
  assert.equal(await page.locator('#file-name').textContent(), 'my-sales.csv');
  assert.equal(await page.locator('#file').evaluate(input => input.files[0].name), 'my-sales.csv');
  console.log('PASS: delayed sample cannot replace a newer file selection');
}
async function refreshRace() {
  await open(); await connect();
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.listCalls = 0;
    window.fetch = (url, options) => {
      if (String(url).includes('/v1/jobs?')) {
        window.listCalls++;
        if (window.listCalls === 1) return new Promise(resolve => {
          window.releaseList = () => resolve(original(url, options));
        });
      }
      return original(url, options);
    };
  });
  // Wait for the actual scheduled poll; do not invoke application internals.
  await page.waitForFunction(() => typeof window.releaseList === 'function', { timeout: 12000 });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  assert.notEqual(await page.locator('#message').textContent(), 'Job list refreshed.');
  await page.evaluate(() => window.releaseList());
  await page.locator('#message').filter({ hasText: 'Job list refreshed.' }).waitFor();
  assert.ok(await page.evaluate(() => window.listCalls >= 2));
  console.log('PASS: manual refresh waits for polling and sends its own request');
}
try {
  await sampleRace();
  await refreshRace();
  assert.deepEqual(errors, []);
  await page.screenshot({ path: 'output/browser-checks/dashboard.png', fullPage: true });
} finally {
  await context.tracing.stop({ path: 'output/browser-checks/trace.zip' });
  await browser.close();
}
