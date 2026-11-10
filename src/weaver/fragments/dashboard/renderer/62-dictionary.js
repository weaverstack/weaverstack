// The declared metadata, indexed once, and the Dictionary page.

function auditColumn(name) {
  return ["row insert datetime", "row update datetime", "row delete datetime", "row signature"].indexOf(String(name || "").toLowerCase().replace(/_/g, " ")) >= 0;
}

function metadata(m) {
  if (m.meta) return m.meta;
  var t = function (name) { return m.tables[name] || []; };
  function keep(r) { return !isInternal(m, r.item, r.schema); }
  var md = { tables: new Map(), folders: new Map(), schemas: [], borrowed: new Set(), columns: new Map(), types: new Map(), keys: new Map(), validations: new Map(),
    foreignKeys: [], references: new Map(), referencedBy: new Map(), models: new Map(), hasMetadata: !!m.tables.tables, hasSemantic: !!m.tables.models };
  t("tables").filter(keep).forEach(function (r) { md.tables.set(identityKey(r.item, r.schema, r.object), r); });
  t("folders").filter(keep).forEach(function (r) { md.folders.set(identityKey(r.item, r.schema, r.object), r); });
  md.schemas = t("schemas").filter(keep);
  t("columns").filter(keep).filter(function (r) { return !auditColumn(r.column); }).forEach(function (r) { addTo(md.columns, identityKey(r.item, r.schema, r.object), r); });
  t("keys").filter(keep).forEach(function (r) { addTo(md.keys, identityKey(r.item, r.schema, r.object), r); });
  t("validations").filter(keep).forEach(function (r) { md.validations.set(identityKey(r.item, r.schema, r.object), r); });
  t("foreignkeys").filter(keep).forEach(function (r) {
    var fk = { from: identityKey(r.item, r.schema, r.object), to: identityKey(r.primaryitem, r.primaryschema, r.primaryobject),
      fromColumns: splitList(r.columns), toColumns: splitList(r.primarycolumns), row: r };
    md.foreignKeys.push(fk);
    addTo(md.references, fk.from, fk); addTo(md.referencedBy, fk.to, fk);
  });
  md.columns.forEach(function (list) { list.sort(function (a, b) { return compare(a.column, b.column); }); });
  var owners = new Map(t("columnowners").map(function (r) { return [r.owner, identityKey(r.item, r.schema, r.object)]; }));
  t("columntypes").forEach(function (r) {
    var id = owners.get(r.owner);
    if (!id || !md.tables.has(id) || auditColumn(r.column)) return;
    var note = (md.columns.get(id) || []).filter(function (c) { return c.column === r.column; })[0];
    addTo(md.types, id, Object.assign({}, r, { ordinal: num(r.ordinal), description: note ? note.description : "" }));
  });
  md.types.forEach(function (list) { list.sort(function (a, b) { return a.ordinal - b.ordinal; }); });
  t("borrowed").forEach(function (r) { md.borrowed.add(identityKey(r.item, r.schema, r.object)); });

  function model(item) {
    var it = m.items.get(item);
    if (it && it.internal) return null;
    var mo = md.models.get(item);
    if (!mo) md.models.set(item, mo = { item: item, name: itemName(item), description: null, tables: new Map(), relationships: [], node: null });
    return mo;
  }
  function table(mo, name) {
    var tb = mo.tables.get(name);
    if (!tb) mo.tables.set(name, tb = { model: mo, name: name, ordinal: null, description: null, mode: null, access: null, columns: [], measures: [], sources: [] });
    return tb;
  }
  t("models").forEach(function (r) { var mo = model(r.item); if (mo) mo.description = r.description; });
  t("smtables").forEach(function (r) {
    var mo = model(r.item); if (!mo) return;
    var tb = table(mo, r.table);
    tb.ordinal = num(r.ordinal); tb.description = r.description; tb.mode = r.mode; tb.access = r.access;
  });
  t("smcolumns").forEach(function (r) { var mo = model(r.item); if (mo) table(mo, r.table).columns.push(r); });
  t("smmeasures").forEach(function (r) { var mo = model(r.item); if (mo) table(mo, r.table).measures.push(r); });
  t("smrelationships").forEach(function (r) {
    var mo = model(r.item); if (!mo) return;
    mo.relationships.push({ name: r.name, from: r.fromtable, fromColumn: r.fromcolumn, to: r.totable, toColumn: r.tocolumn,
      fromCardinality: (r.fromcardinality || "many").toLowerCase(), toCardinality: (r.tocardinality || "one").toLowerCase(),
      crossFilter: r.crossfilter, active: r.active !== "0" });
  });
  t("smsources").forEach(function (r) {
    var mo = model(r.item); if (!mo) return;
    table(mo, r.table).sources.push({ reference: r.reference, item: r.sourceitem, schema: r.sourceschema, object: r.sourceobject,
      node: r.sourceitem ? m.byIdentity.get(identityKey(r.sourceitem, r.sourceschema, r.sourceobject)) || null : null });
  });
  md.models.forEach(function (mo) {
    mo.tables.forEach(function (tb) {
      tb.columns.sort(function (a, b) { return compare(a.column, b.column); });
      tb.measures.sort(function (a, b) { return compare(a.measure, b.measure); });
    });
    var root = null;
    m.nodes.forEach(function (n) { if (n.item === mo.item && n.kind === KIND.MODEL) root = n; });
    mo.node = root;
  });
  m.meta = md;
  return md;
}

