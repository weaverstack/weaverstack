"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { load } = require("./renderer");
const { Element, document } = require("./dom");

function fixture(pageState = {}) {
  const doc = document(), frames = [];
  const root = { __WD_STATE: { orchestration: pageState }, addEventListener() {},
    requestAnimationFrame: (f) => frames.push(f), getComputedStyle: () => ({ overflowY: "visible", getPropertyValue: () => "" }) };
  const D = load(root, doc);
  function flush() { while (frames.length) frames.shift()(1000); }
  function table(name, cols, rows) { return D.TABLE + [name, ...cols].join(D.FIELD) + rows.map((r) => D.ROW + r.join(D.FIELD)).join(""); }
  const nodes = [
    ["a", "Warehouse/A", "HigherEducation", "Input", "Table", "HigherEducation.Input", 9, ""],
    ["b", "Warehouse/A", "Other", "Output", "Table", "Other.Output", 9, ""],
    ["c", "Warehouse/B", "HigherEducation", "Input", "Table", "HigherEducation.Input", 9, ""],
    ["d", "Warehouse/B", "Other", "Output", "Table", "Other.Output", 9, ""],
    ["e", "Warehouse/A", "Other", "Unrelated", "Table", "Other.Unrelated", 9, ""],
    ["f", "Warehouse/A", "Other", "Another", "Table", "Other.Another", 9, ""]
  ];
  const payload = table("page", ["name"], [["orchestration"]]) +
    table("nodes", ["key", "item", "schema", "object", "kind", "label", "flags", "description"], nodes) +
    table("edges", ["down", "up", "kind", "through", "reference"], [["b", "a", "Dependency", "", ""], ["c", "a", "Dependency", "", ""], ["d", "c", "Dependency", "", ""]]) +
    table("tables", ["item", "schema", "object", "type", "primarykey"], nodes.map((n) => [n[1], n[2], n[3], "Table", "Id"]));
  const p = D.parsePayload(payload), m = D.buildModel(p.tables, p.problems);
  return { D, m, root, doc, flush, body: new Element("div") };
}

test("ER pointer activation zooms without selecting, redrawing or calling onPick", () => {
  const { D, m, body, flush } = fixture();
  const s = {}, picks = [];
  D.ui.erWorkspace(body, m, s, { onPick: (id) => picks.push(id) }); flush();
  const before = JSON.parse(JSON.stringify(s)), boxes = body.querySelectorAll(".wd-er-box");
  const box = boxes[0], svg = body.querySelector("svg");
  box.fire("pointerdown"); box.fire("pointerup", { shiftKey: true }); flush();
  assert.deepEqual(s.selection, before.selection, "node click must not change selection");
  assert.deepEqual(s.patterns, before.patterns);
  assert.deepEqual(s.expanded, before.expanded);
  assert.deepEqual(s.moved, before.moved);
  assert.deepEqual(picks, []);
  assert.equal(body.querySelector("svg"), svg, "zoom must preserve diagram and edges");
  assert.equal(body.querySelectorAll(".wd-er-box").length, boxes.length);
  assert.ok(s.view.k > before.view.k, "click zooms toward the activated node");
});

function graph(s, items) {
  const env = fixture(s), { D, m, root, body } = env;
  // Canvas paint is outside these state/window tests; keep the real view geometry.
  root.requestAnimationFrame = undefined;
  D.ui.GraphView.prototype.draw = function () {};
  const setWindow = D.ui.GraphView.prototype.setWindow;
  D.ui.GraphView.prototype.setWindow = function (win, lay) {
    env.win = win; env.layout = lay; return setWindow.call(this, win, lay);
  };
  env.controller = D.ui.graphWorkspace(body, m, { page: "orchestration", items, mode: "kind" });
  return env;
}

test("orchestration item scope bounds wildcard inputs and their expanded impact", () => {
  const env = graph({ patterns: ["HigherEducation.*"], up: -1, down: -1 }, ["Warehouse/A"]);
  assert.deepEqual([...env.win.seeds], ["a"], "same keyword in another item is not an input");
  assert.deepEqual([...env.win.shown].sort(), ["a", "b"], "impact outside the keyword stays, outside the item does not");
  assert.deepEqual([...env.layout.pos.keys()].sort(), ["a", "b"]);
  assert.deepEqual(env.win.edges.map((e) => [e.u, e.d]), [["a", "b"]]);
});

