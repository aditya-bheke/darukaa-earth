# Decisions & Change Log

Every significant design choice and change, **with the reason**. Use this to answer
*"why was it done this way?"* questions. Entries are grouped by build phase, in the order they were made.

---

## Phase 0 — Reading the brief

| # | Decision | Reason (traced to the brief) |
|---|---|---|
| D0.1 | Spend most effort on reasoning, grounding and the knowledge layer; keep the UI thin. | Scoring: Depth of Reasoning 30% + Scientific Grounding 25% + Knowledge System 20% = 75%. The brief says *"We are not looking for UI-heavy applications."* |
| D0.2 | Treat "≥ 3 environmental variables together" and "no single-variable answers" as hard rules in code, not prompt instructions. | Stated twice in the brief (Multi-Metric Reasoning + Constraints). Code rules are testable; prompts are not. |
| D0.3 | Make every recommendation carry *what / why / metric / reference / time horizon / confidence*. | Sections 3 and 6 of the brief make these mandatory (confidence "optional but valuable"). |

---

## Phase 1 — Stack

| # | Decision | Reason |
|---|---|---|
| D1.1 | **Python + Streamlit**, deployed on Streamlit Community Cloud. | Fastest path to a live demo URL (requested in the submission guidelines) with free hosting. |
| D1.2 | **Free LLM via Groq** (OpenAI-compatible client), Gemini as an alternative, and a **deterministic no-LLM mode**. | A free tier keeps the project reproducible at no cost. The OpenAI-compatible interface allows switching providers with one setting. The no-LLM mode proves the system is not "LLM-only" and lets CI run without secrets. |
| D1.3 | **fastembed (ONNX) `bge-small-en-v1.5`** instead of sentence-transformers. | No PyTorch → small install that fits Streamlit Cloud's memory; good retrieval quality for English science text. |
| D1.4 | **NumPy vector matrix + BM25 hybrid** instead of a hosted vector DB. | The corpus is small, so exact search is instant; no extra service to deploy or pay for. BM25 catches exact scientific terms ("SOC", "Faidherbia") that dense search can miss. |
| D1.5 | **SQLite** for structured knowledge *and* conversation memory. | A real relational schema with foreign keys (the README must document a database/schema) at zero operational cost. |
| D1.6 | Knowledge authored as **YAML files**, compiled into SQLite by a build step. | Readable and reviewable in git; the build step validates every citation link, so broken references fail CI. |
| D1.7 | API key stored in `.env` (git-ignored); `.env.example` and `secrets.toml.example` committed instead. | Keeps secrets out of GitHub. |

---

## Phase 2 — Knowledge base

| # | Decision | Reason |
|---|---|---|
| D2.1 | Four layers: **sources → evidence passages → practices/effects → variable relationships**. | Separates *who says it*, *what they found*, *what to do*, and *how variables interact*. Each layer serves a different part of reasoning (see ARCHITECTURE §4). |
| D2.2 | Sources limited to **IPCC, IPBES, FAO, UNCCD and peer-reviewed meta-analyses/landmark studies**, each with a DOI/URL and an evidence **tier**. | The brief names FAO and IPCC as examples of credible sources; tiers feed the confidence score. |
| D2.3 | Evidence passages are **paraphrased**, not copied, and only include figures I am confident the papers report. | Avoids copyright issues and invented numbers. The brief's own example figure ("~15–25% (FAO studies)") was **not** hard-coded because it is an illustrative format, not a verified citation. |
| D2.4 | Quantified effects live in a **structured table** (`practice_effects`) foreign-keyed to their passage. | "Measurable improvement estimates" (brief p.3) must be reproducible, not generated. |
| D2.5 | Practices carry `avoid_when`, `requires`, `water_penalty` and `adaptations`. | Enables non-obvious, context-aware reasoning: the same practice can be good in one site and harmful in another. |
| D2.6 | Added **"avoid" practices** (e.g. water-hungry exotic plantations) and **"restore grassland instead of planting trees"**. | Strong solutions warn against plausible-but-harmful actions; this is where "non-obvious" advice comes from. |
| D2.7 | Added an **optional PDF ingestion path** (`data/raw/`). | The brief says "index research papers, reports, or environmental datasets"; this lets the corpus grow without code changes. |
| D2.8 | Content **fingerprint** triggers an automatic rebuild. | Streamlit Cloud starts from a clean checkout; the index is built on first run and whenever knowledge files change. |