function splitList(text) { return text ? String(text).split(",").map(function (s) { return s.trim(); }).filter(Boolean) : []; }

/* Tables of a model in authored TMDL order, or alphabetically. */
function modelTables(mo, order) {
  var list = Array.from(mo.tables.values());
  list.sort(order === "alphabetical" || list.some(function (tb) { return tb.ordinal === null; })
    ? function (a, b) { return compare(a.name, b.name) || (a.name < b.name ? -1 : 1); }
    : function (a, b) { return a.ordinal - b.ordinal; });
  return list;
}

/* Searchable items and objects, plus semantic tables, columns and measures. */
function dictionaryEntries(m) {
  if (m.entries) return m.entries;
  var md = metadata(m), out = [];
  visibleItems(m).forEach(function (it) {
    if (!it.nodes.length && !it.target) return;
    out.push({ kind: "Item", label: it.name, meta: it.type + (it.target && it.target !== it.name ? " · " + it.target : "") + (CATALOGUES.size > 1 && it.catalogue ? " · " + it.catalogue : ""), desc: "", item: it.label, ref: it });
  });
  m.nodes.forEach(function (n) {
    out.push({ kind: n.kind, label: n.label, meta: n.kind + " · " + shownItem(n.item), desc: n.desc, item: n.item, ref: n, qualified: qualified(n) });
  });

  md.models.forEach(function (mo) {
    mo.tables.forEach(function (tb) {
      out.push({ kind: "Semantic table", label: tb.name, meta: "Semantic table · " + mo.name, desc: tb.description || "", item: mo.item, ref: tb });
      tb.columns.forEach(function (c) {
        out.push({ kind: "Semantic column", label: c.column, meta: "Semantic column · " + tb.name + " · " + mo.name, desc: c.description || "", item: mo.item, ref: c, table: tb });
      });
      tb.measures.forEach(function (c) {
        out.push({ kind: "Measure", label: c.measure, meta: "Measure · " + tb.name + " · " + mo.name, desc: c.description || "", item: mo.item, ref: c, table: tb });
      });
    });
  });
  out.forEach(function (e) {
    e.lower = e.label.toLowerCase(); e.descLower = e.desc.toLowerCase(); e.metaLower = e.meta.toLowerCase();
    e.nameLower = e.ref && e.ref.key && e.ref.object ? e.ref.object.toLowerCase() : e.lower;
  });
  m.entries = out;
  return out;
}

