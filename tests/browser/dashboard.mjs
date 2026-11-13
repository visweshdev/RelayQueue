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
async function workflow() {
  await open(); await connect();
  const headers = { 'X-API-Key': 'dev-key-1' };
  for (let i = 0; i < 13; i++) {
    const response = await context.request.post(`${base}/v1/jobs`, { headers, data: { task: 'noop' } });
    assert.equal(response.status(), 201);
  }
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await page.locator('#message').filter({ hasText: 'Job list refreshed.' }).waitFor();
  await page.getByRole('button', { name: 'Load older jobs', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('#rows tr').length > 12);
  const count = await page.locator('#rows tr').count();
  await page.waitForTimeout(5500);
  assert.equal(await page.locator('#rows tr').count(), count);
  await page.getByLabel('Search loaded jobs').fill('nonexistent-job-identifier');
  await page.getByText('No matching jobs', { exact: true }).waitFor();
  await page.getByLabel('Search loaded jobs').fill('');
  const tabs = context.pages().length;
  await page.locator('nav a[href="#upload"]').click();
  await page.getByRole('button', { name: 'Create report', exact: true }).click();
  await page.locator('#message').filter({ hasText: 'Choose a CSV file' }).waitFor();
  await page.getByRole('button', { name: 'Use sample data', exact: true }).click();
  await page.getByText('Sample sales.csv selected', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Create report', exact: true }).click();
  await page.locator('#result-summary').filter({ hasText: '50.10' }).waitFor({ timeout: 30000 });
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').isVisible(), false);
  await page.locator('nav a[href="#guide"]').click();
  await page.getByText('Built to work with your code.', { exact: true }).waitFor();
  assert.equal(context.pages().length, tabs);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const view of ['upload', 'jobs']) {
    await page.locator(`nav a[href="#${view}"]`).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  await page.screenshot({ path: 'output/browser-checks/mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route('**/v1/jobs?*', route => route.abort());
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await page.locator('#message').filter({ hasText: 'Cannot reach RelayQueue' }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Refresh', exact: true }).isEnabled(), true);
  await page.unroute('**/v1/jobs?*');
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await page.locator('#message').filter({ hasText: 'Job list refreshed.' }).waitFor();
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  assert.equal(await page.locator('#rows tr').count(), 0);
  await page.locator('nav a[href="#upload"]').click();
  assert.equal(await page.getByRole('button', { name: 'Create report', exact: true }).isEnabled(), false);
  console.log('PASS: upload, result, navigation, pagination, search, mobile, network recovery, disconnect');
}
try {
  await sampleRace();
  await refreshRace();
  await workflow();
  assert.deepEqual(errors, []);
  await page.screenshot({ path: 'output/browser-checks/dashboard.png', fullPage: true });
} catch (error) {
  await page.screenshot({ path: "output/browser-checks/failure.png", fullPage: true });
  throw error;
} finally {
  await context.tracing.stop({ path: 'output/browser-checks/trace.zip' });
  await browser.close();
}
