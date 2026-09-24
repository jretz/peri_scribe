import assert from "node:assert/strict";
import test from "node:test";

import * as viewer from "../../../helpers/doubles/peri_scribe/updates_page.mjs";

test("loadUpdates checks HEAD every thirty seconds", async () => {
    const page = await viewer.page(viewer.snapshot(), {
        ETag: '"content-hash"',
    });

    assert.equal(page.interval, 30000);
    await page.advance(29999);
    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET"],
    );
    await page.advance(1);
    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET", "HEAD"],
    );
    await page.advance(30000);
    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET", "HEAD", "HEAD"],
    );
});

test("loadUpdates recovers a same-second equal-length metadata collision", async () => {
    const original = viewer.snapshot();
    const replacement = viewer.snapshot(2000, 900);
    assert.equal(
        JSON.stringify(original).length,
        JSON.stringify(replacement).length,
    );
    const headers = {
        "Last-Modified": "Wed, 23 Sep 2026 00:00:00 GMT",
        "Content-Length": String(JSON.stringify(original).length),
    };
    const page = await viewer.page(original, headers);
    page.setSnapshot(replacement);

    await page.tick();
    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET", "HEAD"],
    );
    await page.advance(5 * 60000 - page.interval - 1);
    assert.equal(page.calls.filter((call) => call.method === "GET").length, 1);
    await page.advance(1);

    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
    assert.equal(page.calls.at(-1).method, "GET");
    assert.equal(page.errors.length, 0);
});

test("loadUpdates keeps strong ETags beyond metadata rechecks", async () => {
    const page = await viewer.page(viewer.snapshot(), {
        ETag: '"content-hash"',
    });

    await page.advance(30 * 60000);

    assert.equal(page.calls.filter((call) => call.method === "GET").length, 1);
    assert.equal(page.rendered.length, 1);
});

test("loadUpdates bounds the lifetime of an unchanged weak ETag", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: 'W/"metadata"' });
    page.setSnapshot(viewer.snapshot(2000));

    await page.advance(5 * 60000);

    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates rechecks weak validators even with a 304 HEAD", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: 'W/"metadata"' });
    page.setSnapshot(viewer.snapshot(2000));
    page.setHeadStatus(304);

    await page.advance(5 * 60000);

    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates retains a strong validator with a 304 HEAD", async () => {
    const page = await viewer.page(viewer.snapshot(), {
        ETag: '"content-hash"',
    });
    page.setHeadStatus(304);

    await page.advance(5 * 60000);

    assert.equal(page.calls.filter((call) => call.method === "GET").length, 1);
});

test("loadUpdates fetches a changed validator on the next check", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });

    await page.tick();

    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET", "HEAD", "GET"],
    );
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates retries failed downloads after weak metadata expires", async () => {
    const headers = { "Last-Modified": "same second", "Content-Length": "400" };
    const page = await viewer.page(viewer.snapshot(), headers);
    page.setSnapshot(viewer.snapshot(2000), headers, 503);

    await page.advance(5 * 60000);
    assert.equal(page.errors.length, 1);
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 1000);
    page.setSnapshot(viewer.snapshot(2000));
    await page.tick();

    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

for (const status of [405, 501]) {
    test(`loadUpdates downloads when HEAD is unsupported with ${status}`, async () => {
        const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
        page.setHeadStatus(status);
        page.setSnapshot(viewer.snapshot(2000));

        await page.tick();

        assert.deepEqual(
            page.calls.map((call) => call.method),
            ["GET", "HEAD", "GET"],
        );
        assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
        assert.equal(page.errors.length, 0);
    });
}

