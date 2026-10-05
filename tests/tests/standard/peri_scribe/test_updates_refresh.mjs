import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_page.mjs";

test("loadUpdates sends one conditional GET every thirty seconds", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"content-hash"' });

    assert.equal(page.interval, 30000);
    assert.equal(new Headers(page.calls[0].headers).get("If-None-Match"), null);
    await page.advance(29999);
    assert.equal(page.calls.length, 1);
    await page.advance(1);
    assert.equal(page.calls.length, 2);
    await page.advance(30000);

    assert.deepEqual(page.calls.map((call) => call.method), ["GET", "GET", "GET"]);
    for (const call of page.calls.slice(1)) {
        assert.equal(new Headers(call.headers).get("If-None-Match"), '"content-hash"');
    }
});

test("loadUpdates retains displayed data without reading a 304 body", async () => {
    const original = viewer.snapshot();
    const page = await viewer.page(original, { ETag: '"unchanged"' });
    page.setSnapshot(viewer.snapshot(2000));

    await page.tick();

    assert.deepEqual(page.rendered, [original]);
    assert.equal(page.jsonCalls.length, 1);
    assert.equal(page.errors.length, 0);
});

test("loadUpdates keeps its validator when a 304 supplies another ETag", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"unexpected"' }, 304);
    await page.tick();

    await page.tick();

    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"first"');
    assert.equal(page.rendered.length, 1);
    assert.equal(page.jsonCalls.length, 1);
});

test("loadUpdates keeps strong ETags beyond weak validator rechecks", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"content-hash"' });

    await page.advance(30 * 60000);

    assert.equal(page.calls.length, 61);
    assert.ok(page.calls.slice(1).every((call) =>
        new Headers(call.headers).get("If-None-Match") === '"content-hash"'));
    assert.equal(page.jsonCalls.length, 1);
    assert.equal(page.rendered.length, 1);
});

test("loadUpdates bounds the lifetime of an unchanged weak ETag", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: 'W/"metadata"' });
    page.setSnapshot(viewer.snapshot(2000));

    await page.advance(5 * 60000 - 1);
    assert.equal(page.rendered.length, 1);
    assert.ok(page.calls.slice(1).every((call) =>
        new Headers(call.headers).get("If-None-Match") === 'W/"metadata"'));
    await page.advance(1);

    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
    assert.equal(page.calls.length, 11);
    assert.equal(new Headers(page.calls.at(-1).headers).get("If-None-Match"), null);
    assert.equal(page.jsonCalls.length, 2);
    await page.tick();
    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), 'W/"metadata"');
});

test("loadUpdates fetches a changed validator on the next check", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });

    await page.tick();

    assert.deepEqual(page.calls.map((call) => call.method), ["GET", "GET"]);
    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"first"');
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
    await page.tick();
    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"second"');
    assert.equal(page.rendered.length, 2);
});

test("loadUpdates consumes a 200 body even when its ETag is unchanged", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"unchanged"' });
    page.setIgnoreConditional(true);
    page.setSnapshot(viewer.snapshot(2000));

    await page.tick();

    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"unchanged"');
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
    assert.equal(page.jsonCalls.length, 2);
});

test("loadUpdates clears its validator when a download omits ETag", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(viewer.snapshot(2000), {});
    await page.tick();
    page.setSnapshot(viewer.snapshot(3000), {});

    await page.tick();

    assert.equal(new Headers(page.calls.at(-1).headers).get("If-None-Match"), null);
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 3000);
});

for (const headers of [{}, {
    "Last-Modified": "Wed, 23 Sep 2026 00:00:00 GMT",
    "Content-Length": "400",
}]) {
    test(`loadUpdates downloads each interval without ETag: ${JSON.stringify(headers)}`,
        async () => {
            const page = await viewer.page(viewer.snapshot(), headers);
            page.setSnapshot(viewer.snapshot(2000));

            await page.tick();
            await page.tick();

            assert.deepEqual(
                page.calls.map((call) => call.method), ["GET", "GET", "GET"]);
            assert.ok(page.calls.every((call) =>
                new Headers(call.headers).get("If-None-Match") === null));
            assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
            assert.equal(page.jsonCalls.length, 3);
        });
}

