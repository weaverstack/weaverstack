// Start-up. Power BI renders the visual again on every refresh; view state
// lives on the window and, where the host allows it, in session storage, so a
// refresh keeps the focus, the depths and the viewport.

var PAGES = {
  workspaces: workspacesPage, overview: overviewPage, health: healthPage, orchestration: orchestrationPage, gantt: ganttPage,
  performance: performancePage, entities: entitiesPage, semantic: semanticPage
};
var STORE = "weaver-dashboard-state";
/* View state is kept per set of catalogues, so one Dashboard's focus never
   lands on another's objects. */
var STATE_VERSION = 2;
function storeKey(m) {
  return STORE + ":" + STATE_VERSION + ":" + (m && m.catalogues ? m.catalogues.map(function (c) { return c.reference; }).sort().join("|") : "");
}

var STATE_KEY = STORE;
function saveState() {
  try { root.sessionStorage.setItem(STATE_KEY, JSON.stringify(state())); } catch (e) { /* unavailable */ }
}

function restoreState(m) {
  STATE_KEY = storeKey(m);
  if (root.__WD_STATE && root.__WD_STATE_KEY === STATE_KEY) return;
  root.__WD_STATE = null;
  root.__WD_STATE_KEY = STATE_KEY;
  try {
    var raw = root.sessionStorage.getItem(STATE_KEY);
    if (raw) root.__WD_STATE = JSON.parse(raw);
  } catch (e) { /* unavailable */ }
}

function start() {
  if (typeof document === "undefined") return;
  var mount = document.getElementById("wd-app"), source = document.getElementById("wd-data");
  if (!mount) return;
  var parsed = parsePayload(source ? source.textContent : ""), m = buildModel(parsed.tables, parsed.problems);
  restoreState(m);
  if (!source) m.problems.push("The page carries no catalogue data.");
  function render() {
    var scroller = scrollBox(mount), scroll = scroller ? scroller.scrollTop : root.scrollY || 0;
    mount.textContent = "";
    mount.className = "wd wd-page-" + m.page;
    var body = shell(mount, m);
    try {
      if (m.tooLarge) tooLargePage(body, m);
      else (PAGES[m.page] || overviewPage)(body, m);
    } catch (error) {
      body.appendChild(el("pre", { "class": "wd-error", text: "This page could not be drawn: " + (error && error.message) }));
    }
    if (scroll && scroller) scroller.scrollTop = scroll;
    else if (scroll && root.scrollTo) root.scrollTo(0, scroll);
    saveState();
  }
  root.__WD_REDRAW = render;
  render();
  root.addEventListener("pagehide", saveState);
}

var api = {
  parsePayload: parsePayload, buildModel: buildModel, assessHealth: assessHealth, readiness: readiness,
  layoutEstate: layoutEstate, WINDOW_GEOMETRY: WINDOW_GEOMETRY, subModel: subModel, focusWindow: focusWindow, searchNodes: searchNodes, nodeMatches: nodeMatches, dictionaryEntries: dictionaryEntries,
  searchEntries: searchEntries, metadata: metadata, modelTables: modelTables, busMatrix: busMatrix, erGraph: erGraph,
  erWindow: erWindow, erLayout: erLayout, ER: ER, ganttSummary: ganttSummary, clockTicks: clockTicks, clockLabel: clockLabel, canvasRatio: canvasRatio, duration: duration, stamp: stamp, wallOf: wallOf, instantOf: instantOf, zoneLabel: zoneLabel, logRows: logRows, perfRows: perfRows, performanceCard: performanceCard, largestRows: largestRows, runStatRows: runStatRows, sortRows: sortRows, taskRank: taskRank, runsOf: runsOf, runObjectRows: runObjectRows, runView: runView, dayStartHour: dayStartHour, testRows: testRows, recordKind: recordKind, tone: tone, BUDGET: BUDGET,
  estateTopology: estateTopology, loopsOf: loopsOf, topologyColumns: topologyColumns,
  joinCatalogues: joinCatalogues, components: components, keysOf: keysOf, scopeSelection: scopeSelection, eligibleItems: eligibleItems, chosenItems: chosenItems, stableItem: stableItem, shownItem: shownItem, storeKey: storeKey,
  FIELD: FIELD, ROW: ROW, TABLE: TABLE, LESS: LESS, OWNER: OWNER
};
if (typeof module === "object" && module && module.exports) module.exports = api;
else { root.WeaverDashboard = api; start(); }
