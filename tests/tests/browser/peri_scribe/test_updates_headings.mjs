import {
  test, expect, update, finishAnimations, requiredHeadingWidth, resizeHeading
} from "../../../helpers/browser/updates.mjs";

test("startPage preserves fractional name widths at the stacking boundary",
  async ({ viewer }) => {
    const name = "East South Fork Trinity River Lightning Complex";
    await viewer.open([update(name, 1500)]);
    const row = viewer.row(name);
    const heading = row.locator(".fire-heading");
    await row.locator(".fire-name").evaluate(node => {
      node.style.flexShrink = "0.5";
    });
    const required = await requiredHeadingWidth(row);

    await resizeHeading(viewer, heading, required + 0.125);
    await expect(heading).not.toHaveClass(/stacked-heading/);
    await resizeHeading(viewer, heading, required - 0.125);
    await expect(heading).toHaveClass(/stacked-heading/);
    await expect(row.locator(".fire-name")).toHaveCSS("flex-shrink", "0.5");
    await resizeHeading(viewer, heading, required + 0.125);
    await expect(heading).not.toHaveClass(/stacked-heading/);
  });

for (const stacked of [true, false]) {
  test(`startPage preserves heading fit during real expansion, stacked=${stacked}`,
    async ({ viewer }) => {
      const name = "East South Fork Trinity River Lightning Complex";
      await viewer.open([update(name, 1500)]);
      const row = viewer.row(name);
      const original = await row.elementHandle();
      const heading = row.locator(".fire-heading");
      const required = await requiredHeadingWidth(row);
      await resizeHeading(viewer, heading, required + (stacked ? -0.5 : 0.5));
      await expect(heading).toHaveClass(stacked ? /stacked-heading/ : /^fire-heading$/);
      const toggle = viewer.group(4).getByRole("button", { name: "24–48 hours ago" });
      await toggle.click();
      await finishAnimations(viewer.page);
      await toggle.click();

      const animationCount = await row.evaluate(node => node.getAnimations().length);
      expect(animationCount).toBeGreaterThan(0);
      await expect(heading).toHaveClass(stacked ? /stacked-heading/ : /^fire-heading$/);
      await finishAnimations(viewer.page);
      await expect(heading).toHaveClass(stacked ? /stacked-heading/ : /^fire-heading$/);
      const retained = await row.evaluate((node, saved) => node === saved, original);
      expect(retained).toBe(true);
    });
}

test("startPage puts the complete name above its timestamp only when needed",
  async ({ viewer }) => {
    await viewer.open([update("Timber", 1500)]);
    const row = viewer.row("Timber");
    const original = await row.elementHandle();
    const heading = row.locator(".fire-heading");
    const required = await requiredHeadingWidth(row);
    await resizeHeading(viewer, heading, required + 0.125);
    await expect(heading).not.toHaveClass(/stacked-heading/);
    await resizeHeading(viewer, heading, required - 1);
    await expect(heading).toHaveClass(/stacked-heading/);
    await expect(row.locator(".fire-name")).toHaveText("Timber");
    const nameBounds = await row.locator(".fire-name").boundingBox();
    const timeBounds = await row.locator(".updated").boundingBox();
    expect(timeBounds.y).toBeGreaterThanOrEqual(nameBounds.y + nameBounds.height);
    await resizeHeading(viewer, heading, required + 0.125);
    await expect(heading).not.toHaveClass(/stacked-heading/);
    const retained = await row.evaluate((node, saved) => node === saved, original);
    expect(retained).toBe(true);
  });

test("startPage fits names independently of optional locations and other fires",
  async ({ viewer }) => {
    await viewer.open([update("Dome", 120), update("Big Grass Complex", 120)]);
    const shortWidth = await requiredHeadingWidth(viewer.row("Dome"));
    const longWidth = await requiredHeadingWidth(viewer.row("Big Grass Complex"));
    const width = (shortWidth + longWidth) / 2;
    for (const name of ["Dome", "Big Grass Complex"]) {
      await resizeHeading(viewer, viewer.row(name).locator(".fire-heading"), width);
    }

    await expect(viewer.row("Dome").locator(".fire-heading"))
      .not.toHaveClass(/stacked-heading/);
    await expect(viewer.row("Big Grass Complex").locator(".fire-heading"))
      .toHaveClass(/stacked-heading/);
    await expect(viewer.row("Dome").locator(".location")).toBeVisible();
    await expect(viewer.row("Dome").locator(".location")).toHaveText("CA");
  });

