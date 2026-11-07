// The Catalogue Dashboard renderer. Every script in this folder is concatenated
// in name order inside one function, so they share its scope. They run inside
// HTML Content (Regular) and, for their tests, under Node.

// The page measures carry delimited text: a table starts with TABLE, its name
// and column names; each row starts with ROW; FIELD separates fields. Every <
// arrives as LESS so that no catalogue text can close the data element.
var FIELD = "", ROW = "", TABLE = "", LESS = "";
// An item, node key or record ID ends with OWNER and its catalogue's code.
var OWNER = "";

var KIND = {
  TABLE: "Table", VIEW: "View", FOLDER: "Folder", SHORTCUT: "Shortcut",
  TEST: "Test", ASSUMPTION: "Assumption", MODEL: "Semantic model", REPORT: "Report"
};
var CATALOGUE_ITEM = "Warehouse/_weaver";
var ITEM_TYPES = ["Lakehouse", "Warehouse", "SQLDatabase", "SemanticModel", "Report"];
// Edge kinds travel as their first letter.
var EDGE_KINDS = { D: "Dependency", S: "Shortcut", V: "Validation", E: "External" };

function parsePayload(text) {
  var tables = {}, problems = [];
  String(text || "").split(LESS).join("<").split(TABLE).forEach(function (chunk) {
    if (!chunk) return;
    var rows = chunk.split(ROW), head = rows[0].split(FIELD), name = head[0], cols = head.slice(1), out = [];
    for (var r = 1; r < rows.length; r++) {
      var fields = rows[r].split(FIELD);
      if (fields.length !== cols.length) { problems.push(name + " row " + r + " has " + fields.length + " fields, not " + cols.length); continue; }
      var row = {};
      for (var c = 0; c < cols.length; c++) row[cols[c]] = fields[c] === "" ? null : fields[c];
      out.push(row);
    }
    tables[name] = out;
  });
  return { tables: tables, problems: problems };
}

function num(value) {
  if (value === null || value === undefined || value === "") return null;
  var n = Number(value);
  return isNaN(n) ? null : n;
}

function identityKey(item, schema, object) { return item + "|" + (schema || "") + "|" + (object || ""); }

function isValidation(node) { return node.kind === KIND.TEST || node.kind === KIND.ASSUMPTION; }

function bare(value) { var s = String(value), at = s.indexOf(OWNER); return at < 0 ? s : s.slice(0, at); }
function ownerCode(value) { var s = String(value), at = s.indexOf(OWNER); return at < 0 ? "" : s.slice(at + 1); }
function owned(value, code) { return code ? value + OWNER + code : value; }
function itemType(label) { return bare(label).split("/")[0]; }
function itemName(label) { var s = bare(label); return s.slice(s.indexOf("/") + 1); }
/* The catalogues the page reads, by code; set by buildModel. */
var CATALOGUES = new Map();
function catalogueLabel(value) { var c = CATALOGUES.get(ownerCode(value)); return c ? c.label : ""; }
/* Each installed item's workspace; set by buildModel. */
var ITEM_WORKSPACES = new Map();
/* The Fabric item of each item whose path another item shares. */
var ITEM_TARGETS = new Map();
/* An item as every page shows it: Workspace/Kind/Name, as the chooser lists it. */
function shownItem(label) {
  if (label === null || label === undefined) return "";
  var w = ITEM_WORKSPACES.get(label) || catalogueLabel(label), target = ITEM_TARGETS.get(label);
  return (w ? w + "/" : "") + bare(label) + (target ? " (" + target + ")" : "");
}
/* An item's name alone, where its workspace and kind are shown beside it. */
function shownName(label) { return itemName(label); }

function typeRank(type) { var i = ITEM_TYPES.indexOf(type); return i < 0 ? ITEM_TYPES.length : i; }

function compare(a, b) {
  a = String(a === null || a === undefined ? "" : a).toLowerCase();
  b = String(b === null || b === undefined ? "" : b).toLowerCase();
  return a < b ? -1 : a > b ? 1 : 0;
}

function addTo(map, key, value) { var list = map.get(key); if (!list) map.set(key, list = []); list.push(value); }

/* The estate one payload describes: items, nodes with their current state,
   the authoritative edges Health walks and the presentation edges the graph
   draws, where a read through a shortcut is drawn from the shortcut. */