test("orchestration markers and saved expansions cannot reveal another item", () => {
  const env = graph({ patterns: ["HigherEducation.*"], expanded: ["c", "e"], up: 0, down: 1 }, ["Warehouse/A"]);
  assert.deepEqual([...env.win.shown].sort(), ["a", "b", "e"]);
  for (const more of env.win.more.values()) {
    assert.ok([...more.up, ...more.down].every((k) => env.m.nodes.get(k).item === "Warehouse/A"));
  }
});

test("orchestration rejects saved and newly picked inputs outside the selected item", () => {
  const s = { selection: ["a", "c"], focus: "c", scope: "Warehouse/A", up: -1, down: -1 };
  const env = graph(s, ["Warehouse/A"]);
  assert.deepEqual(s.selection, ["a"]);
  assert.equal(s.focus, "a");
  env.controller.select("c");
  assert.deepEqual(s.selection, ["a"]);
  assert.deepEqual([...env.win.shown].sort(), ["a", "b"]);
});

test("a wildcard with no in-item matches cannot fall back to the estate", () => {
  const s = { patterns: ["DoesNotExist.*"], up: -1, down: -1 };
  const env = graph(s, ["Warehouse/A"]);
  assert.deepEqual([...env.win.shown], []);
  assert.ok(Object.values(s.view).every(Number.isFinite));
});

for (const items of [["Warehouse/A", "Warehouse/B"], null]) {
  test("orchestration keeps cross-item impact when both items are allowed: " + JSON.stringify(items), () => {
    const env = graph({ patterns: ["HigherEducation.*"], up: -1, down: -1 }, items);
    assert.deepEqual([...env.win.seeds].sort(), ["a", "c"]);
    assert.deepEqual([...env.win.shown].sort(), ["a", "b", "c", "d"]);
  });
}

test("without keywords the selected item stays whole, including isolated nodes", () => {
  const env = graph({}, ["Warehouse/A"]);
  assert.deepEqual([...env.win.shown].sort(), ["a", "b", "e", "f"]);
  assert.equal(env.win.hidden, 0);
  assert.ok(!env.win.truncated);
});

for (const scope of [undefined, "Warehouse/A"]) {
  test("initial and remembered scope both prune foreign selection: " + scope, () => {
    const s = { scope, selection: ["c"] };
    graph(s, ["Warehouse/A"]);
    assert.deepEqual(s.selection, []);
    assert.equal(s.focus, null);
  });
}

test("an empty item set draws no objects and retains a finite viewport", () => {
  const s = {};
  const env = graph(s, []);
  assert.deepEqual([...env.win.shown], []);
  assert.ok(Object.values(s.view).every(Number.isFinite));
});

test("ER Enter zooms without replacing an existing selection or detail", () => {
  const { D, m, body, flush } = fixture();
  const s = {}, picks = [], controller = D.ui.erWorkspace(body, m, s, { onPick: (id) => picks.push(id) });
  controller.select("Warehouse/A|HigherEducation|Input"); flush();
  s.view = { k: 0.3, x: 0, y: 0 };
  const selection = s.selection.slice(), svg = body.querySelector("svg"), view = { ...s.view };
  const boxes = body.querySelectorAll(".wd-er-box");
  boxes[boxes.length - 1].fire("keydown", { key: "Enter", ctrlKey: true });
  assert.deepEqual(s.selection, selection);
  assert.deepEqual(picks, []);
  assert.equal(body.querySelector("svg"), svg);
  assert.notDeepEqual(s.view, view);
});

test("ER dragging moves a box but neither selects nor zooms, and cancellation does nothing", () => {
  const { D, m, body, flush } = fixture(), s = {};
  D.ui.erWorkspace(body, m, s, {}); flush();
  const box = body.querySelector(".wd-er-box"), view = { ...s.view };
  box.fire("pointerdown"); box.fire("pointermove", { clientX: 20, clientY: 10 }); box.fire("pointerup", { clientX: 20, clientY: 10 });
  assert.equal(Object.keys(s.moved).length, 1);
  assert.deepEqual(s.view, view);
  assert.deepEqual(s.selection, []);
  box.fire("pointerdown"); box.fire("pointercancel"); box.fire("pointerup");
  assert.deepEqual(s.view, view);
  assert.deepEqual(s.selection, []);
});
