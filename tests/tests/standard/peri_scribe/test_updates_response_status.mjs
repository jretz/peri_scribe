import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_page.mjs";

test("createResponseMonitor waits two intervals after the last response", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"unchanged"' });
    await page.tick();
    page.setRequestError(new TypeError("Connection unavailable"));

    await page.advance(2 * page.interval - 1);
    assert.equal(page.responseStatus.hidden, true);
    await page.advance(1);

    assert.equal(page.responseStatus.hidden, false);
    assert.equal(
        page.responseStatus.textContent,
        "No response from updates server since Sep 23, 5:00:30 AM PDT.",
    );
    assert.equal(page.rendered.length, 1);
});

test("createResponseMonitor retains response time throughout an outage", async () => {
    const page = await viewer.page(viewer.snapshot());
    page.setRequestError(new TypeError("Connection unavailable"));

    await page.advance(6 * page.interval);

    assert.equal(page.responseStatus.hidden, false);
    assert.equal(
        page.responseStatus.textContent,
        "No response from updates server since Sep 23, 5:00:00 AM PDT.",
    );
});

test("createResponseMonitor uses opening time before the first response", async () => {
    const page = await viewer.page(viewer.snapshot(), {}, {
        requestError: new TypeError("Connection unavailable"),
    });

    await page.advance(2 * page.interval - 1);
    assert.equal(page.responseStatus.hidden, true);
    await page.advance(1);

    assert.equal(page.responseStatus.hidden, false);
    assert.equal(
        page.responseStatus.textContent,
        "No response from updates server since this page opened at " +
            "Sep 23, 5:00:00 AM PDT.",
    );
    assert.equal(page.status.textContent, "Unable to load updates.json.");
});

for (const headStatus of [200, 304]) {
    test(`createResponseMonitor recovers on unchanged HEAD ${headStatus}`, async () => {
        const page = await viewer.page(viewer.snapshot(), { ETag: '"unchanged"' });
        page.setRequestError(new TypeError("Connection unavailable"));
        await page.advance(2 * page.interval);
        assert.equal(page.responseStatus.hidden, false);
        page.setRequestError(undefined);
        page.setHeadStatus(headStatus);

        await page.tick();

        assert.equal(page.responseStatus.hidden, true);
        assert.equal(page.calls.filter((call) => call.method === "GET").length, 1);
        page.setRequestError(new TypeError("Connection unavailable"));
        await page.advance(2 * page.interval - 1);
        assert.equal(page.responseStatus.hidden, true);
        await page.advance(1);
        assert.equal(page.responseStatus.hidden, false);
        assert.equal(
            page.responseStatus.textContent,
            "No response from updates server since Sep 23, 5:01:30 AM PDT.",
        );
    });
}

test("createResponseMonitor clears a warning on HTTP HEAD errors", async () => {
    const page = await viewer.page(viewer.snapshot());
    page.setRequestError(new TypeError("Connection unavailable"));
    await page.advance(2 * page.interval);
    assert.equal(page.responseStatus.hidden, false);
    page.setRequestError(undefined);
    page.setHeadStatus(503);

    await page.tick();

    assert.equal(page.responseStatus.hidden, true);
    assert.equal(page.errors.at(-1).message, "HEAD HTTP 503");
    assert.equal(page.rendered.length, 1);
});

for (const [description, snapshot, response] of [
    ["an HTTP error", viewer.snapshot(), { status: 503 }],
    ["invalid JSON", viewer.snapshot(), { jsonError: new SyntaxError("Invalid JSON") }],
    ["an invalid snapshot", null, {}],
]) {
    test(`createResponseMonitor records GET headers with ${description}`, async () => {
        const page = await viewer.page(snapshot, {}, response);
        page.setRequestError(new TypeError("Connection unavailable"));

        await page.advance(2 * page.interval);

        assert.equal(page.responseStatus.hidden, false);
        assert.equal(
            page.responseStatus.textContent,
            "No response from updates server since Sep 23, 5:00:00 AM PDT.",
        );
        assert.equal(page.rendered.length, 0);
    });
}

test("createResponseMonitor warns while a request is still pending", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"unchanged"' });
    const held = page.holdNextRequest();
    const pending = page.tick();
    await held.started;

    await page.advance(page.interval - 1);
    assert.equal(page.responseStatus.hidden, true);
    await page.advance(1);

    assert.equal(page.responseStatus.hidden, false);
    assert.equal(page.calls.length, 2);
    held.release();
    await pending;
    assert.equal(page.responseStatus.hidden, true);
});

test("createResponseMonitor ignores request timeouts", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"unchanged"' });
    const first = page.holdNextRequest({ respectTimeout: true });
    await page.advance(page.interval, { waitForRequests: false });
    await first.started;
    await page.advance(15000, { waitForRequests: false });
    assert.equal(page.errors.at(-1).name, "TimeoutError");
    assert.equal(page.responseStatus.hidden, true);
    const second = page.holdNextRequest({ respectTimeout: true });

    await page.advance(15000, { waitForRequests: false });
    await second.started;

    assert.equal(page.responseStatus.hidden, false);
    assert.equal(
        page.responseStatus.textContent,
        "No response from updates server since Sep 23, 5:00:00 AM PDT.",
    );
    await page.advance(15000, { waitForRequests: false });
    assert.equal(page.errors.length, 2);
    assert.ok(page.errors.every((error) => error.name === "TimeoutError"));
    assert.equal(page.responseStatus.hidden, false);
});
