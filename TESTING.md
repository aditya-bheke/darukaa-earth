# Testing

Two layers: an automated suite that runs in CI, and a manual pass over the web app (the parts a
browser can break: gestures, rendering, caching, layout).

```bash
pytest                              # 42 unit / integration / API tests
python eval/run_eval.py --no-llm    # 11 behavioural scenarios, deterministic
python eval/run_eval.py             # the same scenarios through the configured LLM
ruff check .                        # lint
node --check frontend/app.js        # front-end syntax
```

## Automated coverage

| Area | Examples |
|---|---|
| Knowledge base | every citation resolves; each practice has effects and monitoring; PDFs carry real citations; retrieval finds the expected passage and returns diverse sources |
| Parsing | the brief's example text and JSON; numbers, coordinates, areas; organic matter converted to organic carbon; questions are not parsed as site data |
| Reasoning | diagnosis thresholds; causal chains; multi-issue rule; water-consuming practices excluded in drylands; contraindications; prerequisites; projections scaled to the site; value-of-information ranking |
| Conversation | clarifying questions; memory across engine instances; skip handling; follow-up answers; stale sibling values cleared |
| Grounding | unsupported numbers and unknown citations removed, including parenthesised and grouped forms |
| API & front end | `/chat`, `/sessions`, history list/delete, `/knowledge/*`, static assets served, old payloads still validate, rebuilds preserve conversations |

## Manual web-app pass (2026-09-18)

Run against `uvicorn api:app` with the Groq LLM live, in Chromium.

| # | Case | Expected | Result |
|---|---|---|---|
| 1 | Routes: `/`, `/app/`, assets, `/docs`, `/sessions`, `/knowledge/search` | 307 redirect + 200s | pass |
| 2 | Vague opener ("Biodiversity is declining") | clarifying questions, no asterisk markup, known-variable chip | pass — 3 questions, asks soil carbon first |
| 3 | Full site description | diagnosis, causal chains, recommendations, action plan, projections, citations, downloads, retrieval trace | pass — 5 findings, 5 chains, 5 recommendations, 4 phases |
| 4 | Recommendation sheet | 7 sections incl. projections and monitoring, references, citation chips | pass — 3 metrics, 6 monitoring rows, 4 references |
| 5 | Sheet gesture | 1:1 drag, flick dismisses, scrim and shell restore | pass |
| 6 | Follow-up question ("why not cover crops?") | grounded answer, no new assessment | **failed, then fixed** — see note 1 |
| 7 | History panel | list with titles, age, message counts, site chips | pass — open and delete both work |
| 8 | Delete a conversation | confirmation, row removed, server deletes | pass |
| 9 | Reopen from history | `?session=…`, transcript restored | pass — 3 messages, 10 cards |
| 10 | New button / refresh | clean page, hero, resume link, session parked | pass |
| 11 | Knowledge search | 6 hits with dense and BM25 ranks | pass |
| 12 | Practice sheet from Knowledge | action, mechanism, effects, monitoring | pass |
| 13 | Method tab | 10 pipeline steps | pass |
| 14 | Invalid JSON input | toast with parser message, sheet stays open | pass |
| 15 | Valid JSON input | sheet closes, assessment rendered, JSON echoed in the bubble | pass — 4 recommendations |
| 16 | Coordinates lookup | SoilGrids / Open-Meteo / GBIF values with provenance, user values not overwritten | pass — rainfall, temperature, 844 GBIF species; user's soil carbon kept |
| 17 | Mobile 375 px | no horizontal overflow, tabs fit, composer visible | **failed, then fixed** — see note 2 |
| 18 | Accessibility | tab roles and `aria-selected`, labelled icon buttons, dialog role, polite live region | pass |
| 19 | Console errors across the whole pass | none | pass |
| 20 | Light and dark themes | both legible, translucency intact | pass |

### Note 1 — questions were treated as new site data
"Why not cover crops?" made the LLM extractor set `goal: "introduce cover crops"`. The profile changed,
so the engine re-ran a full assessment instead of answering. Fixed by detecting question-shaped
messages, ignoring non-material fields (`goal`, `region`, `area_ha`) for the recompute decision, and
instructing the extractor to return nothing for questions. Covered by
`test_questions_do_not_become_site_data`.

### Note 2 — status line wrapped on narrow screens
The header's model/counts line wrapped into the brand at 375 px. The counts are now hidden below
560 px, and the line is kept to a single row. While fixing it, the browser kept serving a cached
stylesheet, so `/app/*` responses now send `Cache-Control: no-cache` (ETags keep it to a 304) —
otherwise a demo can silently run against stale assets.

## Not automated

- `prefers-reduced-motion`, `prefers-reduced-transparency` and `prefers-contrast` paths are
  implemented and reviewed, but not exercised in this pass (the test browser cannot emulate those media features).
- Haptics (`navigator.vibrate`) fire only after a real user gesture, so they are untested in automation.
- Deployment (Render blueprint, Docker image) is built and smoke-tested in CI, not locally.