function searchEntries(entries, query, kind) {
  var terms = String(query || "").toLowerCase().split(/\s+/).filter(Boolean), found = [];
  entries.forEach(function (e) {
    if (kind && kind !== "All" && e.kind !== kind) return;
    var score = 0;
    for (var i = 0; i < terms.length; i++) {
      var term = terms[i], s = 0, w = wildcard(term);
      if (w) s = w.test(e.lower) || w.test(e.nameLower) ? 70 : 0;
      else if (e.lower === term || e.nameLower === term) s = 100;
      else if (e.lower.indexOf(term) === 0 || e.nameLower.indexOf(term) === 0) s = 80;
      else if ((" " + e.lower.replace(/[._/\-]/g, " ")).indexOf(" " + term) >= 0) s = 60;
      else if (e.lower.indexOf(term) >= 0) s = 40;
      else if (e.metaLower.indexOf(term) >= 0) s = 20;
      else if (e.descLower.indexOf(term) >= 0) s = 10;
      if (!s) return;
      score += s;
    }
    found.push({ e: e, score: terms.length ? score : 0 });
  });
  // Items and objects come before semantic columns and measures.
  found.sort(function (a, b) {
    return b.score - a.score || entryRank(a.e) - entryRank(b.e) || compare(a.e.label, b.e.label) || compare(a.e.meta, b.e.meta);
  });
  return found.map(function (f) { return f.e; });
}

var ENTRY_RANK = { "Item": 0, "Semantic table": 2, "Semantic column": 3, "Measure": 3 };

function entryRank(e) { return e.kind in ENTRY_RANK ? ENTRY_RANK[e.kind] : 1; }