function buildModel(tables, problems) {
  var t = function (name) { return tables[name] || []; };
  var meta = t("meta")[0] || {}, page = t("page")[0] || {};
  CATALOGUES = new Map();
  t("catalogues").forEach(function (r) { CATALOGUES.set(r.code, { code: r.code, label: r.label, reference: r.reference }); });
  var m = {
    page: page.name || "overview", at: num(meta.at) || Date.now(), tables: tables,
    catalogues: Array.from(CATALOGUES.values()), mode: meta.mode || null, imported: num(meta.imported),
    tooLarge: (t("toolarge")[0] || null),
    problems: (problems || []).slice(), items: new Map(), nodes: new Map(), byIdentity: new Map(),
    internalItems: new Set(), edgeCount: 0, hiddenEdges: 0, externalCount: 0
  };
  t("internal").forEach(function (r) { m.internalItems.add(r.item); });
  function item(label) {
    var it = m.items.get(label);
    if (!it) m.items.set(label, it = { label: label, type: itemType(label), name: itemName(label), code: ownerCode(label), catalogue: catalogueLabel(label),
      workspace: null, workspaceId: null, target: null, targetId: null, version: null, nodes: [], internal: m.internalItems.has(label) || bare(label) === CATALOGUE_ITEM });
    return it;
  }
  t("items").forEach(function (r) {
    var it = item(r.item);
    it.workspace = r.workspace; it.target = r.target; it.version = r.version;
    it.workspaceId = r.workspaceid || null; it.targetId = r.targetid || null;
  });
  ITEM_WORKSPACES = new Map(); ITEM_TARGETS = new Map();
  m.items.forEach(function (it) { if (it.workspace) ITEM_WORKSPACES.set(it.label, it.workspace); });
  // Two catalogues in one workspace can each install an item of one name, as a
  // mirror does; those are told apart by the Fabric item each is installed to.
  var paths = new Map();
  m.items.forEach(function (it) { if (!it.internal) addTo(paths, shownItem(it.label), it); });
  paths.forEach(function (list) { if (list.length > 1) list.forEach(function (it) { if (it.target) ITEM_TARGETS.set(it.label, it.target); }); });
  var first = m.catalogues.length ? m.catalogues[0].code : "";
  var catalogue = m.items.get(owned(CATALOGUE_ITEM, first)) || m.items.get(CATALOGUE_ITEM);
  m.catalogue = { name: catalogue ? catalogue.target : null, workspace: catalogue ? catalogue.workspace : null, version: catalogue ? catalogue.version : null };

  t("nodes").forEach(function (r) {
    if (m.nodes.has(r.key)) { m.problems.push("Two lineage nodes share the key " + r.key + "; one of them is not shown."); return; }
    var flags = num(r.flags) || 0;
    var n = {
      key: r.key, item: r.item, schema: r.schema, object: r.object, kind: r.kind, label: r.label || r.object || r.item,
      desc: r.description || "", canLoad: !!(flags & 1), isStatic: !!(flags & 2), isMirrored: !!(flags & 4), isInstalled: !!(flags & 8),
      id: identityKey(r.item, r.schema, r.object), load: null, test: null, built: null,
      up: [], down: [], vup: [], vdown: [], stubs: [], missing: [], kinds: {}
    };
    m.nodes.set(n.key, n);
    m.byIdentity.set(n.id, n);
    item(n.item).nodes.push(n);
  });

  var seen = new Set(), vseen = new Set(), edges = t("edges");
  edges.forEach(function (r) {
    var d = m.nodes.get(r.down), kind = EDGE_KINDS[r.kind] || r.kind;
    if (!d) return;
    if (kind === "External") { d.stubs.push(r.reference || r.up); m.externalCount += 1; return; }
    var u = m.nodes.get(r.up);
    if (!u) { if (r.reference) d.missing.push(r.reference); m.hiddenEdges += 1; return; }
    var key = u.key + ">" + d.key;
    if (!seen.has(key)) { seen.add(key); u.down.push(d.key); d.up.push(u.key); m.edgeCount += 1; }
    var from = r.through && m.nodes.has(r.through) && r.through !== d.key ? m.nodes.get(r.through) : u;
    var vkey = from.key + ">" + d.key;
    if (!vseen.has(vkey)) {
      vseen.add(vkey);
      from.vdown.push(d.key); d.vup.push(from.key);
      d.kinds[from.key] = from === u ? kind : "Dependency";
    }
  });

  m.crossings = joinCatalogues(m, t("shortcuts"));
  m.crossings.forEach(function (c) {
    if (!c.producer) return;
    var u = m.nodes.get(c.producer), d = m.nodes.get(c.consumer), key = u.key + ">" + d.key;
    if (seen.has(key)) return;
    seen.add(key); u.down.push(d.key); d.up.push(u.key); m.edgeCount += 1;
    if (!vseen.has(key)) { vseen.add(key); u.vdown.push(d.key); d.vup.push(u.key); d.kinds[u.key] = "Shortcut"; }
  });

  t("loads").forEach(function (r) {
    var n = m.byIdentity.get(identityKey(r.item, r.schema, r.object));
    if (n) n.load = status(r);
  });
  mirrorSources(m, t("mirrors"));
  markChanges(m, t("signatures"));
  t("tests").forEach(function (r) {
    var n = m.byIdentity.get(identityKey(r.item, r.schema, r.object));
    if (n) { n.test = status(r); n.test.failures = num(r.failures); }
  });
  // A certified data object with no lineage node means its item's graph was
  // not projected by the build that certified it.
  m.graphGaps = new Map();
  t("built").forEach(function (r) {
    var n = m.byIdentity.get(identityKey(r.item, r.schema, r.object));
    if (n) n.built = num(r.built);
    else if (!isInternal(m, r.item, r.schema)) m.graphGaps.set(r.item, (m.graphGaps.get(r.item) || 0) + 1);
  });
  m.items.forEach(function (it) {
    it.nodes.sort(function (a, b) { return compare(a.schema, b.schema) || compare(a.label, b.label) || compare(a.key, b.key); });
  });
  m.workflows = t("workflows").map(function (r) {
    return { id: r.workflow, started: num(r.started), completed: num(r.completed), records: num(r.records) || 0, failed: num(r.failed) || 0, tasks: r.tasks ? r.tasks.split(",") : [] };
  });
  // Newest first: CONCATENATEX keeps no order unless asked for one.
  m.workflows.sort(function (a, b) { return (b.completed || 0) - (a.completed || 0) || compare(a.id, b.id); });
  m.workflowCount = num((t("workflowcount")[0] || {}).count);
  return m;
}

