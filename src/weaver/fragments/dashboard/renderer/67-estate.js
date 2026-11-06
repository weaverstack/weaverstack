// Estate: which workspaces and items the catalogues read supply and receive,
// as direct object dependencies, and where they read one another in a loop.
// It shows the estate the catalogues describe, not the whole tenant.

/* Items by physical identity, workspaces, and the direct dependencies between
   them. An item is its workspace and Fabric item, so two catalogues recording
   one item count it once. A dependency is one object reading another
   directly: through a shortcut it is the shortcut, never what reads it, and a
   schema shortcut is one dependency. Dependencies inside one item are left
   out. */
function estateTopology(m) {
  var t = function (name) { return m.tables[name] || []; };
  var physical = new Map(), byLabel = new Map(), installed = new Map();
  m.items.forEach(function (it) {
    if (it.internal || !it.target) return;
    var key = (it.workspaceId || it.workspace || "").toLowerCase() + "|" + (it.targetId || it.type + "/" + it.target).toLowerCase();
    var p = physical.get(key);
    if (!p) physical.set(key, p = { key: key, type: it.type, name: it.target, workspace: it.workspace || "", labels: [], objects: 0,
      loads: 0, failed: 0, pending: 0, tests: 0, testsFailed: 0, assessed: false });
    p.labels.push(it.label);
    byLabel.set(it.label, p);
    addTo(installed, [String(it.workspace || "").toLowerCase(), it.type, String(it.target).toLowerCase()].join("|"), p);
  });
  t("itemobjects").forEach(function (r) { var p = byLabel.get(r.item); if (p) p.objects += num(r.objects) || 0; });
  t("itemloads").forEach(function (r) {
    var p = byLabel.get(r.item); if (!p) return;
    p.loads += num(r.loads) || 0; p.failed += num(r.failed) || 0; p.pending += num(r.pending) || 0; p.assessed = true;
  });
  t("itemtests").forEach(function (r) {
    var p = byLabel.get(r.item); if (!p) return;
    p.tests += num(r.tests) || 0; p.testsFailed += num(r.failed) || 0; p.assessed = true;
  });
  var edges = new Map(), unmatched = new Map();
  function connect(up, down, count) {
    if (!up || !down || up === down) return;
    var key = up.key + ">" + down.key, e = edges.get(key);
    if (!e) edges.set(key, e = { up: up.key, down: down.key, count: 0 });
    e.count += count;
  }
  t("itemedges").forEach(function (r) { connect(byLabel.get(r.up), byLabel.get(r.down), num(r.count) || 0); });
  var seenShortcut = new Set();
  t("shortcuts").forEach(function (r) {
    var consumer = byLabel.get(r.item);
    if (!consumer) return;
    var workspace = r.workspace || consumer.workspace;
    // The same physical shortcut recorded by two catalogues is one dependency.
    var key = consumer.key + "|" + r.schema + "|" + r.object;
    if (seenShortcut.has(key)) return;
    seenShortcut.add(key);
    var found = installed.get([String(workspace).toLowerCase(), r.targettype, String(r.target).toLowerCase()].join("|")) || [];
    var producers = Array.from(new Set(found));
    if (producers.length === 1) connect(producers[0], consumer, 1);
    else unmatched.set(consumer.workspace, (unmatched.get(consumer.workspace) || 0) + 1);
  });
  var workspaces = new Map();
  physical.forEach(function (p) {
    var w = workspaces.get(p.workspace);
    if (!w) workspaces.set(p.workspace, w = { name: p.workspace, items: [], kinds: {}, objects: 0, loads: 0, failed: 0, pending: 0, tests: 0, testsFailed: 0, assessed: false,
      receives: new Set(), supplies: new Set(), incoming: 0, outgoing: 0, unmatched: 0 });
    w.items.push(p);
    w.kinds[p.type] = (w.kinds[p.type] || 0) + 1;
    w.objects += p.objects; w.loads += p.loads; w.failed += p.failed; w.pending += p.pending; w.tests += p.tests; w.testsFailed += p.testsFailed;
    if (p.assessed) w.assessed = true;
  });
  unmatched.forEach(function (n, name) { var w = workspaces.get(name); if (w) w.unmatched += n; });
  var itemEdges = Array.from(edges.values()), workspaceEdges = new Map();
  itemEdges.forEach(function (e) {
    var a = physical.get(e.up), b = physical.get(e.down);
    if (a.workspace === b.workspace) return;
    var from = workspaces.get(a.workspace), to = workspaces.get(b.workspace);
    from.supplies.add(b.workspace); to.receives.add(a.workspace);
    from.outgoing += e.count; to.incoming += e.count;
    var key = a.workspace + ">" + b.workspace, we = workspaceEdges.get(key);
    if (!we) workspaceEdges.set(key, we = { up: a.workspace, down: b.workspace, count: 0 });
    we.count += e.count;
  });
  var wEdges = Array.from(workspaceEdges.values());
  return {
    items: physical, workspaces: workspaces, itemEdges: itemEdges, workspaceEdges: wEdges,
    itemLoops: loopsOf(Array.from(physical.keys()), itemEdges),
    workspaceLoops: loopsOf(Array.from(workspaces.keys()), wEdges)
  };
}

