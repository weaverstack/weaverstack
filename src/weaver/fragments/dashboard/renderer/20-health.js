// Health, as weaver.health assesses it from the catalogue alone. The codes,
// severities and rules are Python's; tests/js and the parity test hold them
// together. What only `weaver health` can observe is reported as unassessed.

var GREEN = "green", AMBER = "amber", RED = "red";
var SEVERITY_RANK = { green: 0, amber: 1, red: 2 };
var DEFAULT_AGE_MS = 24 * 3600 * 1000;
var LOAD_RED = ["Failed", "Error", "Blocked"];
var NO_DATA = ["Failed", "Error", "Blocked", "Pending"];
var ESTABLISHED = ["Succeeded", "Rejected", "Skipped"];

function isView(n) { return n.kind === KIND.VIEW; }
/* Observation, not execution: a loadable, a mirrored object and a View carry
   load state. A View settles when its build succeeds. */
function participates(n) { return n.canLoad || n.isMirrored || isView(n); }
function isLoadSubject(n) { return (n.canLoad || n.isMirrored) && !isView(n); }

/* A mirrored object's state is recorded in the catalogue it mirrors: the
   source object's, where the Dashboard reads that catalogue. */
function effectiveLoad(n) {
  if (!n.isMirrored) return n.load;
  return n.mirror && n.mirror.source ? n.mirror.source.load : null;
}
function mirrorObserved(n) { return !!(n.mirror && n.mirror.read); }

function establishedAt(n) {
  var s = effectiveLoad(n);
  return s && ESTABLISHED.indexOf(s.result) >= 0 ? s.completed : null;
}

/* Strongly connected components: nodes that read one another share one. Each
   node maps to its component's index; components come out with every upstream
   component before them. */
function components(m) {
  if (m.components) return m.components;
  var index = new Map(), low = new Map(), on = new Set(), stack = [], comp = new Map(), list = [], counter = 0;
  function connect(start) {
    var work = [[start, 0]];
    index.set(start, counter); low.set(start, counter); counter += 1; stack.push(start); on.add(start);
    while (work.length) {
      var top = work[work.length - 1], key = top[0], ups = m.nodes.get(key).up;
      if (top[1] < ups.length) {
        var u = ups[top[1]++];
        if (!index.has(u)) {
          index.set(u, counter); low.set(u, counter); counter += 1; stack.push(u); on.add(u);
          work.push([u, 0]);
        } else if (on.has(u)) low.set(key, Math.min(low.get(key), index.get(u)));
        continue;
      }
      work.pop();
      if (work.length) { var parent = work[work.length - 1][0]; low.set(parent, Math.min(low.get(parent), low.get(key))); }
      if (low.get(key) === index.get(key)) {
        var members = [], w;
        do { w = stack.pop(); on.delete(w); comp.set(w, list.length); members.push(w); } while (w !== key);
        list.push(members);
      }
    }
  }
  Array.from(m.nodes.keys()).sort().forEach(function (k) { if (!index.has(k)) connect(k); });
  m.components = { of: comp, list: list };
  return m.components;
}

function sameCycle(m, a, b) { var c = components(m).of; return c.get(a) === c.get(b); }

/* Over each node's lifecycle ancestors: whether one has not been processed,
   the latest instant one outside its cycle was processed, and the latest one
   was processed or built. Members of a cycle count as each other's ancestors
   for what has not been processed, never for what is newer. */
function ancestry(m) {
  var c = components(m), out = new Map();
  function empty() { return { unprocessed: false, latest: null, changed: null }; }
  function merge(a, b) { if (b.unprocessed) a.unprocessed = true; a.latest = later(a.latest, b.latest); a.changed = later(a.changed, b.changed); }
  function own(p) {
    var r = empty();
    if (participates(p)) {
      var at = establishedAt(p);
      if (at === null) r.unprocessed = true;
      r.latest = at;
      r.changed = later(at, p.built);
    }
    return r;
  }
  // Tarjan emits a component after every component it reads. full[i] is what
  // a reader of any member of component i inherits: the members and their
  // ancestry, since every member is an ancestor of every other.
  var full = [];
  c.list.forEach(function (members, i) {
    var upstream = empty(), seen = new Set();
    members.forEach(function (key) {
      m.nodes.get(key).up.forEach(function (u) {
        var j = c.of.get(u);
        if (j === i || seen.has(j)) return;
        seen.add(j);
        merge(upstream, full[j]);
      });
    });
    var whole = { unprocessed: upstream.unprocessed, latest: upstream.latest, changed: upstream.changed };
    members.forEach(function (key) { merge(whole, own(m.nodes.get(key))); });
    full[i] = whole;
    members.forEach(function (key) {
      var a = { unprocessed: upstream.unprocessed, latest: upstream.latest, changed: upstream.changed };
      if (members.length > 1) members.forEach(function (other) {
        if (other === key) return;
        var o = own(m.nodes.get(other));
        if (o.unprocessed) a.unprocessed = true;
        a.changed = later(a.changed, o.changed);
      });
      out.set(key, a);
    });
  });
  return out;
}