---

## Phase 3 — Reasoning engine

| # | Decision | Reason |
|---|---|---|
| D3.1 | **Threshold diagnosis → issue codes**, each linked to an evidence passage. | Makes the reasoning explainable ("SOC 0.3% is below the 0.5% low band [ev_soc_bands_india]"). |
| D3.2 | SOC bands from the **Indian Soil Health Card** scheme; aridity zones from **UNCCD**; rainfall-mm and 27 °C heat thresholds labelled **heuristic** in the output. | Use cited standards where they exist; be transparent where they don't. |
| D3.3 | **Signed variable graph + BFS causal chains**. | Directly demonstrates "Soil health ↔ biodiversity, water ↔ species survival, land use ↔ fragmentation." |
| D3.4 | A "do" recommendation must address **≥ 2 diagnosed issues**. | Enforces "no single-variable answers" in code. |
| D3.5 | **Water penalty** for water-consuming practices in dry sites, plus **water-first sequencing**. | The key non-obvious insight for the brief's semi-arid example: cover crops, the textbook SOC answer, compete for scarce water. |
| D3.6 | **Confidence** computed from evidence tier minus explicit penalties, with the reason shown. | Brief: confidence is "optional but valuable"; a number without a reason is not explainable. |
| D3.7 | Time horizon bands defined as short < 1 yr, medium 1–5 yr, long > 5 yr. | The brief requires short/medium/long but doesn't define them, so the definitions are stated in every response. |

---

## Phase 4 — LLM & grounding

| # | Decision | Reason |
|---|---|---|
| D4.1 | The LLM only writes the **summary and "why for your site"** text; it never chooses practices or numbers. | Keeps scientific decisions deterministic and testable. |
| D4.2 | **Grounding verifier** removes sentences that cite unknown evidence IDs or contain numbers absent from the evidence or the user's data. | Guards the 25% "Scientific Grounding" criterion against hallucination. |
| D4.3 | **Changed model `llama-3.3-70b-versatile` → `openai/gpt-oss-120b`**. | The Llama model returned *404 model_not_found* on the Groq free tier; `gpt-oss-120b` was the strongest model available there. |
| D4.4 | For gpt-oss, set `reasoning_effort="low"` and add 2,000 tokens to `max_tokens`. | It is a reasoning model; hidden reasoning tokens count against the limit and could truncate the JSON answer. |
| D4.5 | **Fixed the verifier to handle grouped citations** such as `[ev_a, ev_b]`. | The model cited several passages in one bracket, which the first regex silently ignored (a grounding hole). |
| D4.6 | Rule parser runs **before** the LLM extractor, and its numbers win. | Regex is exact for numbers like "0.3%"; the LLM only fills gaps in loose phrasing. |

---

## Phase 5 — Conversation

| # | Decision | Reason |
|---|---|---|
| D5.1 | Sufficiency = **≥ 3 variables, ≥ 2 domains, and land use known**. | ≥ 3 variables is from the brief. **Land use was added later** (see D7.6) because it decides which practices apply. |
| D5.2 | Questions ordered **SOC → rainfall → land use → …**, at most 3 per turn, each asked at most twice. | Mirrors the brief's example follow-up; avoids nagging. |
| D5.3 | "not sure / just recommend" → proceed with **reduced confidence** and a stated assumption. | A real assistant shouldn't block forever; transparency preserves trust. |
| D5.4 | Follow-up questions ("why not cover crops?") are answered from retrieval **plus the engine's own exclusion reasons**. | Shows the system can explain its reasoning, not just repeat it. |
| D5.5 | Practice mentions matched with a **curated keyword map** instead of words from the practice names. | The first version matched "cover" in *"salt-tolerant cover"* (gypsum practice), which was a false positive. |
| D5.6 | Causal chains that are just the **tail of a longer chain** are hidden. | Removed repetitive output. |