/* Groups of two or more that read one another, each in name order. */
function loopsOf(keys, edges) {
  var ups = new Map();
  keys.forEach(function (k) { ups.set(k, []); });
  edges.forEach(function (e) { if (ups.has(e.down)) ups.get(e.down).push(e.up); });
  var g = { nodes: new Map() };
  ups.forEach(function (list, k) { g.nodes.set(k, { up: list }); });
  return components(g).list.filter(function (c) { return c.length > 1; })
    .map(function (c) { return c.slice().sort(compare); }).sort(function (a, b) { return compare(a[0], b[0]); });
}

/* Columns by the longest chain of suppliers before each node, with the members
   of a loop side by side in one column. */
function topologyColumns(keys, edges) {
  var ups = new Map();
  keys.forEach(function (k) { ups.set(k, []); });
  edges.forEach(function (e) { if (ups.has(e.down) && ups.has(e.up)) ups.get(e.down).push(e.up); });
  var g = { nodes: new Map() };
  ups.forEach(function (list, k) { g.nodes.set(k, { up: list }); });
  var c = components(g), level = [];
  c.list.forEach(function (members, i) {
    var l = 0;
    members.forEach(function (k) { ups.get(k).forEach(function (u) { var j = c.of.get(u); if (j !== i) l = Math.max(l, level[j] + 1); }); });
    level[i] = l;
  });
  var columns = [];
  keys.slice().sort(compare).forEach(function (k) {
    var l = level[c.of.get(k)];
    (columns[l] = columns[l] || []).push(k);
  });
  return columns.map(function (col) { return col || []; });
}

function loadTone(x) {
  if (x.failed || x.testsFailed) return "bad";
  if (x.pending) return "warn";
  return x.assessed ? "ok" : "none";
}

function loadNote(x) {
  if (!x.assessed) return "no load or test recorded";
  var parts = [];
  if (x.failed) parts.push(fmt(x.failed) + " failed loads");
  if (x.pending) parts.push(fmt(x.pending) + " pending");
  if (x.testsFailed) parts.push(fmt(x.testsFailed) + " failed validations");
  return parts.length ? parts.join(" · ") : "last loads and validations succeeded";
}

var KIND_NAMES = { Lakehouse: "Lakehouses", Warehouse: "Warehouses", SQLDatabase: "SQL databases", SemanticModel: "semantic models", Report: "Reports" };

function composition(kinds) {
  return ITEM_TYPES.filter(function (k) { return kinds[k]; }).map(function (k) {
    return fmt(kinds[k]) + " " + (kinds[k] === 1 ? KIND_NAMES[k].replace(/s$/, "") : KIND_NAMES[k]);
  }).join(" · ") || "no items";
}