test("loadUpdates preserves displayed data after an unsuccessful HEAD", async () => {
    const page = await viewer.page(viewer.snapshot());
    page.setHeadStatus(503);
    page.setSnapshot(viewer.snapshot(2000));

    await page.tick();

    assert.equal(page.rendered.length, 1);
    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET", "HEAD"],
    );
    assert.equal(page.errors[0].message, "HEAD HTTP 503");
    assert.equal(page.status.hidden, true);
    assert.equal(page.status.getAttribute("role"), undefined);
    page.setHeadStatus(200);
    await page.tick();
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
    const page = await viewer.page(
        viewer.snapshot(),
        {},
        { requestError: failure },
    );

    assert.equal(page.errors[0], failure);
    assert.equal(page.rendered.length, 0);
    page.setRequestError(undefined);
    await page.tick();
    assert.equal(page.rendered.length, 1);
    assert.equal(page.status.hidden, true);
});

test("loadUpdates preserves displayed data when response JSON is invalid", async () => {
    const page = await viewer.page(viewer.snapshot());
    const failure = new SyntaxError("Incomplete JSON");
    page.setJsonError(failure);

    await page.tick();

    assert.equal(page.errors[0], failure);
    assert.equal(page.rendered.length, 1);
    assert.equal(page.status.hidden, true);
    page.setJsonError(undefined);
    page.setSnapshot(viewer.snapshot(2000));
    await page.tick();
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates does not overlap requests during a slow response", async () => {
    const page = await viewer.page(viewer.snapshot(), { ETag: '"first"' });
    page.setSnapshot(viewer.snapshot(2000), { ETag: '"second"' });
    const held = page.holdNextRequest();
    const pendingTick = page.tick();
    await held.started;

    await page.tick();

    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET", "HEAD"],
    );
    assert.equal(page.rendered.length, 1);
    held.release();
    await pendingTick;
    assert.deepEqual(
        page.calls.map((call) => call.method),
        ["GET", "HEAD", "GET"],
    );
    assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
});

test("loadUpdates asks the browser to bypass its cache and bound request waits", async () => {
    const page = await viewer.page(viewer.snapshot());

    await page.tick();

    for (const call of page.calls) {
        assert.equal(call.url, "./updates.json");
        assert.equal(call.cache, "no-store");
        assert.ok(call.signal instanceof AbortSignal);
        assert.equal(call.signal.aborted, false);
    }
});

const metadata = {
    "Last-Modified": "Wed, 23 Sep 2026 00:00:00 GMT",
    "Content-Length": "400",
};
for (const [description, before, after] of [
    ["no validators are provided", {}, {}],
    ["a strong ETag appears", {}, { ETag: '"new"' }],
    ["a strong ETag disappears", { ETag: '"old"' }, {}],
    ["last-modified was absent", { "Content-Length": "400" }, metadata],
    ["last-modified disappears", metadata, { "Content-Length": "400" }],
    [
        "content-length was absent",
        { "Last-Modified": metadata["Last-Modified"] },
        metadata,
    ],
    [
        "content-length disappears",
        metadata,
        { "Last-Modified": metadata["Last-Modified"] },
    ],
    [
        "last-modified changes",
        metadata,
        { ...metadata, "Last-Modified": "Wed, 23 Sep 2026 00:00:01 GMT" },
    ],
    [
        "content-length changes",
        metadata,
        { ...metadata, "Content-Length": "401" },
    ],
]) {
    test(`loadUpdates downloads when ${description}`, async () => {
        const page = await viewer.page(viewer.snapshot(), before);
        page.setSnapshot(viewer.snapshot(2000), after);

        await page.tick();

        assert.deepEqual(
            page.calls.map((call) => call.method),
            ["GET", "HEAD", "GET"],
        );
        assert.equal(page.rendered.at(-1).updates[0].mapped_area.value, 2000);
    });
}

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
    ["invalid location", (record) => ({ ...record, location: 123 })],
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
    test(`validateSnapshot accepts log identity ${JSON.stringify(identity)}`, async () => {
        const data = viewer.snapshot();
        data.updates[0].log_identity = identity;

        const page = await viewer.page(data);

        assert.deepEqual(page.rendered, [data]);
        assert.equal(page.errors.length, 0);
    });
}

test("validateSnapshot accepts an empty update history", async () => {
    const data = { ...viewer.snapshot(), updates: [] };

    const page = await viewer.page(data);

    assert.deepEqual(page.rendered, [data]);
    assert.equal(page.errors.length, 0);
});