/* Where each physical shortcut lands among the catalogues read, as
   weaver.catalogues.join decides it: the installation of the target item in
   its workspace, then the object that item installs at the target path. A
   shortcut nothing given installs, or that several items install, joins nothing. */
function joinCatalogues(m, shortcuts) {
  var installed = new Map();
  m.items.forEach(function (it) {
    if (!it.target) return;
    var key = [String(it.workspace || "").toLowerCase(), it.type, String(it.target).toLowerCase()].join("|");
    addTo(installed, key, it);
  });
  var out = [];
  shortcuts.forEach(function (r) {
    var code = ownerCode(r.item), consumerItem = m.items.get(r.item);
    var workspace = r.workspace || (consumerItem ? consumerItem.workspace : "");
    var target = workspace + "/" + r.targettype + "/" + r.target + "/" + r.targetschema + (r.targetobject ? "." + r.targetobject : "");
    var consumer = m.byIdentity.get(identityKey(r.item, r.schema, r.object));
    var crossing = { consumer: consumer ? consumer.key : null, item: r.item, target: target, workspace: workspace, producer: null, reason: null };
    var candidates = installed.get([String(workspace).toLowerCase(), r.targettype, String(r.target).toLowerCase()].join("|")) || [];
    var reached = candidates.map(function (it) { return { item: it, nodes: reachedNodes(m, it, r) }; }).filter(function (x) { return x.nodes.length; });
    if (!consumer) crossing.reason = "Its shortcut object is not installed in " + shownItem(r.item) + ".";
    else if (!candidates.length) crossing.reason = "No catalogue read installs " + workspace + "/" + r.targettype + "/" + r.target + ".";
    else if (reached.length > 1) crossing.reason = target + " is installed by more than one item read.";
    else if (!reached.length) crossing.reason = r.targetschema + (r.targetobject ? "." + r.targetobject : "") + " is not installed there.";
    if (crossing.reason) { out.push(crossing); return; }
    reached[0].nodes.forEach(function (n) {
      var schemaDestination = r.type === "Schema" ? m.byIdentity.get(identityKey(r.item, r.schema, n.object)) : null;
      out.push({ consumer: schemaDestination ? schemaDestination.key : consumer.key, item: r.item, target: target, workspace: workspace, producer: n.key, reason: null });
    });
    void code;
  });
  return out;
}

/* Where each mirrored object's rows come from. When the catalogue holding its
   source is read, the object's state is the source's, and none when the source
   no longer holds it; otherwise its state is not observed here. */
