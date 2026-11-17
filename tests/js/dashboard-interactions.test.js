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

test("ER pointer activation opens details without changing the graph selection or drawing", () => {
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
  assert.deepEqual(picks, ["Warehouse/A|HigherEducation|Input"]);
  assert.equal(body.querySelector("svg"), svg, "activation must preserve diagram and edges");
  assert.equal(body.querySelectorAll(".wd-er-box").length, boxes.length);
  assert.ok(s.view.k > before.view.k, "click zooms toward the activated node");
});

function graph(s, items, configure) {
  const env = fixture(s), { D, m, root, body } = env;
  if (configure) configure(m);
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

test("out-of-scope detail dependencies and mirror references are readable but not interactive", () => {
  const s = { selection: ["a"], focus: "a" };
  const env = graph(s, ["Warehouse/A"], (m) => {
    const a = m.nodes.get("a"), c = m.nodes.get("c"), d = m.nodes.get("d");
    a.vup.push(c.key);
    a.vdown.push(d.key); d.kind = "Assumption";
    a.original = c; a.copies = [d];
  });
  const side = env.body.querySelector(".wd-side");
  const references = side.querySelectorAll("button").concat(side.querySelectorAll("span"))
    .filter((e) => (e.getAttribute("title") || "").startsWith(env.D.shownItem("Warehouse/B") + " · "));
  assert.equal(references.length, 5, "Reads, Read by, validation, source and mirror-copy references remain visible");
  for (const reference of references) {
    assert.equal(reference.tagName, "span", "outside references must not present a dead button");
    assert.equal(reference.onclick, undefined);
    assert.equal(reference.getAttribute("tabindex"), null);
  }
  const local = side.querySelectorAll("button").find((e) => e.textContent.includes("Other.Output"));
  assert.ok(local, "in-scope dependencies remain interactive");
  local.fire("click");
  assert.deepEqual(s.selection, ["b"]);
  assert.ok([...env.win.shown].every((k) => env.m.nodes.get(k).item === "Warehouse/A"));
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

for (const k of [0.8, 2.2]) {
  for (const activation of ["pointer", "Enter"]) {
    test(`ER ${activation} at readable scale ${k} changes details without moving the viewport`, () => {
      const { D, m, body, flush } = fixture(), s = {}, picks = [];
      D.ui.erWorkspace(body, m, s, { onPick: (id) => picks.push(id) }); flush();
      s.view = { k, x: 123, y: -45 };
      const view = { ...s.view }, svg = body.querySelector("svg"), boxes = body.querySelectorAll(".wd-er-box");
      for (const box of [boxes[0], boxes[1], boxes[1]]) {
        if (activation === "Enter") box.fire("keydown", { key: "Enter" });
        else { box.fire("pointerdown"); box.fire("pointerup"); }
        assert.deepEqual(s.view, view, "readable and manually panned views must stay exact");
        assert.equal(body.querySelector("svg"), svg);
      }
      assert.deepEqual(picks, ["Warehouse/A|HigherEducation|Input", "Warehouse/B|HigherEducation|Input", "Warehouse/B|HigherEducation|Input"]);
      assert.deepEqual(s.selection, [], "detail focus must not filter or rebuild the diagram");
    });
  }
}

test("ER activation zooms once from an overview, then preserves the viewport on a narrow screen", () => {
  const { D, m, body, flush } = fixture(), s = {};
  D.ui.erWorkspace(body, m, s, {});
  const svg = body.querySelector("svg");
  svg.getBoundingClientRect = () => ({ width: 360, height: 280 });
  flush();
  const before = { ...s.view }, boxes = body.querySelectorAll(".wd-er-box");
  boxes[0].fire("pointerdown"); boxes[0].fire("pointerup");
  assert.ok(s.view.k > before.k);
  assert.ok(s.view.k < 0.8, "a narrow viewport cannot reach desktop reading scale");
  const view = { ...s.view };
  for (const box of [boxes[0], boxes[1]]) {
    box.fire("pointerdown"); box.fire("pointerup");
    assert.deepEqual(s.view, view, "a viewport-limited focus must not jump on the next activation");
  }
});

test("ER narrow-screen activation stays stable between unequal-height boxes and can refocus after zooming out", () => {
  const { D, m, body, flush } = fixture(), s = { columns: true };
  m.tables.columns = Array.from({ length: 8 }, (_, i) => ({ item: "Warehouse/A", schema: "HigherEducation", object: "Input", column: "Column" + i }));
  D.ui.erWorkspace(body, m, s, {});
  const svg = body.querySelector("svg");
  svg.getBoundingClientRect = () => ({ width: 360, height: 280 });
  flush();
  const boxes = body.querySelectorAll(".wd-er-box"), tall = boxes[0], compact = boxes[1];
  assert.notEqual(tall.querySelector("rect").getAttribute("height"), compact.querySelector("rect").getAttribute("height"));
  tall.fire("keydown", { key: "Enter" });
  const focused = { ...s.view };
  compact.fire("keydown", { key: "Enter" });
  assert.deepEqual(s.view, focused, "the readable threshold must not depend on the next node's height");
  body.querySelectorAll("button").find((b) => b.getAttribute("title") === "Zoom out").fire("click");
  const overview = { ...s.view };
  tall.fire("keydown", { key: "Enter" });
  assert.ok(s.view.k > overview.k, "manual zoom-out must allow another focus zoom");
  assert.deepEqual(s.view, focused);
  assert.equal(body.querySelector("svg"), svg);
});

test("ER details focus highlights the activated node without replacing graph seeds", () => {
  const { D, m, body, flush } = fixture(), s = {};
  D.ui.erWorkspace(body, m, s, {}); flush();
  const boxes = body.querySelectorAll(".wd-er-box");
  boxes[0].fire("pointerdown"); boxes[0].fire("pointerup");
  assert.equal(s.focus, "Warehouse/A|HigherEducation|Input");
  assert.ok(boxes[0].classList.contains("wd-er-box-current"));
  boxes[1].fire("keydown", { key: "Enter" });
  assert.equal(s.focus, "Warehouse/B|HigherEducation|Input");
  assert.ok(!boxes[0].classList.contains("wd-er-box-current"));
  assert.ok(boxes[1].classList.contains("wd-er-box-current"));
  assert.deepEqual(s.selection, []);
});

test("ER chip and diagram navigation share detail focus without changing membership", () => {
  const { D, m, body, flush } = fixture(), s = {}, picks = [];
  const controller = D.ui.erWorkspace(body, m, s, { onPick: (id) => picks.push(id) }); flush();
  const a = "Warehouse/A|HigherEducation|Input", b = "Warehouse/B|HigherEducation|Input";
  controller.select(a); controller.select(b, true); flush();
  const svg = body.querySelector("svg"), boxes = body.querySelectorAll(".wd-er-box"), seeds = [...s.selection];
  function current(id) {
    assert.equal(s.focus, id);
    assert.deepEqual(boxes.filter((box) => box.classList.contains("wd-er-box-current")).map((box) => box.getAttribute("data-er-id")), [id]);
    const chips = body.querySelectorAll(".wd-chip-select");
    assert.deepEqual(chips.filter((chip) => chip.classList.contains("wd-current")).map((chip) => chip.querySelector(".wd-chip-name").getAttribute("title")), [id.split("|")[0] + " · HigherEducation.Input"]);
    assert.deepEqual(s.selection, seeds);
    assert.equal(body.querySelector("svg"), svg);
    assert.equal(body.querySelectorAll(".wd-er-box").length, boxes.length);
  }
  s.view = { k: 1.4, x: 30, y: 40 };
  const view = { ...s.view };
  boxes.find((box) => box.getAttribute("data-er-id") === a).fire("keydown", { key: "Enter" });
  current(a);
  assert.deepEqual(s.view, view);
  body.querySelectorAll(".wd-chip-name").find((chip) => chip.getAttribute("title") === "Warehouse/B · HigherEducation.Input").fire("click");
  current(b);
  assert.notDeepEqual(s.view, view, "chip navigation retains its explicit zoom");
  const chipView = { ...s.view }, boxA = boxes.find((box) => box.getAttribute("data-er-id") === a);
  boxA.fire("pointerdown"); boxA.fire("pointerup");
  current(a);
  assert.deepEqual(s.view, chipView);
  assert.deepEqual(picks, [a, b, a]);
});

test("ER node activation updates the entity page's side and bottom details", () => {
  const { D, m, body, root, flush } = fixture();
  D.ui.entitiesPage(body, m); flush();
  const svg = body.querySelector("svg"), boxes = body.querySelectorAll(".wd-er-box");
  for (const key of ["a", "f"]) {
    const box = boxes.find((b) => b.getAttribute("data-er-id") === m.nodes.get(key).id);
    box.fire("pointerdown"); box.fire("pointerup");
    for (const selector of [".wd-side", ".wd-entry-detail"]) {
      assert.equal(body.querySelector(selector).querySelector(".wd-detail-title").textContent, m.nodes.get(key).label);
    }
    assert.equal(root.__WD_STATE.entities.selected, "node|" + key);
    assert.equal(body.querySelector("svg"), svg);
    assert.equal(body.querySelectorAll(".wd-er-box").length, boxes.length);
  }
});

for (const activation of ["pointer", "Enter"]) {
  test(`ER ${activation} opens cross-item endpoint details without changing the chosen items`, () => {
    const { D, m, body, root, flush } = fixture();
    m.items.forEach((it) => { it.type = "Warehouse"; });
    m.tables.foreignkeys = [{ item: "Warehouse/A", schema: "HigherEducation", object: "Input", columns: "Id",
      primaryitem: "Warehouse/B", primaryschema: "HigherEducation", primaryobject: "Input", primarycolumns: "Id" }];
    root.__WD_STATE.entities = { items: ["|Warehouse/A"] };
    D.ui.entitiesPage(body, m); flush();
    const state = root.__WD_STATE.entities, svg = body.querySelector("svg"), boxes = body.querySelectorAll(".wd-er-box");
    const id = "Warehouse/B|HigherEducation|Input", box = boxes.find((b) => b.getAttribute("data-er-id") === id);
    assert.ok(box, "the relationship includes its other-item endpoint");
    assert.ok(!body.querySelector(".wd-entry-list").textContent.includes("Warehouse/B"));
    if (activation === "Enter") box.fire("keydown", { key: "Enter" });
    else { box.fire("pointerdown"); box.fire("pointerup"); }
    for (const selector of [".wd-side", ".wd-entry-detail"]) {
      assert.equal(body.querySelector(selector).querySelector(".wd-detail-title")?.textContent, "HigherEducation.Input");
    }
    assert.equal(state.selected, "node|c");
    assert.equal(state.er.focus, id);
    assert.deepEqual(state.er.selection, []);
    assert.deepEqual(state.items, ["|Warehouse/A"]);
    assert.ok(box.classList.contains("wd-er-box-current"));
    assert.equal(body.querySelector("svg"), svg);
    assert.equal(body.querySelectorAll(".wd-er-box").length, boxes.length);
  });
}

test("ER endpoint without catalogue metadata shows its identity and the metadata gap in both panels", () => {
  const { D, m, body, flush } = fixture();
  m.tables.foreignkeys = [{ item: "Warehouse/A", schema: "HigherEducation", object: "Input", columns: "Id",
    primaryitem: "Warehouse/External", primaryschema: "Other", primaryobject: "Missing", primarycolumns: "Id" }];
  D.ui.entitiesPage(body, m); flush();
  const svg = body.querySelector("svg"), box = body.querySelectorAll(".wd-er-box").find((b) => b.getAttribute("data-er-id") === "Warehouse/External|Other|Missing");
  box.fire("keydown", { key: "Enter" });
  for (const selector of [".wd-side", ".wd-entry-detail"]) {
    const panel = body.querySelector(selector);
    assert.equal(panel.querySelector(".wd-detail-title")?.textContent, "Other.Missing");
    assert.ok(panel.textContent.includes("Warehouse/External"));
    assert.ok(panel.textContent.includes("No catalogue metadata is available for this table."));
  }
  assert.equal(body.querySelector("svg"), svg);
});

test("ER dragging moves a box but neither opens details nor zooms, and cancellation does nothing", () => {
  const { D, m, body, flush } = fixture(), s = {}, picks = [];
  D.ui.erWorkspace(body, m, s, { onPick: (id) => picks.push(id) }); flush();
  const box = body.querySelector(".wd-er-box"), view = { ...s.view };
  box.fire("pointerdown"); box.fire("pointermove", { clientX: 20, clientY: 10 }); box.fire("pointerup", { clientX: 20, clientY: 10 });
  assert.equal(Object.keys(s.moved).length, 1);
  assert.deepEqual(s.view, view);
  assert.deepEqual(s.selection, []);
  box.fire("pointerdown"); box.fire("pointercancel"); box.fire("pointerup");
  assert.deepEqual(s.view, view);
  assert.deepEqual(s.selection, []);
  assert.deepEqual(picks, []);
});