function later(a, b) { return a === null ? b : b === null ? a : Math.max(a, b); }

function ancestorsOf(m, key) {
  var seen = new Set([key]), stack = [key], out = [];
  while (stack.length) {
    m.nodes.get(stack.pop()).up.forEach(function (u) { if (!seen.has(u)) { seen.add(u); out.push(m.nodes.get(u)); stack.push(u); } });
  }
  return out;
}

function firstAncestor(m, key, test) {
  var found = ancestorsOf(m, key).filter(function (a) { return participates(a) && test(a); });
  found.sort(function (a, b) { return compare(a.id, b.id); });
  return found[0] || null;
}

/* The unprocessed ancestor named as the cause: a failed load before a Pending one. */
var CAUSES = ["Failed", "Error", "Blocked"];
function causeRank(p) { var s = effectiveLoad(p), i = s ? CAUSES.indexOf(s.result) : -1; return i < 0 ? CAUSES.length : i; }
function firstCause(m, key) {
  var found = ancestorsOf(m, key).filter(function (a) { return participates(a) && establishedAt(a) === null; });
  found.sort(function (a, b) { return causeRank(a) - causeRank(b) || compare(a.id, b.id); });
  return found[0] || null;
}
function unestablished(p) {
  if (!p) return "an upstream object has not been processed since it was built";
  var s = effectiveLoad(p), result = s ? s.result : "Pending";
  if (result === "Failed") return "the last load of " + p.label + " failed";
  if (result === "Error") return "the last load of " + p.label + " raised an error";
  if (result === "Blocked") return "the last load of " + p.label + " was blocked";
  return p.label + " has not been processed since it was built";
}

function finding(area, code, severity, node, result, message, s) {
  return { area: area, code: code, severity: severity, node: node, result: result, message: message,
    workflow: s ? s.workflow : null, completed: s ? s.completed : null, unobserved: false };
}

function assessHealth(m, options) {
  options = options || {};
  var asOf = options.asOf !== undefined ? options.asOf : m.at - DEFAULT_AGE_MS;
  // green holds each subject an area finds nothing about, apart from the findings.
  var anc = ancestry(m), load = [], tests = [], build = [], green = [];
  var counts = { load: { subjects: 0 }, tests: { subjects: 0 }, build: { subjects: 0 } };
  m.nodes.forEach(function (n) {
    counts.build.subjects += 1;
    if (isLoadSubject(n)) {
      counts.load.subjects += 1;
      var lf = loadFindings(m, n, anc, asOf), s = effectiveLoad(n);
      load.push.apply(load, lf);
      if (!lf.length) green.push(finding("load", "load_current", GREEN, n, s.result, "the last load " + s.result + (n.isStatic ? "; loaded once" : "; current with its dependencies"), s));
    }
    if (isValidation(n)) {
      counts.tests.subjects += 1;
      var tf = testFindings(m, n, anc);
      tests.push.apply(tests, tf);
      if (!tf.length) green.push(finding("tests", "test_current", GREEN, n, n.test.result, "the last run " + n.test.result + "; current with its dependencies", n.test));
      if (!n.isInstalled) build.push(finding("build", "missing_validation_artefact", RED, n, null, "its definition or artefact is not installed; build the item again"));
      else green.push(finding("build", "build_installed", GREEN, n, null, "installed and current"));
    } else green.push(finding("build", "build_installed", GREEN, n, null, "installed and current"));
  });
  // Objects that read one another are reported once per cycle, as weaver.health does.
  components(m).list.forEach(function (members) {
    if (members.length < 2) return;
    var nodes = members.map(function (k) { return m.nodes.get(k); }).sort(function (a, b) { return compare(a.id, b.id); });
    build.push(finding("build", "dependency_cycle", GREEN, nodes[0], null,
      "These objects read one another, so each loads once and the first reads what the last loaded before: " + nodes.map(function (n) { return n.label; }).join(", ")));
  });
  (m.tables.uncertified || []).forEach(function (r) {
    if (!m.items.has(r.item) || m.items.get(r.item).internal || !m.items.get(r.item).target) return;
    build.push({ area: "build", code: "not_installed", severity: RED, node: null, label: r.item + " " + r.schema + "." + r.object,
      item: r.item, schema: r.schema, object: r.object,
      result: null, message: "declared in the dictionary, but not certified in Registry", unobserved: false });
  });
  [load, tests, build].forEach(function (list) { list.sort(byFinding); });
  return { asOf: asOf, at: m.at, load: load, tests: tests, build: build, counts: counts,
    all: load.concat(tests, build).sort(byFinding), green: green.sort(byFinding) };
}

function byFinding(a, b) {
  return SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || compare(a.area, b.area) ||
    compare(a.node ? a.node.id : a.label, b.node ? b.node.id : b.label) || compare(a.code, b.code);
}

