import { defineConfig, devices } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';

const databaseDir = mkdtempSync(join(tmpdir(), 'folio-browser-'));
const python = process.env.CI
  ? 'python'
  : `"${process.platform === 'win32' ? resolve('../.venv/Scripts/python.exe') : resolve('../.venv/bin/python')}"`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1100 } },
    },
  ],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8001`,
      url: 'http://127.0.0.1:8001/api/health',
      reuseExistingServer: false,
      timeout: 30_000,
      env: { FOLIO_DB: resolve(databaseDir, 'test.db') },
    },
    {
      command: 'npm run dev -- --port 4173 --strictPort',
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: false,
      timeout: 30_000,
      env: { FOLIO_API_URL: 'http://127.0.0.1:8001' },
    },
  ],
});
