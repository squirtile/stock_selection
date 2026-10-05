# Research Workbench Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add search, browser-local watchlists and alerts, score explanations, strategy comparison, market breadth, stock research, and source-health visibility without changing strategy behavior.

**Architecture:** A read-only Python aggregation module exposes four JSON endpoints, while a separate progressive-enhancement JavaScript file adds browser-local personalization and research UI to the existing Flask/Jinja page. Existing scanners and APIs remain untouched, and each new data source degrades independently.

**Tech Stack:** Python 3.10, Flask, Jinja2, vanilla JavaScript, CSS, unittest, Node syntax checks

**Spec:** `docs/superpowers/specs/2026-10-05-research-workbench-features-design.md`

## Global Constraints

- Keep the registered website name “策略实验室” unchanged.
- Do not modify strategy implementations, scan conditions, score thresholds, registry contents, or scheduler behavior.
- Treat all new backend operations as read-only and tolerate missing, stale, or malformed files.
- Store watchlists and read alert IDs in browser localStorage only; do not add authentication.
- Explain existing scores without recalculating or overwriting them.
- Preserve all current page navigation, filtering, intraday refresh, K-line, and money-flow behavior.

## Review Focus

- Malformed or partially written JSON/CSV must degrade one source, not break the overview endpoint.
- Search must deduplicate the same six-digit code across daily, intraday, and snapshot sources.
- Future-dated or stale local files must be labeled by their embedded data date where available, not silently treated as current.
- Invalid/oversized query parameters and stock codes must return bounded, safe responses.
- localStorage denial or corrupt stored JSON must fall back to an empty in-memory watchlist.

---

### Task 1: Read-only research aggregation

**Files:**
- Create: `tools/research_workspace.py`
- Create: `test/test_research_workspace.py`

**Interfaces:**
- Produces: `build_workspace_overview(project_root, now=None) -> dict`
- Produces: `search_stocks(project_root, query, limit=20) -> list[dict]`
- Produces: `build_stock_research(project_root, code) -> dict | None`
- Produces: `build_watchlist_alerts(project_root, codes) -> list[dict]`

- [ ] Write tests for breadth calculation, source freshness, malformed source isolation, search deduplication, score explanation, research aggregation and stable alert IDs.
- [ ] Run `PYTHONPATH=. python3 -m unittest test.test_research_workspace -v` and confirm failures are caused by the missing module.
- [ ] Implement the four interfaces using only local files and bounded inputs.
- [ ] Re-run the test command and confirm it passes.
- [ ] Commit the module and tests.

### Task 2: Flask endpoints and page data contract

**Files:**
- Modify: `api_server.py`
- Modify: `web/views.py`
- Create: `test/test_research_workspace_api.py`

**Interfaces:**
- Consumes: all four Task 1 aggregation interfaces.
- Produces: `/api/workspace/overview`, `/api/stocks/search`, `/api/stock/<code>/research`, `/api/workspace/alerts`.
- Produces: `strategyHistoryJson` and `stockCatalogJson` Jinja values without mutating strategy data.

- [ ] Write API tests for success, empty search, invalid code, bounded code list and degraded overview.
- [ ] Run `PYTHONPATH=. python3 -m unittest test.test_research_workspace_api -v` and confirm route failures.
- [ ] Add routes and template context, keeping existing routes byte-compatible in behavior.
- [ ] Re-run API and existing web tests.
- [ ] Commit endpoint changes.

### Task 3: Search, watchlist, alerts and research drawer

**Files:**
- Create: `static/research_workspace.js`
- Modify: `web/templates/index.html`
- Modify: `static/workspace.css`
- Create: `test/test_research_workspace_ui.py`

**Interfaces:**
- Consumes: Task 2 endpoints and embedded Jinja values.
- Produces: global search UI, `个人观察` panel, card action buttons, notification center, source drawer and stock research drawer.

- [ ] Write rendered-DOM tests for landmarks, preserved site name/navigation order, external script loading and accessible controls.
- [ ] Write Node-executed tests for localStorage corruption fallback, watchlist toggling and alert deduplication.
- [ ] Run the UI tests and confirm missing markup/module failures.
- [ ] Implement progressive enhancement and responsive styling without replacing existing card click handling.
- [ ] Re-run UI, existing web tests and `node --check static/research_workspace.js`.
- [ ] Commit the UI feature set.

### Task 4: Strategy comparison and market/source dashboard

**Files:**
- Modify: `static/research_workspace.js`
- Modify: `web/templates/index.html`
- Modify: `static/workspace.css`
- Modify: `test/test_research_workspace_ui.py`

**Interfaces:**
- Consumes: `strategyHistoryJson` and `/api/workspace/overview`.
- Produces: 2–4 strategy comparison view, market breadth cards and detailed source-health list.

- [ ] Add failing DOM/JavaScript tests for comparison selection limits, metric rendering and degraded overview states.
- [ ] Implement the comparison and overview renderers.
- [ ] Re-run UI and full relevant regression tests.
- [ ] Commit comparison/dashboard changes.

### Task 5: Integrated verification and service handoff

**Files:**
- Modify only if an integration test exposes a defect.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a deployable, backwards-compatible research workbench.

- [ ] Run Python compile checks, all new unit tests, existing web/card/scanner unit tests, template-rendered inline JavaScript syntax checks, external JavaScript syntax checks and `git diff --check`.
- [ ] Restart `stock-api.service`, verify `/api/health`, all four new endpoints and the rendered page.
- [ ] Perform a whole-change review against the spec and fix all Critical/Important findings with RED-GREEN tests.
- [ ] Commit any integration fixes and report final status; push only if explicitly authorized.
