import { expect, test } from '@playwright/test';

/**
 * The Phase-3 shell smoke (frontend.md §4.4). It runs against the MSW-backed
 * production-shaped build: no API container, no broker, no trained model.
 */
test.describe('shell smoke', () => {
  test('renders the chrome and one placeholder per machine from hello + snapshot', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });

    await page.goto('/');

    await expect(page.getByTestId('app-shell')).toBeVisible();
    await expect(page.getByTestId('top-bar')).toBeVisible();
    await expect(page.getByTestId('main-region')).toBeVisible();
    await expect(page.getByTestId('right-rail')).toBeVisible();

    // hello carries the run id; snapshot populates the machines.
    await expect(page.getByTestId('run-id')).toHaveText(/^run_[0-9a-f]{12}$/);
    await expect(page.getByTestId('connection-pill')).toContainText('LIVE');

    // The grid is machine_count-driven, read from the plant descriptor itself.
    const machineCount = await page.evaluate(async () => {
      const response = await fetch('/api/plants');
      const plants = (await response.json()) as Array<{
        plant_id: string;
        machine_count: number;
      }>;
      return plants.find((plant) => plant.plant_id === 'ai4i')?.machine_count ?? 0;
    });
    expect(machineCount).toBeGreaterThan(0);

    const tiles = page.locator('[data-testid^="floor-placeholder-tile-"]');
    await expect(tiles).toHaveCount(machineCount);

    // Every unbuilt feature shows its designed empty state, not a stub.
    await expect(page.getByTestId('empty-rail-feed')).toBeVisible();

    await page.getByTestId('floor-demo-link').click();
    await expect(page).toHaveURL(/\/machines\/ai4i-\d{2}$/);
    await expect(page.getByTestId('machine-detail')).toBeVisible();
    await expect(page.getByTestId('empty-detail-shap')).toBeVisible();

    expect(consoleErrors).toEqual([]);
  });
});
