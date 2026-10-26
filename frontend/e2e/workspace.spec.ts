import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

test.describe.configure({ mode: 'serial' });

test('empty workspace has a focused, responsive first-run experience', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Big ideas deserve a clear desk.' }),
  ).toBeVisible();
  await page.screenshot({ path: 'test-results/folio-empty.png', fullPage: true });
  const violations = (await new AxeBuilder({ page }).analyze()).violations;
  expect(
    violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({ target: n.target, reason: n.failureSummary })),
    })),
  ).toEqual([]);
});

test('sample import, pagination, filtering and sorting work against Python', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Try a sample statement' }).click();
  await expect(page.getByRole('tab', { name: 'All transactions 36' })).toBeVisible();
  await expect(page.getByText('Page 1 of 4')).toBeVisible();
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(page.getByText('Page 2 of 4')).toBeVisible();
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('FIGMA');
  await expect(page.getByText('1–2 of 2 transactions')).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByLabel('Filter money type').selectOption('refund');
  await expect(page.getByText('1–2 of 2 transactions')).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByRole('button', { name: 'Amount', exact: true }).click();
  await expect(page.locator('tbody tr').first()).toContainText('STRIPE PAYOUT');
  await page.getByRole('button', { name: 'Date', exact: true }).click();
  await page.getByRole('button', { name: 'Dismiss notification' }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: 'test-results/folio-overview.png', fullPage: true });
});

test('review explains uncertainty, remembers an exact rule and persists a note', async ({
  page,
}) => {
  await page.goto('/#transactions');
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('AMAZON');
  await page.getByRole('button', { name: 'Review AMAZON MKTPLACE 83729102', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('A broad retailer does not identify what was purchased.');
  await dialog.getByRole('combobox', { name: 'Category', exact: true }).selectOption('office');
  await dialog.getByLabel('Business context').fill('Paper and a desk organizer for the studio.');
  await dialog.getByLabel('Remember for future imports').check();
  await page.screenshot({ path: 'test-results/folio-review.png', fullPage: true });
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.reload();
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('AMAZON');
  await expect(page.locator('tbody tr')).toContainText('Confirmed');
  await expect(page.locator('tbody tr')).toContainText('Paper and a desk organizer');
  await page.getByRole('link', { name: 'Merchant rules' }).click();
  await expect(page.locator('tbody')).toContainText('AMAZON MKTPLACE');
});

test('CSV upload respects explicit card signs and applies only the exact learned merchant', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Import statement', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Statement file').setInputFiles({
    name: 'fictional-card.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'Date,Description,Amount\n2026-09-01,AMAZON MKTPLACE 83729102,45.00\n2026-09-02,AMAZON FRESH,10.00',
    ),
  });
  await dialog.getByLabel('Signed amount convention').selectOption('card');
  await dialog.getByRole('button', { name: 'Import statement' }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('tab', { name: 'All transactions 2' })).toBeVisible();
  const known = page.locator('tbody tr').filter({ hasText: 'AMAZON MKTPLACE' });
  await expect(known).toContainText('Your rule');
  await expect(known).toContainText('-$45.00');
  const unknown = page.locator('tbody tr').filter({ hasText: 'AMAZON FRESH' });
  await expect(unknown).toContainText('Needs review');
});

test('invalid CSV gives row-level feedback and leaves the statement library unchanged', async ({
  page,
  request,
}) => {
  const before = await (await request.get('/api/workspace')).json();
  await page.goto('/');
  await page.getByRole('button', { name: 'Import statement', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Statement file').setInputFiles({
    name: 'invalid.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('Date,Description,Amount\n2026-10-99,ADOBE,-59.99'),
  });
  await dialog.getByRole('button', { name: 'Import statement' }).click();
  await expect(dialog.getByRole('alert')).toContainText('Row 2');
  const after = await (await request.get('/api/workspace')).json();
  expect(after.statements.length).toBe(before.statements.length);
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
});