function loadFindings(m, n, anc, asOf) {
  var s = effectiveLoad(n), out = [];
  if (!s || s.result === "Pending") {
    var unseen = n.isMirrored && !mirrorObserved(n);
    var f = finding("load", "load_pending", AMBER, n, "Pending", unseen ?
      "loaded in the catalogue this one mirrors, which the Dashboard does not read" :
      n.isMirrored ? "the catalogue this one mirrors has not loaded it" :
      "no load has processed this object since it was built", s);
    f.unobserved = unseen;
    return [f];
  }
  if (LOAD_RED.indexOf(s.result) >= 0) return [finding("load", "load_failed", RED, n, s.result, "the last load " + s.result, s)];
  if (s.result === "Rejected") out.push(finding("load", "load_rejected", AMBER, n, s.result, "the last load completed with rejected rows", s));
  if (NO_DATA.indexOf(s.result) >= 0 || n.isStatic) return out;
  if (s.completed !== null && s.completed < asOf) out.push(finding("load", "load_stale_time", AMBER, n, s.result, "last loaded " + stamp(s.completed), s));
  var a = anc.get(n.key);
  if (a.unprocessed) {
    var behind = firstCause(m, n.key);
    out.push(finding("load", "load_ancestor_unestablished", AMBER, n, s.result, unestablished(behind), s));
  }
  var loaded = establishedAt(n);
  if (loaded !== null && a.latest !== null && a.latest > loaded) {
    var newer = firstAncestor(m, n.key, function (p) { var at = establishedAt(p); return !sameCycle(m, p.key, n.key) && at !== null && at > loaded; });
    out.push(finding("load", "load_stale_ancestor", AMBER, n, s.result,
      (newer ? newer.label : "an upstream object") + " has been established since this object was loaded", s));
  }
  return out;
}

function testFindings(m, n, anc) {
  var s = n.test;
  if (!s) return [finding("tests", "test_pending", AMBER, n, "Pending", "this validation has not run since it was built")];
  if (LOAD_RED.indexOf(s.result) >= 0) return [finding("tests", "test_failed", RED, n, s.result, "the last run " + s.result, s)];
  if (s.result !== "Succeeded") return [finding("tests", "test_pending", AMBER, n, s.result, "the last run " + s.result, s)];
  var at = s.completed, a = anc.get(n.key);
  if (at === null || a.changed === null || a.changed <= at) return [];
  var moved = firstAncestor(m, n.key, function (p) { return (establishedAt(p) || at) > at || (p.built || at) > at; });
  var how = moved && (establishedAt(moved) || at) > at ? "loaded" : "built";
  return [finding("tests", "test_stale_dependency", AMBER, n, s.result,
    (moved ? moved.label : "an upstream object") + " has been " + how + " since this validation passed", s)];
}

function worstOf(list) {
  return list.reduce(function (w, f) { return SEVERITY_RANK[f.severity] > SEVERITY_RANK[w] ? f.severity : w; }, GREEN);
}

/* ---- readiness: derived from recorded dependencies, never a queue -------- */

/* The nearest upstream objects that carry load state, walking through those
   that do not, such as a shortcut. */
function nearestStateful(m, n) {
  var seen = new Set(), stack = n.up.slice(), out = [];
  while (stack.length) {
    var key = stack.pop();
    if (seen.has(key)) continue;
    seen.add(key);
    var p = m.nodes.get(key);
    if (participates(p)) out.push(p);
    else stack.push.apply(stack, p.up);
  }
  return out.sort(function (a, b) { return compare(a.label, b.label); });
}

var READINESS = { CURRENT: "Current", READY: "Ready", WAITING: "Waiting", ELSEWHERE: "Loaded elsewhere", NONE: "Not loaded here" };

/* Readiness keeps apart what happened (the outcome) and whether the recorded
   dependencies would let it run again now. */
function readiness(m, n) {
  if (n.isMirrored) return { state: READINESS.ELSEWHERE, waitingOn: [], unprocessed: 0 };
  if (!n.canLoad) return { state: READINESS.NONE, waitingOn: [], unprocessed: 0 };
  var ups = nearestStateful(m, n), waiting = ups.filter(function (p) { return establishedAt(p) === null; });
  if (waiting.length) return { state: READINESS.WAITING, waitingOn: waiting, unprocessed: waiting.length };
  var loaded = establishedAt(n);
  var behind = loaded === null || ups.some(function (p) { return establishedAt(p) > loaded; });
  return { state: behind ? READINESS.READY : READINESS.CURRENT, waitingOn: [], unprocessed: 0 };
}

function tone(result) {
  switch (result) {
    case "Succeeded": case "Skipped": return "ok";
    case "Failed": case "Error": case "Blocked": return "bad";
    case "Rejected": return "warn";
    case "Pending": return "wait";
    default: return "none";
  }
}