test("loadUpdates adopts a validator when a download gains ETag", async () => {
    const page = await viewer.page(viewer.snapshot());
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"new"' });
    await page.tick();

    await page.tick();

    assert.equal(new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"new"');
    assert.equal(page.rendered.length, 2);
});

test("loadUpdates retries failures after a weak validator expires", async () => {
    const headers = { ETag: 'W/"metadata"' };
    const page = await viewer.page(viewer.snapshot(), headers);
    await page.advance(5 * 60000 - page.interval);
    page.setSnapshot(viewer.snapshot(2000), headers, 503);

    await page.tick();
    assert.equal(page.errors.length, 1);
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 1000);
    page.setSnapshot(viewer.snapshot(2000));
    await page.tick();

    assert.equal(new Headers(page.calls.at(-1).headers).get("If-None-Match"), null);
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates rejects an unsolicited 304 before the first download", async () => {
    const page = await viewer.page(
        viewer.snapshot(), { ETag: '"first"' }, { status: 304 });

    assert.equal(page.rendered.length, 0);
    assert.equal(page.jsonCalls.length, 0);
    assert.equal(page.errors[0].message, "HTTP 304");
    assert.equal(page.status.getAttribute("role"), "alert");
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });
    await page.tick();
    assert.equal(new Headers(page.calls.at(-1).headers).get("If-None-Match"), null);
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates rejects unsolicited 304 after a weak validator expires", async () => {
    const headers = { ETag: 'W/"metadata"' };
    const page = await viewer.page(viewer.snapshot(), headers);
    page.setSnapshot(viewer.snapshot(2000), headers, 304);

    await page.advance(5 * 60000);

    assert.equal(page.rendered.length, 1);
    assert.equal(page.errors[0].message, "HTTP 304");
    assert.equal(new Headers(page.calls.at(-1).headers).get("If-None-Match"), null);
    page.setSnapshot(viewer.snapshot(2000));
    await page.tick();
    assert.equal(new Headers(page.calls.at(-1).headers).get("If-None-Match"), null);
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates preserves displayed data and ETag after an HTTP error", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"failed"' }, 503);

    await page.tick();

    assert.equal(page.rendered.length, 1);
    assert.equal(page.errors[0].message, "HTTP 503");
    assert.equal(page.status.hidden, true);
    assert.equal(page.status.getAttribute("role"), undefined);
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });
    await page.tick();
    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"first"');
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates retries after an initial download fails", async () => {
    const page = await viewer.page(viewer.snapshot(), {}, { status: 503 });

    assert.equal(page.rendered.length, 0);
    assert.equal(page.status.hidden, false);
    assert.equal(page.status.getAttribute("role"), "alert");
    assert.equal(page.status.textContent, "Unable to load updates.json.");
    assert.equal(page.errors[0].message, "HTTP 503");
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"recovered"' });
    await page.tick();
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
    assert.equal(page.status.hidden, true);
});

test("loadUpdates recovers from a network exception", async () => {
    const failure = new TypeError("Connection unavailable");
    const page = await viewer.page(viewer.snapshot(), {}, { requestError: failure });

    assert.equal(page.errors[0], failure);
    assert.equal(page.rendered.length, 0);
    page.setRequestError(undefined);
    await page.tick();
    assert.equal(page.rendered.length, 1);
    assert.equal(page.status.hidden, true);
});

test("loadUpdates preserves displayed data and ETag when JSON is invalid", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    const failure = new SyntaxError("Incomplete JSON");
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });
    page.setJsonError(failure);

    await page.tick();

    assert.equal(page.errors[0], failure);
    assert.equal(page.rendered.length, 1);
    assert.equal(page.status.hidden, true);
    page.setJsonError(undefined);
    await page.tick();
    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"first"');
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates preserves its validator when snapshot validation fails", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(null, { ETag: '"second"' });
    await page.tick();
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });

    await page.tick();

    assert.equal(
        new Headers(page.calls.at(-1).headers).get("If-None-Match"), '"first"');
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates does not overlap requests during a slow response", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });
    const held = page.holdNextRequest();
    const pendingTick = page.tick();
    await held.started;

    await page.tick();

    assert.deepEqual(page.calls.map((call) => call.method), ["GET", "GET"]);
    assert.equal(page.rendered.length, 1);
    held.release();
    await pendingTick;
    assert.equal(page.calls.length, 2);
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates bypasses the browser cache and bounds request waits", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });

    await page.tick();

    for (const call of page.calls) {
        assert.equal(call.url, "./updates.json");
        assert.equal(call.cache, "no-store");
        assert.ok(call.signal instanceof AbortSignal);
    }
    assert.equal(page.calls.at(-1).signal.aborted, false);
    assert.ok(page.requestTimeouts.every((milliseconds) => milliseconds === 15000));
});