---

## Phase 6 — Fixes found by the evaluation suite

The behavioural evaluation (`eval/run_eval.py`) initially passed **5/10** scenarios. Each failure was a real
bug; fixes:

| # | Failure | Fix | Reason |
|---|---|---|---|
| D6.1 | Acidic cotton + heavy fertiliser: nutrient management was never recommended. | Added evidence that **nitrogen fertiliser acidifies soil** (Guo et al. 2010, *Science*), a graph edge `pollution → soil_ph`, and linked nutrient management to `PH_ACIDIC`. | A genuine multi-variable link (human impact ↔ soil health) the knowledge base was missing. |
| D6.2 | "We cleared part of a forest patch for maize" wasn't detected as deforestation, and land use was set to *forest*. | Broader clearing regex; a named crop now sets land use to cropland. | Parser robustness. |
| D6.3 | Sodic soil (pH 9.2): gypsum reclamation was crowded out. | **Gatekeeper boost** (+8) for practices with prerequisites; gypsum also linked to infiltration/erosion. | Extreme pH blocks every other practice, so it must be fixed first. |
| D6.4 | User skipped questions → no recommendations. | **Screening-level fallback** (single-issue allowed, confidence −0.2, clearly flagged). | Better than an empty answer, and honest about its limits. |
| D6.5 | "Actually rainfall is 1200 mm" kept the old `rainfall_level=low`. | Sibling fields (`rainfall_mm` / `rainfall_level`) are kept consistent on merge; the change is reported. | Memory must update correctly, not just accumulate. |
| D6.6 | A regex edit inserted invisible backspace characters. | Replaced them with proper `\b` word boundaries. | Tooling bug caught by tests. |

After the fixes: **10/10 scenarios, 22/22 tests, lint clean** (later extended to 11 scenarios and 24 tests; see Phase 7).

---

## Phase 7 — Geo, UI & polish

| # | Decision | Reason |
|---|---|---|
| D7.1 | Geo enrichment via **SoilGrids + Open-Meteo**; derived climate zone from the **aridity index** (P/ET₀). | Bonus requirement in the brief; free APIs without keys. |
| D7.2 | Looked-up values are **labelled with provenance** and never overwrite user-given values. | Modelled data isn't a field measurement; the user must see which is which. |
| D7.3 | Streamlit UI shows the **retrieval trace, grounding notes and raw JSON** for every answer. | Brief: "Clearly show how knowledge is retrieved and used." |
| D7.4 | Replaced deprecated `use_container_width` with `width="stretch"`. | Removes Streamlit deprecation warnings. |
| D7.5 | Confidence bands tightened to **high ≥ 0.75, medium ≥ 0.55**. | Almost everything showed "high" before; the label wasn't informative. |
| D7.6 | **Land use now required** before recommending; geo notes are shown in the clarification. | Coordinates alone gave 5 variables but no land use, so advice would have been untargeted. |
| D7.7 | "growing only pearl millet" is now detected as a monoculture; IPM linked to monocultures (diversification improves pest control, Tamburini 2020). | Found in manual testing of the geo flow. |
| D7.8 | CLI (`python -m darukaa.cli --json file`) and example JSON files. | Shows structured input outside the UI and makes grading scripts easy. |
| D7.9 | GitHub Actions CI: lint → build/validate KB → pytest → eval (no secrets, Python 3.10 & 3.11). | The README must describe CI/CD; broken citations or reasoning regressions fail the build. |
| D7.10 | A site-specific rainfall of "high" (≥ 1000 mm) now overrides a regional dry climate label; added an 11th evaluation scenario for it. | In the demo, *"actually rainfall is 1200 mm"* on a site labelled semi-arid still triggered `WATER_LIMITED`. The measured value is more specific than the regional label. |
| D7.11 | Leaner LLM usage: smaller token budgets, LLM extraction only when the rule parser found < 3 fields, and automatic **fallback to `openai/gpt-oss-20b`** on errors or rate limits (no 30 s retry wait). Replaced `print` with `logging`. | Groq's free tier allows 8,000 tokens/min for `gpt-oss-120b`; during testing a 429 error silently pushed a UI turn into deterministic mode. |
| D7.12 | **Prerequisite practices** (liming, gypsum) may target a single diagnosed constraint. | With pH 4.8 but no SOC value, liming was dropped even though the legume recommendation said "correct acidity first". Prerequisites unblock other practices, so they are multi-variable by nature. |
| D7.13 | The verifier checks **any evidence-ID token**, including `(ev_x)` in parentheses, and normalises citations to `[ev_x]`. | The LLM sometimes cited in parentheses, which bypassed the bracket-only check (a grounding hole found in the UI test). |
| D7.14 | Time horizon ignores only *harmful* decreases (e.g. soil moisture), not beneficial ones (e.g. nitrogen runoff ↓). | Nitrogen management showed "long term" although its runoff reduction is short term. |
| D7.15 | Added 2 tests (24 total) and made the acidic-soil scenario omit SOC. | Locks in D7.12–D7.14. |