test('batch categorization, category exploration and CSV downloads work', async ({ page }) => {
  await page.goto('/#transactions');
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('FIGMA');
  await page.getByLabel('Select page', { exact: true }).check();
  await page.getByRole('button', { name: 'Categorize selected' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: 'Category', exact: true }).selectOption('software');
  await dialog.getByRole('button', { name: 'Confirm 2 rows' }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('tbody tr').first()).toContainText('Confirmed');
  await page.getByRole('button', { name: 'Export', exact: true }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('menuitem', { name: 'Confirmed transactions' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain('folio-');
  await page.getByRole('link', { name: 'Categories', exact: true }).click();
  await page.getByRole('button', { name: /Software & subscriptions/ }).click();
  await expect(page.getByLabel('Filter category')).toHaveValue('software');
  await expect(page.locator('tbody tr').first()).toContainText('Software');
});

test('rule deletion and statement navigation are functional', async ({ page }) => {
  await page.goto('/#rules');
  await page.getByRole('button', { name: 'Remove rule for AMAZON MKTPLACE' }).click();
  await expect(
    page.getByRole('heading', { name: 'Your experience is the best shortcut.' }),
  ).toBeVisible();
  await page.getByRole('link', { name: 'Statements', exact: true }).click();
  await page.getByRole('button', { name: /^fictional-card.csv/ }).click();
  await expect(page.getByLabel('Statement', { exact: true })).not.toHaveValue('');
  await expect(page.getByRole('tab', { name: 'All transactions 2' })).toBeVisible();
});

test('dialog traps focus, closes on Escape and restores the trigger', async ({ page }) => {
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Import statement', exact: true });
  await trigger.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  for (let i = 0; i < 14; i++) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => !!document.activeElement?.closest('dialog'))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('mobile workspace has no page overflow and keeps review usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('tab', { name: /All transactions/ })).toBeVisible();
  const overflow = await page.evaluate(() => ({
    width: window.innerWidth,
    scroll: document.documentElement.scrollWidth,
    elements: [...document.querySelectorAll('body *')]
      .filter(
        (el) =>
          el.getBoundingClientRect().right > window.innerWidth + 1 && !el.closest('.table-scroll'),
      )
      .map((el) => ({
        tag: el.tagName,
        class: el.className,
        right: el.getBoundingClientRect().right,
      }))
      .slice(0, 15),
  }));
  expect(overflow.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width);
  await page.screenshot({ path: 'test-results/folio-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: 'Merchant rules' }).click();
  await expect(page.getByRole('heading', { name: 'Merchant rules 0' })).toBeVisible();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: 'Transactions', exact: false }).click();
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('JOES');
  await page.getByRole('button', { name: 'Review JOES CAFE 9921' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
});

test('populated workspace, review dialog and navigation meet automated accessibility checks', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.getByRole('tab', { name: /All transactions/ })).toBeVisible();
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({ target: n.target, reason: n.failureSummary })),
    })),
  ).toEqual([]);
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('JOES');
  await page.getByRole('button', { name: 'Review JOES CAFE 9921' }).click();
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({ target: n.target, reason: n.failureSummary })),
    })),
  ).toEqual([]);
});

