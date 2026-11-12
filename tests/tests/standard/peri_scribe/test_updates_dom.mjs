import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_dom.mjs";

test("browser computed styles defer layout and retain live fractional widths",
  async context => {
    const page = await viewer.page([viewer.update("Timber", 120)], {
      fireHeadingWidths: { Timber: 320.125 }
    });
    const heading = page.row("Timber").querySelector(".fire-heading");
    const measurements = context.mock.method(page.document, "bounds");
    const styles = page.document.computedStyle(heading);
    assert.equal(styles.columnGap, "16px");
    assert.equal(styles.backgroundColor, "white");
    assert.equal(styles.padding, "13px 16px");
    assert.equal(styles.borderTop, "1px solid gray");
    assert.equal(measurements.mock.callCount(), 0);
    assert.equal(styles.width, "320.125px");
    page.document.fireHeadingWidths.set("Timber", 324.4375);
    assert.equal(styles.width, "324.4375px");
  });

test("browser visible rectangles measure only the target and respect hidden ancestors",
  async context => {
    const page = await viewer.page([viewer.update("Timber", 120)]);
    const row = page.row("Timber");
    const name = row.querySelector(".fire-name");
    const group = page.group(1);
    const following = page.group(2);
    const body = group.querySelector(".group-body");
    const list = group.querySelector(".updates");
    const sort = group.querySelector(".sort-order");
    const groupTop = group.getBoundingClientRect().top;
    const followingTop = following.getBoundingClientRect().top;
    const bodyHeight = body.getBoundingClientRect().height;

    body.hidden = true;
    assert.equal(following.getBoundingClientRect().top, followingTop - bodyHeight);
    body.hidden = false;
    group.hidden = true;
    assert.equal(following.getBoundingClientRect().top, groupTop);
    group.hidden = false;
    page.document.textWidths.set(sort.textContent, 1000);
    assert.equal(following.getBoundingClientRect().top, followingTop + 28);
    page.document.textWidths.delete(sort.textContent);
    page.document.headingWidths.set("1", 1200);
    assert.equal(group.getBoundingClientRect().width, 1200);
    page.document.headingWidths.delete("1");

    page.anchorGroup(1);
    assert.equal(following.getBoundingClientRect().top, followingTop - groupTop);
    page.anchorGroup(null);
    row.classList.remove("update");
    assert.equal(following.getBoundingClientRect().top, followingTop - (96 - 52));
    row.classList.add("update");
    following.querySelector(".updates").append(row);
    assert.equal(following.getBoundingClientRect().top, followingTop - 96);
    list.append(row);
    assert.equal(following.getBoundingClientRect().top, followingTop);
    list.textContent = "";
    assert.equal(following.getBoundingClientRect().top, followingTop - 96);
    list.append(row);
    assert.equal(following.getBoundingClientRect().top, followingTop);

    const expected = name.getBoundingClientRect();
    context.mock.method(page.document, "bounds", node => {
      assert.ok(node === name, "Only the requested rectangle needs measuring.");
      return expected;
    });
    assert.deepEqual(name.getClientRects(), [expected]);
    row.hidden = true;
    assert.deepEqual(name.getClientRects(), []);
    row.hidden = false;
    assert.deepEqual(name.getClientRects(), [expected]);
    row.remove();
    assert.deepEqual(name.getClientRects(), []);
  });
