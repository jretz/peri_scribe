import {
  test, expect, update, finishAnimations
} from "../../../helpers/browser/updates.mjs";

test("startPage gives each window an independent keyboard-operated collapse control",
  async ({ viewer }) => {
    await viewer.open([update("Timber", 10)]);
    const group = viewer.group(0);
    const toggle = group.getByRole("button", { name: "0–60 minutes ago" });
    const body = group.locator(".group-body");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveAttribute("aria-controls",
      await body.getAttribute("id"));
    await viewer.page.getByRole("searchbox").focus();
    await viewer.page.keyboard.press("Tab");
    await expect(toggle).toBeFocused();
    await viewer.page.keyboard.press("Enter");

    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(body).toBeHidden();
    await expect(viewer.group(1).locator(".group-body")).toBeVisible();
    await expect(toggle).toBeFocused();
    await viewer.page.keyboard.press("Space");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(body).toBeVisible();
  });

test("startPage retains collapse, sorting and focused controls across live replacement",
  async ({ viewer }) => {
    const records = [update("Timber", 10), update("Austin", 20)];
    await viewer.open(records);
    const group = viewer.group(0);
    const body = group.locator(".group-body");
    const sort = group.locator(".sort-order");
    await group.locator(".group-toggle").click();
    await finishAnimations(viewer.page);
    await sort.focus();
    await viewer.page.keyboard.press("Enter");
    await viewer.replace([...records, update("Zinc", 30)]);

    await expect(body).toBeHidden();
    await expect(sort).toBeFocused();
    await expect(sort).toHaveText("3 fires ordered by name");
    await expect(group.locator(".fire-name")).toHaveText(["Austin", "Timber", "Zinc"]);
    await viewer.page.getByRole("searchbox").fill("TIM");
    await expect(body).toBeHidden();
    await expect(sort).toHaveText("1 fire ordered by name");
    await viewer.page.getByRole("searchbox").fill("");
    await expect(body).toBeHidden();
    await expect(sort).toHaveText("3 fires ordered by name");
  });

test("startPage honors reduced motion while rows move into collapsed windows",
  async ({ viewer }) => {
    await viewer.page.emulateMedia({ reducedMotion: "reduce" });
    await viewer.open([update("Timber", 59.9)]);
    await viewer.group(1).locator(".group-toggle").click();
    await viewer.page.clock.fastForward(6001);

    await expect(viewer.group(1).locator(".fire-name")).toHaveText("Timber");
    await expect(viewer.row("Timber")).toBeHidden();
    await expect(viewer.page.locator(".departing-update")).toHaveCount(0);
    expect(await viewer.page.evaluate(() => document.getAnimations().length)).toBe(0);
  });