function entityNode(m, id, declared) {
  var parts = id.split("|"), existing = m.byIdentity.get(id);
  if (existing) return existing;
  var shortcut = (m.tables.entityshortcuts || []).some(function (r) {
    return r.item === parts[0] && (/^schema$/i.test(r.type)
      ? (r.schema ? r.schema + "/" : "") + r.object === parts[1]
      : r.schema === parts[1] && r.object === parts[2]);
  });
  return { id: id, key: id, item: parts[0], schema: parts[1], object: parts[2],
    label: parts[1].replace(/^Tables\//, "") + "." + parts[2],
    kind: shortcut ? KIND.SHORTCUT : declared && /^view$/i.test(declared.type) ? KIND.VIEW : KIND.TABLE,
    desc: declared && declared.description || "", change: metadata(m).borrowed.has(id) ? CHANGE.BORROWED : null };
}

function entityEntries(m) {
  var md = metadata(m), out = [];
  erGraph(m, "all").nodes.forEach(function (node) {
    var n = node.owner, declared = md.tables.get(node.id);
    var e = { kind: n.kind === KIND.SHORTCUT ? "Shortcut" : declared && /^view$/i.test(declared.type) ? "View" : "Table",
      label: n.label, meta: shownItem(n.item), desc: declared && declared.description || "", item: n.item, ref: n };
    e.lower = e.label.toLowerCase(); e.nameLower = n.object.toLowerCase(); e.metaLower = e.meta.toLowerCase(); e.descLower = e.desc.toLowerCase();
    out.push(e);
  });
  return out;
}

var ENTITY_KINDS = ["All", "Table", "View", "Shortcut"];
var SEMANTIC_TYPES = ["SemanticModel", "Report"];

/* The meaning of the landed and curated data: the declared relationships
   between Lakehouse and Warehouse objects, and their dictionary. The Semantic
   model page is its counterpart for models. */
function entitiesPage(body, m) {
  var s = pageState("entities");
  s.kind = ENTITY_KINDS.indexOf(s.kind) >= 0 ? s.kind : "All"; s.query = s.query || ""; s.er = s.er || {};
  var pick = pageItems(m, "entities", DETAIL_KINDS, false), chosen = pick.set;
  var allEntries = entityEntries(m), scope = erGraph(m, chosen).nodes;
  var entries = allEntries.filter(function (e) { return scope.has(e.ref.id); });
  var counts = {};
  entries.forEach(function (e) { counts[e.kind] = (counts[e.kind] || 0) + 1; });

  var picker = pick.chooser;
  var search = searchBox({
    placeholder: "Search " + fmt(entries.length) + " tables and views · * matches any text · Shift adds",
    find: function (q) {
      return q.trim() ? searchEntries(entries, q, "All").slice(0, 12).map(function (e) { return { kind: e.kind, label: e.label, meta: e.meta, desc: e.desc, entry: e }; }) : [];
    },
    onPick: function (r, adding) { choose(r.entry, adding); },
    onPattern: function (q) { er.addPattern(q); }
  });

  var er = erWorkspace(body, m, s.er, { item: chosen, tools: [picker, search], describe: renderSide,
    // A wildcard term selects the objects it names.
    matches: function (q) { return searchEntries(entries, q, "All").filter(function (e) { return e.ref && e.ref.key; }).map(function (e) { return e.ref.id; }); },
    onPick: function (id) {
    var entry = tableEntry(id);
    s.selected = entry ? entryId(entry) : null;
    renderSide(); renderList();
    saveState();
  } });

  var facets = el("div", { "class": "wd-facets", role: "radiogroup", "aria-label": "Entry kind" });
  var input = el("input", { "class": "wd-search wd-search-wide", type: "search", value: s.query, placeholder: "Filter " + fmt(entries.length) + " entries by name, kind or description · * matches any text", "aria-label": "Filter the dictionary", autocomplete: "off", spellcheck: "false" });
  var list = el("div", { "class": "wd-entry-list", role: "listbox" }), note = el("div", { "class": "wd-status-line" });
  var detail = el("div", { "class": "wd-entry-detail", "aria-label": "Table definition" });
  body.appendChild(section("Dictionary", [el("div", { "class": "wd-toolbar" }, [input]), facets, note,
    el("div", { "class": "wd-dictionary" }, [list, detail])]));
  function tableEntry(id) { return entries.filter(function (e) { return e.ref && e.ref.key && e.ref.id === id; })[0] || null; }
  function tableOf(e) {
    if (e.ref && e.ref.key) return e.ref.id;

    return null;
  }
  function current() { return allEntries.filter(function (e) { return entryId(e) === s.selected; })[0] || null; }
  function renderFacets() {
    facets.textContent = "";
    ENTITY_KINDS.forEach(function (k) {
      if (k !== "All" && !counts[k]) return;
      facets.appendChild(el("button", { type: "button", role: "radio", "class": "wd-facet", "aria-checked": String(s.kind === k),
        onclick: function () { s.kind = k; renderFacets(); renderList(); saveState(); } },
        [k === "All" ? null : kindMark(k), k + " ", el("span", { "class": "wd-facet-count", text: fmt(k === "All" ? entries.length : counts[k]) })]));
    });
  }
  function renderList() {
    var found = searchEntries(entries, s.query, s.kind), shown = found.slice(0, 100);
    list.textContent = "";
    note.textContent = found.length > 100 ? "Showing the first 100 of " + fmt(found.length) + " matches. Refine the filter to narrow them." : fmt(found.length) + (found.length === 1 ? " match" : " matches");
    shown.forEach(function (e) {
      var n = e.ref;
      list.appendChild(el("button", { type: "button", role: "option", "class": "wd-entry" + changeClass(n), "aria-selected": String(s.selected === entryId(e)),
        onclick: function () { choose(e, false); } }, [
        el("span", { "class": "wd-entry-label" }, [kindMark(e.kind), e.label, e.ref && e.ref.key ? changeMark(e.ref) : null]),
        el("span", { "class": "wd-entry-meta", text: e.meta }),
        e.desc ? el("span", { "class": "wd-entry-desc", text: e.desc }) : null
      ]));
    });
    if (!shown.length) list.appendChild(empty("Nothing matches. Try fewer words, or another kind."));
  }
  /* One selection: SQL preview beside the graph, full column dictionary below it. */
  function choose(e, adding) {
    s.selected = entryId(e);
    var id = tableOf(e);
    if (id && er.has(id)) er.select(id, adding);
    else if (id) er.say(e.label + " is not a declared table in the items shown");
    renderSide(); renderList();
    saveState();
  }
  function renderSide(panel) {
    panel = panel || er.side;
    var e = current();
    if (e) entityDetail(panel, m, e, "columns");
    else { panel.textContent = ""; panel.appendChild(empty("Select a table to preview its SQL columns.")); }
    if (detail) {
      if (e) entityDetail(detail, m, e, "details");
      else { detail.textContent = ""; detail.appendChild(empty("Select a table to see its definition, keys and column descriptions.")); }
    }
  }

  input.addEventListener("input", function () { s.query = input.value; renderList(); saveState(); });
  renderFacets(); renderList(); renderSide();
}

function entryId(e) {
  if (e.kind === "Item") return "item|" + e.item;
  if (e.ref && e.ref.key) return "node|" + e.ref.key;

  if (e.kind === "Semantic table") return "smt|" + e.item + "|" + e.ref.name;
  return e.kind + "|" + e.item + "|" + (e.table ? e.table.name : "") + "|" + e.label;
}

function entityDetail(panel, m, e, mode) {
  panel.textContent = "";
  var md = metadata(m), n = e.ref, declared = md.tables.get(n.id) || {};
  panel.appendChild(el("div", { "class": "wd-eyebrow", text: e.kind }));
  panel.appendChild(el("h2", { "class": "wd-detail-title", text: e.label }));
  panel.appendChild(el("div", { "class": "wd-muted", text: shownItem(e.item) }));
  if (mode !== "columns" && declared.description) panel.appendChild(el("p", { "class": "wd-desc", text: declared.description }));
  var keys = (declared.primarykey ? [{ type: "Primary key", columns: declared.primarykey }] : []).concat(md.keys.get(n.id) || []);
  if (mode !== "columns" && keys.length) {
    panel.appendChild(el("h3", { "class": "wd-h3", text: "Keys" }));
    panel.appendChild(el("ul", { "class": "wd-list wd-mono" }, keys.map(function (k) { return el("li", { text: k.type + " (" + k.columns + ")" }); })));
  }
  var columns = md.types.get(n.id), notes = md.columns.get(n.id) || [];
  if (!columns) {
    panel.appendChild(el("p", { "class": "wd-note", text: "SQL column inventory unavailable. Build this item to collect it." }));
    columns = notes;
  }
  if (columns.length) {
    panel.appendChild(el("h3", { "class": "wd-h3", text: (md.types.has(n.id) ? "Columns" : "Described columns") + " · " + columns.length }));
    var fields = [
      { key: "ordinal", title: "#", value: function (c) { return c.ordinal; }, numeric: true, sortable: false },
      { key: "column", title: "Column", value: function (c) { return c.column; }, sortable: false },
      { key: "datatype", title: "SQL type", value: function (c) { return c.datatype || "—"; }, sortable: false },
      { key: "nullable", title: "Nullable", value: function (c) { return c.nullable === null || c.nullable === undefined ? "—" : c.nullable === "1" ? "Yes" : "No"; }, sortable: false }
    ];
    if (mode !== "columns") fields.push({ key: "description", title: "Description", value: function (c) { return c.description || ""; }, sortable: false });
    panel.appendChild(dataTable(fields, columns, { limit: columns.length, sort: null }));
  }
}