for (const [description, change] of [
    ["null snapshot", () => null],
    ["unsupported version", (data) => ({ ...data, version: 2 })],
    ["non-string generation time", (data) => ({ ...data, generated_at: 123 })],
    [
        "invalid generation time",
        (data) => ({ ...data, generated_at: "not a date" }),
    ],
    ["non-array updates", (data) => ({ ...data, updates: {} })],
]) {
    test(`validateSnapshot rejects ${description} before rendering`, async () => {
        const page = await viewer.page(change(viewer.snapshot()));

        assert.equal(page.rendered.length, 0);
        assert.equal(page.errors[0].message, "Invalid update snapshot.");
        assert.equal(page.status.getAttribute("role"), "alert");
    });
}

for (const [description, change] of [
    ["null record", () => null],
    ["non-string name", (record) => ({ ...record, name: 123 })],
    ["invalid identifier", (record) => ({ ...record, identifier: 123 })],
    ["non-array log identity", (record) => ({ ...record, log_identity: {} })],
    [
        "incomplete log identity",
        (record) => ({ ...record, log_identity: ["name"] }),
    ],
    [
        "invalid log identity kind",
        (record) => ({
            ...record,
            log_identity: ["location", "Timber"],
        }),
    ],
    [
        "non-string log identity",
        (record) => ({ ...record, log_identity: ["name", 123] }),
    ],
    ["non-array history identity", (record) => ({ ...record, history_identity: {} })],
    [
        "incomplete history identity",
        (record) => ({ ...record, history_identity: ["local"] }),
    ],
    [
        "invalid history identity kind",
        (record) => ({ ...record, history_identity: ["location", "Timber"] }),
    ],
    [
        "non-string history identity",
        (record) => ({ ...record, history_identity: ["local", 123] }),
    ],
    ["invalid location", (record) => ({ ...record, location: 123 })],
    ["non-string preview", (record) => ({ ...record, preview: 123 })],
    ["external preview", (record) => ({ ...record, preview: "https://example.com/image.webp" })],
    ["non-WebP preview", (record) => ({ ...record, preview: "data:image/png;base64,AAAA" })],
    ["empty preview", (record) => ({ ...record, preview: "data:image/webp;base64," })],
    ["non-string timestamp", (record) => ({ ...record, timestamp: 123 })],
    ["invalid timestamp", (record) => ({ ...record, timestamp: "not a date" })],
    ["missing acreage", (record) => ({ ...record, mapped_area: null })],
    [
        "wrong acreage units",
        (record) => ({
            ...record,
            mapped_area: { value: 123, units: "hectare" },
        }),
    ],
    [
        "non-numeric acreage",
        (record) => ({
            ...record,
            mapped_area: { value: "123", units: "acre" },
        }),
    ],
    [
        "non-finite acreage",
        (record) => ({
            ...record,
            mapped_area: { value: Infinity, units: "acre" },
        }),
    ],
    [
        "negative acreage",
        (record) => ({
            ...record,
            mapped_area: { value: -123, units: "acre" },
        }),
    ],
    [
        "invalid previous acreage",
        (record) => ({
            ...record,
            previous_mapped_area: { value: -123, units: "acre" },
        }),
    ],
]) {
    test(`validateSnapshot rejects ${description} without replacing data`, async () => {
        const page = await viewer.page(viewer.snapshot());
        const replacement = viewer.snapshot(2000);
        replacement.updates[0] = change(replacement.updates[0]);
        page.setSnapshot(replacement);

        await page.tick();

        assert.equal(page.rendered.length, 1);
        assert.equal(page.errors[0].message, "Invalid fire update.");
        assert.equal(page.status.hidden, true);
    });
}

test("validateSnapshot accepts missing incident metadata and a zero acreage baseline", async () => {
    const data = viewer.snapshot();
    data.updates[0].identifier = null;
    data.updates[0].location = null;
    data.updates[0].previous_mapped_area = { value: 0, units: "acre" };

    const page = await viewer.page(data);

    assert.deepEqual(page.rendered, [data]);
    assert.equal(page.errors.length, 0);
});

for (const identity of [
    null,
    ["id", "2026-timber"],
    ["name", "Timber"],
    ["local", "new-timber"],
]) {
    for (const field of ["log_identity", "history_identity"]) {
        test(`validateSnapshot accepts ${field} ${JSON.stringify(identity)}`, async () => {
            const data = viewer.snapshot();
            data.updates[0][field] = identity;

            const page = await viewer.page(data);

            assert.deepEqual(page.rendered, [data]);
            assert.equal(page.errors.length, 0);
        });
    }
}

test("validateSnapshot accepts an empty update history", async () => {
    const data = { ...viewer.snapshot(), updates: [] };

    const page = await viewer.page(data);

    assert.deepEqual(page.rendered, [data]);
    assert.equal(page.errors.length, 0);
});