function mirrorSources(m, rows) {
  // A workspace names items uniquely per type: a Lakehouse and a Warehouse may share a name.
  function where(type, workspace, target) { return [type, workspace, target].map(function (v) { return String(v || "").toLowerCase(); }).join("|"); }
  var byTarget = new Map();
  m.items.forEach(function (it) {
    if (it.target) byTarget.set(where(it.type, it.workspace, it.target), it);
  });
  // A row whose object was since built locally still names the catalogue
  // mirrored. Lineage marks the objects still borrowed: a Warehouse records a
  // live row's delete time past the latest datetime DAX can read.
  m.mirrored = new Map();
  rows.forEach(function (r) {
    // A mirror borrows each item into an item of its own type.
    var source = byTarget.get(where(bare(r.item).split("/")[0], r.workspace, r.target));
    if (source) m.mirrored.set(ownerCode(r.item), source.code);
    var n = m.byIdentity.get(identityKey(r.item, r.schema, r.object));
    // The source schema is named as Spark names it; a Lakehouse object's area is its own.
    var slash = String(r.schema || "").indexOf("/"), sourceSchema = String(r.sourceschema || "");
    if (slash >= 0 && sourceSchema.indexOf("/") < 0) sourceSchema = r.schema.slice(0, slash + 1) + sourceSchema;
    if (n && n.isMirrored && source) n.mirror = { read: true, source: m.byIdentity.get(identityKey(source.label, sourceSchema, r.sourceobject)) || null };
  });
}

/* How each object differs between a mirror and the catalogue it mirrors,
   where both are read. On the mirror's side an object is borrowed when it is
   mirrored, changed when its source signature differs from the same object's
   there, added when that catalogue holds no such object, and otherwise rebuilt
   with the same code. The source's copy of a borrowed or changed object takes
   that state. A mirror whose source is not read marks only what it borrows. */
var CHANGE = { BORROWED: "borrowed", CHANGED: "changed", ADDED: "added" };
function markChanges(m, signatures) {
  var sources = m.mirrored, signed = new Map();
  signatures.forEach(function (r) { signed.set(identityKey(r.item, r.schema, r.object) + "|" + r.kind, r.signature); });
  function signature(n) { return signed.get(identityKey(n.item, n.schema, n.object) + "|" + (isValidation(n) ? "test" : "data")) || null; }
  m.nodes.forEach(function (n) {
    var code = sources.get(ownerCode(n.item));
    if (!n.isMirrored && !code) return;
    var original = n.mirror && n.mirror.source ? n.mirror.source
      : code ? m.byIdentity.get(identityKey(owned(bare(n.item), code), n.schema, n.object)) || null : null;
    if (n.isMirrored) n.change = CHANGE.BORROWED;
    else if (!original) n.change = CHANGE.ADDED;
    else if (signature(n) && signature(original) && signature(n) !== signature(original)) n.change = CHANGE.CHANGED;
    if (n.change) m.changes = true;
    if (!original) return;
    n.original = original;
    (original.copies = original.copies || []).push(n);
    if (n.change && !original.change) original.change = n.change;
  });
}

function relational(schema) { return String(schema || "").replace(/^Tables\//, ""); }

function reachedNodes(m, it, r) {
  var schema = relational(r.targetschema);
  if (r.type === "Schema") {
    return it.nodes.filter(function (n) { return relational(n.schema).toLowerCase() === schema.toLowerCase() && String(n.schema || "").indexOf("Files") !== 0; });
  }
  if (r.type === "Folder") {
    var parts = String(r.targetschema).replace(/^\/+|\/+$/g, "").split("/");
    if (parts.length !== 2) return [];
    var folder = m.byIdentity.get(identityKey(it.label, "Files/" + parts[0], parts[1]));
    return folder ? [folder] : [];
  }
  return it.nodes.filter(function (n) { return n.object === r.targetobject && relational(n.schema).toLowerCase() === schema.toLowerCase() && String(n.schema || "").indexOf("Files") !== 0; });
}

function status(r) {
  return { result: r.result, workflow: r.workflow, started: num(r.started), completed: num(r.completed), duration: num(r.duration) };
}

/* The catalogue, the Dashboard and the `_` surface the catalogue presents in
   every item are Weaver's own; no page reports them as part of the estate. */
var INTERNAL_SCHEMA = /^(?:Files\/|Tables\/)?_$/;

function isInternal(m, item, schema) {
  var it = m.items.get(item);
  return !!(it && it.internal) || bare(item) === CATALOGUE_ITEM || INTERNAL_SCHEMA.test(schema || "");
}

function visibleItems(m) {
  return Array.from(m.items.values()).filter(function (it) { return !it.internal; });
}

/* Shown names: a Lakehouse folder keeps its Files path. */
function qualified(node) {
  if (!node.schema && !node.object) return shownItem(node.item);
  if (!node.object) return node.schema;
  return node.schema + (String(node.schema).indexOf("Files") === 0 ? "/" : ".") + node.object;
}