---

## Phase 8 — Enhancements

| # | Decision | Reason |
|---|---|---|
| D8.1 | Added **monitoring indicators** (indicator, method, frequency) to every practice: 48 in total, stored in a new `monitoring` column. The build fails if a practice has none. | "Actionable" advice needs a way to check it is working. Evaluators can see that each recommendation has a verification method. |
| D8.2 | New **planner**: phased action plan *0 Baseline → 1 Unblock & secure → 2 Diversify & build → 3 Sustain & review*, with baseline measurements for each diagnosed issue. | Turns a ranked list into an executable sequence and makes the water-first / prerequisite-first reasoning explicit. |
| D8.3 | Knowledge tables are **dropped and recreated** on each build. | `CREATE TABLE IF NOT EXISTS` would not add the new column to an existing database; conversation tables are left untouched. |
| D8.4 | Water-consuming practices are now **excluded** (not just penalised) on water-limited sites. | A coordinate-based test site (semi-arid, SOC 0.69%) still listed cover crops with low confidence, contradicting the system's own water-first reasoning. The follow-up question still explains the exclusion. |
| D8.5 | Exclusion explanations now also cover unmet prerequisites and unsuitable land use, and only say "addresses only N problems" when no more specific reason applies. | After D8.4, the old message ("addresses only 0 problems") was misleading. |
| D8.6 | **GBIF** added to geo enrichment: recorded species within a ~20 km box, plus threatened-species (CR/EN/VU) record count, flagged as a sampling-biased proxy. | The brief lists species richness as a biodiversity indicator; GBIF is free and global. The bias is stated so the number isn't over-trusted. |
| D8.7 | **Site reasoning map** (Graphviz): problems → variables → outcomes, with practices → the problems they treat. | Makes multi-variable reasoning visible at a glance (Depth of Reasoning + Output Clarity). |
| D8.8 | **Markdown / JSON report downloads** for each assessment. | The advice is useful outside the app (sharing with farmers or agronomists, attaching to a submission). |
| D8.9 | **FastAPI REST API** (`/chat`, `/sessions/{id}`, `/knowledge/search`, `/knowledge/practices`, `/health`) with OpenAPI docs; session IDs give multi-turn memory over HTTP. | Structured JSON input is a stated requirement; an API makes it usable by other systems, not only the UI. |
| D8.10 | **Dockerfile** (knowledge base built into the image) and a CI **docker job** that builds the image and smoke-tests the API. | Reproducible deployment; CI now covers the container too. The image could not be built locally because Docker Desktop was not running, so CI is where it is verified. |
| D8.11 | 6 new tests (30 total): API flow, validation, knowledge endpoints, plan sequencing, dryland exclusion. | Locks in the enhancements. |

---

## Phase 9 — Design refresh