function estatePage(body, m) {
  var topo = estateTopology(m), s = pageState("estate");
  s.level = s.level || "workspace";
  if (s.selected && !(s.level === "workspace" ? topo.workspaces.has(s.selected) : topo.items.has(s.selected))) s.selected = null;
  var workspaceList = Array.from(topo.workspaces.values()), itemList = Array.from(topo.items.values());
  var crossing = topo.workspaceEdges.reduce(function (a, e) { return a + e.count; }, 0);
  body.appendChild(el("div", { "class": "wd-tiles" }, [
    tile("Workspaces", workspaceList.length, "with an item a catalogue read installs", "none"),
    tile("Items", itemList.length, composition(itemList.reduce(function (k, p) { k[p.type] = (k[p.type] || 0) + 1; return k; }, {})), "none"),
    tile("Dependencies between workspaces", crossing, "direct object dependencies", "none")
  ]));
  body.appendChild(el("p", { "class": "wd-note", text: "The estate is what the catalogues read describe. A dependency is one object reading another directly; dependencies inside one item are left out. Load state is each item's last loads and validations, not a Health assessment." }));
  var bar = el("div", { "class": "wd-toolbar" }, [segmented("Show", ["workspace", "item"], s.level, function (v) { s.level = v; s.selected = null; saveState(); redraw(); },
    function (v) { return v === "workspace" ? "Workspaces" : "Items"; })]);
  body.appendChild(bar);
  var nodes, edges, loops;
  if (s.level === "workspace") {
    nodes = workspaceList.map(function (w) { return { key: w.name, title: w.name, eyebrow: "Workspace", lines: [composition(w.kinds),
      "Receives from " + fmt(w.receives.size) + (w.receives.size === 1 ? " workspace" : " workspaces") + " · " + fmt(w.incoming) + (w.incoming === 1 ? " dependency" : " dependencies"),
      "Supplies " + fmt(w.supplies.size) + (w.supplies.size === 1 ? " workspace" : " workspaces") + " · " + fmt(w.outgoing) + (w.outgoing === 1 ? " dependency" : " dependencies")],
      tone: loadTone(w), note: loadNote(w) }; });
    edges = topo.workspaceEdges; loops = topo.workspaceLoops;
  } else {
    var incoming = new Map(), outgoing = new Map();
    topo.itemEdges.forEach(function (e) { incoming.set(e.down, (incoming.get(e.down) || 0) + e.count); outgoing.set(e.up, (outgoing.get(e.up) || 0) + e.count); });
    nodes = itemList.map(function (p) { return { key: p.key, title: p.name, eyebrow: p.type + " · " + p.workspace, lines: [
      fmt(p.objects) + (p.objects === 1 ? " object" : " objects"),
      fmt(incoming.get(p.key) || 0) + " in · " + fmt(outgoing.get(p.key) || 0) + " out"], tone: loadTone(p), note: loadNote(p) }; });
    edges = topo.itemEdges; loops = topo.itemLoops;
  }
  var drawing = el("div", { "class": "wd-estate" });
  body.appendChild(drawing);
  drawTopology(drawing, nodes, edges, s, function (key) { s.selected = s.selected === key ? null : key; saveState(); redraw(); });
  if (loops.length) {
    body.appendChild(section("Loops", [
      el("p", { "class": "wd-note", text: s.level === "workspace" ?
        "These workspaces read from one another, directly or through others. A loop between workspaces does not mean any object reads itself." :
        "These items read from one another, directly or through others." }),
      el("ul", { "class": "wd-list" }, loops.map(function (members) {
        return el("li", { text: members.map(function (k) { return s.level === "workspace" ? k : topo.items.get(k).name + " · " + topo.items.get(k).workspace; }).join(" ⇄ ") });
      }))
    ]));
  }
  if (s.selected) body.appendChild(estateDetail(m, topo, s));
}

function estateDetail(m, topo, s) {
  var rows, title;
  if (s.level === "workspace") {
    var w = topo.workspaces.get(s.selected);
    title = w.name;
    rows = w.items.map(function (p) {
      var inn = 0, out = 0, from = new Set(), to = new Set();
      topo.itemEdges.forEach(function (e) {
        var a = topo.items.get(e.up), b = topo.items.get(e.down);
        if (a.workspace === b.workspace) return;
        if (e.down === p.key) { inn += e.count; from.add(a.workspace); }
        if (e.up === p.key) { out += e.count; to.add(b.workspace); }
      });
      return { p: p, inn: inn, out: out, from: Array.from(from).sort(compare).join(", "), to: Array.from(to).sort(compare).join(", ") };
    });
  } else {
    var p0 = topo.items.get(s.selected);
    title = p0.name + " · " + p0.workspace;
    rows = [];
    topo.itemEdges.forEach(function (e) {
      if (e.down === s.selected) rows.push({ p: topo.items.get(e.up), inn: 0, out: e.count, from: "", to: p0.name });
      if (e.up === s.selected) rows.push({ p: topo.items.get(e.down), inn: e.count, out: 0, from: p0.name, to: "" });
    });
  }
  var w0 = s.level === "workspace" ? topo.workspaces.get(s.selected) : null;
  return section(title, [
    w0 && w0.unmatched ? el("p", { "class": "wd-note", text: fmt(w0.unmatched) + " shortcuts here read items no catalogue read installs; they are not counted." }) : null,
    dataTable([
      { key: "item", title: s.level === "workspace" ? "Item" : "Connected item", value: function (r) { return r.p.name; } },
      { key: "kind", title: "Kind", value: function (r) { return r.p.type; } },
      { key: "workspace", title: "Workspace", value: function (r) { return r.p.workspace; } },
      { key: "objects", title: "Objects", numeric: true, value: function (r) { return r.p.objects; } },
      { key: "in", title: s.level === "workspace" ? "Dependencies in" : "It reads", numeric: true, value: function (r) { return r.inn; } },
      { key: "out", title: s.level === "workspace" ? "Dependencies out" : "Reads it", numeric: true, value: function (r) { return r.out; } },
      s.level === "workspace" ? { key: "from", title: "Receives from", value: function (r) { return r.from; } } : null,
      s.level === "workspace" ? { key: "to", title: "Supplies", value: function (r) { return r.to; } } : null,
      { key: "state", title: "Load state", render: function (r) { return el("span", { "class": "wd-chip wd-" + loadTone(r.p), text: loadNote(r.p) }); }, value: function (r) { return loadNote(r.p); } }
    ].filter(Boolean), rows, { sort: "item", desc: false, emptyText: "Nothing here." })
  ]);
}