test("startPage refits a retained name when relative age becomes a date and time",
  async ({ viewer }) => {
    await viewer.open([update("Timber", 59)]);
    const row = viewer.row("Timber");
    const original = await row.elementHandle();
    const heading = row.locator(".fire-heading");
    await resizeHeading(viewer, heading, await requiredHeadingWidth(row) + 0.125);
    await expect(heading).not.toHaveClass(/stacked-heading/);

    await viewer.page.clock.fastForward(60001);
    await finishAnimations(viewer.page);

    await expect(heading).toHaveClass(/stacked-heading/);
    await expect(row.locator("time")).toContainText("Sep 23");
    const retained = await row.evaluate((node, saved) => node === saved, original);
    expect(retained).toBe(true);
  });

test("startPage preserves a departing heading while live rows refit",
  async ({ viewer }) => {
    await viewer.open([update("Timber", 120)]);
    const heading = viewer.row("Timber").locator(".fire-heading");
    await expect(heading).not.toHaveClass(/stacked-heading/);
    await viewer.group(1).locator(".group-toggle").click();
    const ghost = viewer.page.locator(".departing-update");
    await expect(ghost).toHaveCount(1);
    await resizeHeading(viewer, heading, 80);

    await expect(ghost.locator(".fire-heading")).not.toHaveClass(/stacked-heading/);
    await expect(ghost).toHaveAttribute("aria-hidden", "true");
    expect(await ghost.evaluate(node => node.inert)).toBe(true);
    await finishAnimations(viewer.page);
    await expect(ghost).toHaveCount(0);
  });

test("startPage fits and restores sort wording at both real wrapping boundaries",
  async ({ viewer }) => {
    await viewer.open([update("Timber", 1500)]);
    const group = viewer.group(4);
    const heading = group.locator(".section-heading");
    const toggle = group.locator(".group-toggle");
    const sort = group.locator(".sort-order");
    const fullWidth = await heading.evaluate(node =>
      node.querySelector(".group-toggle").getBoundingClientRect().width +
      parseFloat(getComputedStyle(node).columnGap) +
      node.querySelector(".sort-order").getBoundingClientRect().width);
    await resizeHeading(viewer, heading, fullWidth + 0.125);
    await expect(sort).toHaveText("1 fire ordered by time");
    await resizeHeading(viewer, heading, fullWidth - 1);
    await expect(sort).toHaveText("1 fire by time");
    const compactWidth = await heading.evaluate(node =>
      node.querySelector(".group-toggle").getBoundingClientRect().width +
      parseFloat(getComputedStyle(node).columnGap) +
      node.querySelector(".sort-order").getBoundingClientRect().width);
    await resizeHeading(viewer, heading, compactWidth + 0.125);
    await expect(sort).toHaveText("1 fire by time");
    const sideBySide = await sort.boundingBox();
    const titleBeside = await toggle.boundingBox();
    expect(sideBySide.y).toBeLessThan(titleBeside.y + titleBeside.height);
    await resizeHeading(viewer, heading, compactWidth - 1);
    await expect(sort).toHaveText("1 fire ordered by time");
    const wrapped = await sort.boundingBox();
    const titleAbove = await toggle.boundingBox();
    expect(wrapped.y).toBeGreaterThan(titleAbove.y + titleAbove.height);
    expect(wrapped.x).toBeCloseTo(titleAbove.x, 1);
    await resizeHeading(viewer, heading, compactWidth + 0.125);
    await expect(sort).toHaveText("1 fire by time");
    await resizeHeading(viewer, heading, fullWidth + 0.125);
    await expect(sort).toHaveText("1 fire ordered by time");
  });

test("startPage keeps long names readable after fonts settle on a narrow viewport",
  async ({ viewer }) => {
    const name = "East South Fork Trinity River Lightning Complex";
    await viewer.open([update(name, 1500)]);
    await viewer.page.setViewportSize({ width: 320, height: 740 });
    const row = viewer.row(name);
    await expect(row.locator(".fire-heading")).toHaveClass(/stacked-heading/);
    const text = await row.locator(".fire-name").evaluate(node => ({
      visible: node.clientWidth,
      content: node.scrollWidth,
      status: document.fonts.status
    }));
    expect(text.status).toBe("loaded");
    expect(text.content).toBeLessThanOrEqual(text.visible);
    expect(await viewer.page.evaluate(() =>
      document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await viewer.page.setViewportSize({ width: 1100, height: 900 });
    await expect(row.locator(".fire-heading")).not.toHaveClass(/stacked-heading/);
  });