| # | Decision | Reason |
|---|---|---|
| D9.1 | New visual system: earthy palette (forest / clay / amber / sky), Fraunces serif headings + Inter body, custom Streamlit theme (`.streamlit/config.toml`). | The default Streamlit look felt generic; a calm, scientific identity fits an "AI environmental scientist". |
| D9.2 | Hero header with live knowledge-base stats; a three-step "Describe → Diagnose → Act & verify" empty state; example prompts shown as cards. | Shows what the system is and how to use it before the first message. |
| D9.3 | Assessment layout: status pills → summary callout → severity-coded **diagnosis cards** + causal chains as **flow chips** → numbered **recommendation cards** with tabs (Overview / Impact / Verify / Evidence) → **timeline** action plan → collapsible reasoning map, assumptions, retrieval trace and raw JSON. | Puts the decision-relevant content first and keeps the detail one click away, instead of one long wall of text. |
| D9.4 | Clarifying questions shown as numbered cards with "known so far" chips; answers styled as a callout with a source list. | Makes the dialogue state visible. |
| D9.5 | Sidebar profile shows each value with its provenance badge (you / json / lookup). | Users can see which values were measured and which were looked up. |
| D9.6 | All user- and model-supplied text inserted into custom HTML is escaped (`html.escape`). | Prevents broken layout or injected markup from LLM or user text. |
| D9.7 | Fixed: the global font rule overrode Streamlit's icon font (the sidebar toggle showed the text "double_arrow_right"). Fixed: the "How it works" Graphviz diagram never rendered, because `graph` is a reserved DOT keyword used as a node name. | Found while checking the redesign in the browser. |

---

## Phase 10 — Fluid single-page front end

| # | Decision | Reason |
|---|---|---|
| D10.1 | Built a **dedicated single-page front end** (`frontend/`, served by FastAPI at `/app`) instead of restyling Streamlit further. | Streamlit re-renders server-side: it cannot track a finger 1:1, interrupt an animation, or hand gesture velocity to a spring. The Apple-style interaction model needs direct control of pointer events and the frame loop. |
| D10.2 | Kept the **Streamlit console** as a second interface. | It is the zero-config Streamlit Cloud demo, and it exposes the engine's internals (dataframes, Graphviz maps) usefully for evaluators. Both share the same `darukaa` engine. |
| D10.3 | Wrote a small **spring engine** (damping ratio + response, integrated in one rAF loop) rather than adding Motion/Framer Motion. | No build step or CDN dependency, and it matches Apple's two-parameter model directly. Sub-stepped integration keeps a long frame stable. |
| D10.4 | **No CSS transitions or keyframes for gesture-driven motion**; springs re-target from the live value and keep velocity. | Interruptibility is the core principle: a sheet must be grabbable mid-flight and reversible without a jump. |
| D10.5 | Sheet gestures: 1:1 tracking with grab offset, velocity history, **momentum projection** (`d = 0.998`), snap points, **rubber-banding** past the top, velocity handed to the spring, haptic on commit. | This is what makes a flick throw the sheet instead of snapping from the release point. |
| D10.6 | Translucent chrome with content scrolling under it; scrim + shell push-back for modal depth; scroll-edge mask instead of a hard divider. | Material and depth convey hierarchy without stealing focus. |
| D10.7 | Inline `[ev_x]` citations render as compact source chips (id in the tooltip). | Raw ids in prose were unreadable, but the grounding link must stay visible. |
| D10.8 | All server and model text is escaped before insertion into HTML. | The response contains LLM- and user-derived strings. |
| D10.9 | Session id in `localStorage`, full structured payload returned by `GET /sessions/{id}`. | A reload re-renders past turns exactly, without re-running the engine. |
| D10.10 | Docker now defaults to **uvicorn** (API + front end); added `render.yaml`. | The single-page app is the primary interface, so the container should serve it; Render's free tier gives it a live URL (Streamlit Cloud cannot host FastAPI). |
| D10.11 | Chrome height is measured with a `ResizeObserver` and fed into a CSS variable. | The header grows when the site-profile strip appears, which was hiding page titles underneath it. |
| D10.12 | Fixed `[hidden]` being overridden by `display: flex` (the sheet was visible on load) and low-contrast primary buttons in dark mode. | Found in the first browser pass. |
| D10.13 | Added 2 tests (32 total): the front end is served (`/` → `/app/`, assets 200) and session history carries the structured payload. | The front end depends on both; a silent break would only show up in the browser. |