test('reimporting an identical statement opens its existing rows without double counting', async ({
  page,
  request,
}) => {
  const before = await (await request.get('/api/workspace')).json();
  const sample = await (await request.get('/api/sample')).body();
  await page.goto('/');
  await page.getByRole('button', { name: 'Import statement', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog
    .getByLabel('Statement file')
    .setInputFiles({ name: 'sample.csv', mimeType: 'text/csv', buffer: sample });
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
  await dialog.getByRole('button', { name: 'Import statement' }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('tab', { name: 'All transactions 36' })).toBeVisible();
  const after = await (await request.get('/api/workspace')).json();
  expect(after.summary.total).toBe(before.summary.total);
  expect(after.statements.length).toBe(before.statements.length);
});

test('removing a statement requires an explicit decision and refreshes the library', async ({
  page,
}) => {
  await page.goto('/#statements');
  await page.getByRole('button', { name: 'Remove fictional-card.csv', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Its transactions and review history will be removed.');
  await dialog.getByRole('button', { name: 'Keep statement' }).click();
  await expect(page.getByRole('button', { name: /fictional-card.csv/ }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Remove fictional-card.csv', exact: true }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Remove statement', exact: true })
    .click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.getByRole('button', { name: /fictional-card.csv/ })).toHaveCount(0);
});

test('large valid category totals preserve every cent in the browser', async ({
  page,
  request,
}) => {
  const content =
    'Date,Description,Amount\n' +
    Array.from({ length: 90 }, (_, i) => `2026-10-01,ADOBE REF ${i},-999999999999.99`).join('\n');
  const imported = await request.post('/api/statements?currency=EUR', {
    multipart: {
      file: {
        name: 'fictional-high-value.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from(content),
      },
    },
  });
  expect(imported.status()).toBe(201);
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Currency', exact: true }).selectOption('EUR');
  await expect(page.getByRole('article').filter({ hasText: 'Business spending' })).toContainText(
    '\u20ac89,999,999,999,999.10',
  );
});

test('borderless card PDF requires a year and reconciles through the upload dialog', async ({
  page,
}) => {
  const python = process.env.CI
    ? 'python'
    : process.platform === 'win32'
      ? resolve('../.venv/Scripts/python.exe')
      : resolve('../.venv/bin/python');
  const fixture = execFileSync(
    python,
    [
      '-c',
      'import runpy,sys; fixture=runpy.run_path("../backend/tests/test_pdf_text_tables.py"); sys.stdout.buffer.write(fixture["card_pdf"]())',
    ],
    { stdio: ['ignore', 'pipe', 'pipe'] },
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Import statement', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Statement file').setInputFiles({
    name: 'fictional-card-layout.pdf',
    mimeType: 'application/pdf',
    buffer: fixture,
  });
  await dialog.getByLabel('Signed amount convention').selectOption('card');
  await dialog.getByRole('button', { name: 'Import statement', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Statement year');
  await dialog.getByText('Format details', { exact: true }).click();
  await dialog.getByRole('spinbutton', { name: /Statement year/ }).fill('2026');
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
  await dialog.getByRole('button', { name: 'Import statement', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('tab', { name: 'All transactions 4' })).toBeVisible();
  await expect(page.getByRole('article').filter({ hasText: 'Client income' })).toContainText(
    '$0.00',
  );
  await expect(page.getByRole('article').filter({ hasText: 'Business spending' })).toContainText(
    '$5.00',
  );
});

test('skip link focuses content without changing the current route or filters', async ({
  page,
}) => {
  await page.goto('/#transactions');
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('FIGMA');
  await page.getByRole('link', { name: 'Skip to content' }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#transactions$/);
  await expect(page.locator('main')).toBeFocused();
  await expect(page.getByRole('textbox', { name: 'Search transactions' })).toHaveValue('FIGMA');
});

test('closed mobile navigation is inert, open navigation traps focus, desktop remains available', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#transactions');
  await expect(page.getByRole('textbox', { name: 'Search transactions' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toHaveCount(0);
  await expect(page.locator('.sidebar')).toHaveAttribute('inert', '');
  for (let i = 0; i < 18; i++) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => !!document.activeElement?.closest('.sidebar'))).toBe(false);
  }
  const trigger = page.getByRole('button', { name: 'Open navigation', exact: true });
  await trigger.click();
  const drawer = page.getByRole('dialog', { name: 'Workspace navigation' });
  await expect(drawer).toBeVisible();
  await expect(page.locator('.main-shell')).toHaveAttribute('inert', '');
  for (let i = 0; i < 18; i++) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => !!document.activeElement?.closest('.sidebar'))).toBe(true);
  }
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await expect(drawer).not.toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
  await expect(page.locator('.sidebar')).not.toHaveAttribute('inert', '');
  await page.getByRole('link', { name: 'Categories', exact: true }).click();
  await expect(page).toHaveURL(/#categories$/);
});

test('credits-only income choice cannot leak into the next debit batch', async ({
  page,
  request,
}) => {
  const file =
    'Date,Description,Amount\n2026-12-01,REVIEW BATCH CREDIT,200\n2026-12-02,REVIEW BATCH DEBIT,-20';
  const result = await request.post('/api/statements', {
    multipart: {
      file: { name: 'batch-validation.csv', mimeType: 'text/csv', buffer: Buffer.from(file) },
    },
  });
  expect(result.status()).toBe(201);
  await page.goto('/#transactions');
  const search = page.getByRole('textbox', { name: 'Search transactions' });
  await search.fill('REVIEW BATCH CREDIT');
  await page.getByLabel('Select REVIEW BATCH CREDIT', { exact: true }).check();
  await page.getByRole('button', { name: 'Categorize selected' }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: 'Category', exact: true }).selectOption('income');
  await dialog.getByRole('button', { name: 'Confirm 1 rows', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await search.fill('REVIEW BATCH DEBIT');
  await page.getByLabel('Select REVIEW BATCH DEBIT', { exact: true }).check();
  await page.getByRole('button', { name: 'Categorize selected' }).click();
  dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('combobox', { name: 'Category', exact: true })).toHaveValue(
    'office',
  );
  await expect(dialog.getByRole('option', { name: 'Client income' })).toHaveCount(0);
  const sent = page.waitForRequest(
    (r) => r.url().endsWith('/api/review-batch') && r.method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Confirm 1 rows', exact: true }).click();
  expect((await sent).postDataJSON().category).toBe('office');
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('tbody tr')).toContainText('Office & supplies');
  await expect(page.locator('tbody tr')).toContainText('Confirmed');
});

test('search shortcut focuses the field after navigating from another view', async ({ page }) => {
  await page.goto('/#categories');
  await expect(page.getByRole('heading', { name: 'See the bigger picture.' })).toBeVisible();
  await page.keyboard.press('/');
  await expect(page).toHaveURL(/#transactions$/);
  await expect(page.getByRole('textbox', { name: 'Search transactions' })).toBeFocused();
});

test('editing a purchase surfaces its unsupported refund for review in the workspace', async ({
  page,
  request,
}) => {
  const original = await request.post('/api/statements', {
    multipart: {
      file: {
        name: 'review-original.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('Date,Description,Amount\n2026-12-03,REVIEW SHOP,-10'),
      },
    },
  });
  const originalId = (await original.json()).statement_id;
  let workspace = await (await request.get(`/api/workspace?statement_id=${originalId}`)).json();
  const purchase = workspace.transactions[0];
  expect(
    (
      await request.patch(`/api/transactions/${purchase.id}`, {
        data: { category: 'office', flow: 'expense', version: purchase.version },
      })
    ).status(),
  ).toBe(200);
  expect(
    (
      await request.post('/api/statements', {
        multipart: {
          file: {
            name: 'review-refund.csv',
            mimeType: 'text/csv',
            buffer: Buffer.from('Date,Description,Amount\n2026-12-04,REVIEW SHOP REFUND,7'),
          },
        },
      })
    ).status(),
  ).toBe(201);
  await page.goto('/#transactions');
  await page.getByRole('textbox', { name: 'Search transactions' }).fill('REVIEW SHOP');
  await page.getByRole('button', { name: 'Review REVIEW SHOP', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: 'Category', exact: true }).selectOption('software');
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const refund = page.locator('tbody tr').filter({ hasText: 'REVIEW SHOP REFUND' });
  await expect(refund).toContainText('Needs review');
  await refund.getByRole('button', { name: 'Review REVIEW SHOP REFUND', exact: true }).click();
  dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('available refund capacity changed');
});

test('help opened from mobile navigation restores a visible focus target', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Open navigation', exact: true });
  await trigger.click();
  await page
    .getByRole('dialog', { name: 'Workspace navigation' })
    .getByRole('button', { name: 'A little help' })
    .click();
  await expect(page.getByRole('dialog', { name: 'A little help' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