var ESTATE_CARD = { W: 300, H: 118, GAP_X: 120, GAP_Y: 28, PAD: 24 };

function drawTopology(host, nodes, edges, s, onPick) {
  if (!nodes.length) { host.appendChild(empty("The catalogues record no installed items yet.")); return; }
  var G = ESTATE_CARD, keys = nodes.map(function (n) { return n.key; }), byKey = new Map(nodes.map(function (n) { return [n.key, n]; }));
  var columns = topologyColumns(keys, edges), pos = new Map();
  columns.forEach(function (col, x) {
    col.forEach(function (k, y) { pos.set(k, { x: G.PAD + x * (G.W + G.GAP_X), y: G.PAD + y * (G.H + G.GAP_Y) }); });
  });
  var width = G.PAD * 2 + columns.length * (G.W + G.GAP_X) - G.GAP_X;
  var height = G.PAD * 2 + Math.max.apply(null, columns.map(function (c) { return c.length; })) * (G.H + G.GAP_Y) - G.GAP_Y;
  var near = new Set();
  if (s.selected) { near.add(s.selected); edges.forEach(function (e) { if (e.up === s.selected) near.add(e.down); if (e.down === s.selected) near.add(e.up); }); }
  var svg = sv("svg", { "class": "wd-estate-svg", viewBox: "0 0 " + width + " " + height, width: width, height: height, role: "img", "aria-label": "Estate" });
  svg.appendChild(sv("defs", {}, [sv("marker", { id: "wd-estate-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
    [sv("path", { d: "M 0 0 L 10 5 L 0 10 z", "class": "wd-estate-arrowhead" })])]));
  edges.forEach(function (e) {
    var a = pos.get(e.up), b = pos.get(e.down);
    if (!a || !b) return;
    var x1 = a.x + G.W, y1 = a.y + G.H / 2, x2 = b.x, y2 = b.y + G.H / 2, back = x2 <= x1;
    // A dependency to the same column or back is a loop; it bows above the cards.
    var d = back ? "M " + (a.x + G.W / 2) + " " + a.y + " C " + (a.x + G.W / 2) + " " + (Math.min(a.y, b.y) - 60) + ", " + (b.x + G.W / 2) + " " + (Math.min(a.y, b.y) - 60) + ", " + (b.x + G.W / 2) + " " + b.y
      : "M " + x1 + " " + y1 + " C " + (x1 + G.GAP_X / 2) + " " + y1 + ", " + (x2 - G.GAP_X / 2) + " " + y2 + ", " + x2 + " " + y2;
    var lit = s.selected && (e.up === s.selected || e.down === s.selected);
    svg.appendChild(sv("path", { d: d, "class": "wd-estate-edge" + (lit ? " wd-lit" : "") + (s.selected && !lit ? " wd-dim" : ""), "marker-end": "url(#wd-estate-arrow)" }));
    var lx = back ? (a.x + b.x + G.W) / 2 : (x1 + x2) / 2, ly = back ? Math.min(a.y, b.y) - 40 : (y1 + y2) / 2 - 6;
    svg.appendChild(sv("text", { x: lx, y: ly, "class": "wd-estate-count" + (s.selected && !lit ? " wd-dim" : ""), "text-anchor": "middle" }, [fmt(e.count)]));
  });
  nodes.forEach(function (n) {
    var p = pos.get(n.key), dim = s.selected && !near.has(n.key);
    var g = sv("g", { "class": "wd-estate-card wd-" + n.tone + (n.key === s.selected ? " wd-current" : "") + (dim ? " wd-dim" : ""), transform: "translate(" + p.x + "," + p.y + ")", tabindex: 0, role: "button" }, [
      sv("title", {}, [n.title + " · " + n.note]),
      sv("rect", { width: G.W, height: G.H, rx: 10 }),
      sv("rect", { "class": "wd-estate-tone", width: 5, height: G.H, rx: 2 }),
      sv("text", { x: 16, y: 22, "class": "wd-estate-eyebrow" }, [clipText(n.eyebrow, 40)]),
      sv("text", { x: 16, y: 44, "class": "wd-estate-title" }, [clipText(n.title, 30)])
    ].concat(n.lines.map(function (line, i) { return sv("text", { x: 16, y: 66 + i * 17, "class": "wd-estate-line" }, [clipText(line, 44)]); })));
    g.addEventListener("click", function () { onPick(n.key); });
    g.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onPick(n.key); } });
    svg.appendChild(g);
  });
  host.appendChild(el("div", { "class": "wd-estate-scroll" }, [svg]));
}