---

## Phase 11 — Reasoning-quality improvements

| # | Decision | Reason |
|---|---|---|
| D11.1 | **Indexed four open-access primary sources** (FAO *Soil Organic Carbon: the hidden potential*, FAO RECSOIL, IPCC SRCCL SPM, IPBES Global Assessment SPM) — 532 chunks alongside the 53 curated passages. `scripts/fetch_sources.py` downloads them; the PDFs stay out of git. | The brief asks for indexed research papers and reports. The corpus is now primary literature, not only curated summaries, and the fetch script keeps it reproducible. |
| D11.2 | PDF chunks are **quality-filtered** (minimum length, letter ratio, no reference lists, must carry a domain tag, de-duplicated headers) and each PDF carries a **sidecar citation**. | Raw PDF extraction is full of page furniture; unfiltered chunks would pollute retrieval and citations. |
| D11.3 | Extraction and embedding are **cached** (`data/index/pdf_chunks.json`, content-addressed index reuse). | A fresh database was re-parsing 38 MB of PDFs on every run; the test suite went from 5 s to 5 min. It is back to 5 s. |
| D11.4 | **Site-scaled projections** (`reasoning/projections.py`): effect sizes are applied to the user's own baseline — SOC% → t C/ha via texture-based bulk density and 30 cm depth, then a low–high range over the practice's horizon, plus a farm total when the area is known. | "Measurable improvement estimates" should be in the user's units. 0.3% on 5 ha of sandy soil now reads "14.4 t C/ha today → 16.6–19.4 in 10 years (+10.8 to +25.2 t C across 5 ha)". Assumptions and the saturation caveat travel with every number. |
| D11.5 | **Value of information** (`reasoning/voi.py`): each unknown variable is filled with plausible values, the diagnosis and recommender are re-run, and questions are ordered by how much the answer actually changes — the phrasing says so ("could change 2 of the recommendations"). | The old order was a fixed priority list. This asks the question that matters for *this* site, and shows the user why it is worth answering. |
| D11.6 | **Retrieval**: one short site query plus a focused query per diagnosed problem, and MMR diversity so k passages are not k paraphrases. | A single long query mixing message, profile and every finding retrieved generic passages. |
| D11.7 | **Organic matter is converted to organic carbon** (÷2, Pribyl 2010) when a user reports SOM, with the conversion recorded in provenance. Added evidence on the conversion factor, the weak basis for a single critical SOC threshold (Loveland & Webb 2003) and bulk-density ranges. | Treating 1.6% organic matter as 1.6% carbon overstates carbon by ~2x and would have mis-diagnosed the site. |
| D11.8 | Clarifying questions render as a list with the impact note in muted text (front end) instead of raw Markdown asterisks. | The `*(could change …)*` markup was being escaped, not formatted. |
| D11.9 | 6 new tests (38 total) covering SOM conversion, projection arithmetic, projection absence without a baseline, VOI ranking, PDF citation integrity and retrieval diversity. | Each improvement is now regression-protected. |

---

## Phase 12 — Reload robustness

| # | Decision | Reason |
|---|---|---|
| D12.1 | The front end renders stored answers **defensively** (`arr()` around every list field). | Conversations saved before `projections` / `monitoring` / `action_plan` existed threw on reload. |
| D12.2 | A render failure during restore now shows that turn's text and logs a warning; only a **404 clears the session**. | The previous catch-all deleted the session id, so a single unrenderable turn silently wiped the whole conversation — which looked like "refresh is broken". |
| D12.3 | Added a schema test that a pre-projection payload still validates and defaults the new fields to empty. | Locks the backwards compatibility that the front end depends on. |
| D12.4 | `.idea/` and `.vscode/` git-ignored. | IDE folders appeared once the project was opened in an IDE. |
| D12.5 | **A page load starts a new conversation.** The previous session id is *parked* (not deleted) and offered as a "Resume your previous conversation" link; only `?resume=1` reopens it. Added a **＋ New** button in the header. | Restoring automatically meant a refresh always reopened the old chat with no visible way to start over — the opposite of what a refresh is expected to do. Memory is still demonstrable, but on purpose rather than by default. |
| D12.6 | `GET /sessions/{id}` now returns `created_at` / `updated_at`. | Lets a client show when a parked conversation was last active. |

---

## Phase 13 — Conversation history

| # | Decision | Reason |
|---|---|---|
| D13.1 | Added `GET /sessions` (recent conversations with title, timestamps, message count and site profile) and `DELETE /sessions/{id}`, backed by `list_sessions()` / `delete_session()` in `memory.py`. | Conversations were already stored, but only the single most recent one was reachable. |
| D13.2 | A conversation's **title** is its opening message, or — when the user started with JSON — the site itself (crop, land use, climate zone). | A history list of "```json…" entries would be unreadable. |
| D13.3 | Front end: the header's second button opens a **History** sheet listing past conversations with age ("10 min ago"), message count and site chips; Open reopens via `?session=<id>`, and the trash icon deletes. | Makes memory visible and demonstrable without reopening the last chat automatically. |
| D13.4 | Deleting asks for confirmation first. | It is permanent and server-side; the first version deleted on a single click. |
| D13.5 | The Streamlit console gained the same history list in its sidebar. | Parity between the two interfaces. |
| D13.6 | Test: rebuilding the knowledge base must not lose conversations (it drops and recreates the knowledge tables). | Guards the one code path that legitimately drops tables in the shared database. |

---

## Phase 14 — Header

| # | Decision | Reason |
|---|---|---|
| D14.1 | The header's second line became a **live status line**: a coloured dot plus the active model (or "deterministic mode"), and the knowledge-base counts as a button that opens the Knowledge tab. | The old line was a dense dot-separated string. Now it answers "is the LLM on?" at a glance, and the counts are a route into the evidence rather than decoration. |
| D14.2 | Tabs gained **icons, explanatory tooltips and a sliding indicator** driven by two springs (x and width). | 2D motion decomposed into independent axes never desyncs on a fast switch, and the springs re-target from the live value, so repeated taps stay continuous. |
| D14.3 | The header **compacts on scroll** (status line fades and collapses, brand mark shrinks), spring-driven through a `--compact` CSS variable. | Content scrolls under floating chrome, so the chrome should give room back; a spring keeps a reversed scroll continuous where a CSS transition would restart. |
| D14.4 | The **open conversation's title** is shown under the brand. | With history added, it should be obvious which conversation is on screen. |
| D14.5 | Kept the **Knowledge** and **Method** tabs, and documented why in the README. | They answer two scored criteria directly: Knowledge System Design (20%) and the "no generic LLM-only solutions" constraint. Knowledge makes the retrieval layer inspectable; Method states what the LLM is not allowed to decide. |

---

## Phase 15 — Web-app test pass

| # | Decision | Reason |
|---|---|---|
| D15.1 | **Questions no longer become site data.** Question-shaped messages are detected, non-material fields (`goal`, `region`, `area_ha`) don't trigger a recompute, and the extractor is told to return nothing for questions. | Found in testing: "Why not cover crops?" made the LLM extractor write `goal: "introduce cover crops"`, so the engine re-ran a whole assessment instead of answering the question. |
| D15.2 | `/app/*` responses send **`Cache-Control: no-cache`**. | The browser served a stale `styles.css` after an edit — during a demo that silently runs the old UI. ETags keep revalidation to a 304. |
| D15.3 | On screens below 560 px the header **hides the knowledge counts** and keeps the status line to one row. | The model/counts line wrapped into the brand at 375 px. |
| D15.4 | Added `TESTING.md`: what the automated suite covers, plus a 20-case manual web-app pass with results and the two defects it found. | The submission asks how the project is tested; "42 tests pass" doesn't show that gestures, caching and mobile layout were checked. |
