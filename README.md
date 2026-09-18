# 🌱 Darukaa.Earth — AI Environmental Scientist

A knowledge-grounded conversational system that diagnoses land and ecosystem problems from soil, water,
climate, land-use, biodiversity and human-impact variables, and gives **evidence-backed, multi-variable
recommendations** to improve biodiversity.

> **Not an LLM wrapper.** A structured, cited knowledge base and a rule-based reasoning engine decide *what*
> to recommend. Hybrid retrieval supplies the evidence, the LLM explains it for the specific site, and a
> verifier removes anything the evidence doesn't support. With the LLM switched off, the system still works.

* **Live demo:** `<add your deployed URL>` — the single-page app is at `/app`, the API docs at `/docs`
* **Two front ends:** a fluid single-page app (FastAPI-served, gesture-driven) and a Streamlit console
* **Docs:** [ARCHITECTURE.md](ARCHITECTURE.md) (how it works) · [DECISIONS.md](DECISIONS.md) (why, and change log) · [TESTING.md](TESTING.md) (what is tested, and how)

---

## What it does

| Brief requirement | How this project meets it |
|---|---|
| Retrievable knowledge layer, not just prompts | SQLite knowledge base (50 curated sources, 53 evidence passages, 16 practices, 36 quantified effects, 20 causal edges) plus 532 chunks indexed from four open-access FAO/IPCC/IPBES PDFs, searched with a hybrid vector+BM25 index. |
| Clearly show how knowledge is retrieved | Every answer has a **retrieval trace**: queries, filters, passage IDs, dense and BM25 ranks, fused scores, structured lookups. |
| Clarifying questions | Asks for the most informative missing variables when fewer than 3 variables (across 2 domains, incl. land use) are known. |
| Conversation history | Every conversation is stored server-side; the header's **History** panel lists past ones with a title, age, message count and site variables, and can reopen or delete them (`GET /sessions`, `DELETE /sessions/{id}`). A page load starts fresh — reopening is deliberate. |
| Multi-turn memory | Site profile and messages persisted per session in SQLite; updates recompute the advice and say what changed. |
| Evidence-backed recommendations | Each includes **what to do, why it works, site-specific reasoning, impacted metrics with estimates, time horizon, confidence (with reason), trade-offs and references**. |
| Multi-metric reasoning, ≥ 3 variables | Causal chains over a variable graph; every recommendation must address ≥ 2 diagnosed issues; enforced by tests. |
| Text + JSON input, geo bonus | Free text, JSON (strict or loose keys) via the UI, CLI or **REST API**, and coordinates → ISRIC SoilGrids + Open-Meteo (rainfall, temperature, aridity → climate zone) + **GBIF** (recorded species, threatened-species records). |
| Measurable estimates | Literature effect sizes are **scaled to your site**: 0.3% SOC on sandy soil ≈ 14.4 t C/ha now → 16.6–19.4 t C/ha in 10 years (+10.8 to +25.2 t C across 5 ha), with assumptions and the saturation caveat attached. |
| Smart questioning | Unknown variables are ranked by **how much they would change the advice** (each unknown is filled with plausible values and the reasoning re-run), so the most useful question is asked first. |
| Actionable output | A **phased action plan** (baseline → unblock → build → sustain) and, per recommendation, **what to measure, how and how often** to verify it is working. Reports downloadable as Markdown/JSON. |
| Interface | A gesture-driven single-page app (spring physics, draggable detail sheets, translucent materials, reduced-motion support) plus a Streamlit console. |
| Scientific correctness | Soil organic *matter* is converted to *carbon* (÷2, Pribyl 2010) rather than treated as the same number; carbon thresholds are presented as rules of thumb, since a single global critical level is weakly supported (Loveland & Webb 2003). |
| No shallow/generic advice | Context rules: e.g. no cover crops where water is limiting, no tree planting in natural grasslands, fix soil pH first, water-first sequencing, explicit "avoid" warnings. |

### Example (the brief's use case)

**Input:** `{"soil_organic_carbon": "0.3%", "rainfall": "low", "crop": "monoculture wheat", "region": "semi-arid"}`

**Diagnosis:**
- Very low soil organic carbon (SOC)
- A water-limited system
- A monoculture
- Inferred erosion risk

**Causal chain:** `soil_moisture → soil_organic_carbon → soil_biodiversity → species_richness`

**Recommendations, in order:**
1. **Residue mulch + reduced tillage + rotation.** Matches or beats conventional yields in dry climates (Pittelkow et al. 2015). *Short term, high confidence.*
2. **In-field water harvesting + farm pond.** Raises water productivity (Rockström et al. 2010), and ponds add aquatic species (Davies et al. 2008).
3. **Native nitrogen-fixing boundary trees (dryland agroforestry).** Roughly 25% more SOC in the top 30 cm after conversion from cropland (De Stefano & Jacobson 2018). *Medium term.*
4. **Legume rotation or intercrop.** +20.7% microbial biomass carbon (McDaniel et al. 2014); land equivalent ratio about 1.2 (Yu et al. 2015).

**Avoid:** water-hungry exotic plantations, which cut streamflow by roughly half (Jackson et al. 2005).

**Action plan:**
- *0 · Baseline (months 1–2):* measure SOC, soil moisture, yields and erosion.
- *1 · Unblock & secure (0–12 months):* mulch package and water harvesting.
- *2 · Diversify & build (years 1–3):* boundary trees and legumes.
- *3 · Sustain & review (year 3+):* re-measure against the baseline; keep avoiding thirsty plantations.

**Projected for your site** (agroforestry, 10 years): soil carbon **14.4 → 16.6–19.4 t C/ha**
(+2.2 to +5.0), i.e. **+10.8 to +25.2 t C across 5 ha** — the meta-analysis range applied to the measured
baseline, assuming 1.6 g/cm³ bulk density for sandy topsoil over 0–30 cm.

**Follow-up** *"Why not cover crops?"* → the system explains that cover crops deplete stored soil water in dryland systems (Unger & Vigil 1998).

---

## Architecture (summary)

```
text / JSON / lat-lon
   → profile parser (rules + optional LLM) → session memory (SQLite) ← geo enrichment (SoilGrids, Open-Meteo, GBIF)
   → dialogue policy ──► clarifying questions
                     ├─► grounded follow-up answer
                     └─► diagnosis (cited thresholds)
                          → knowledge-graph causal chains
                          → practice scoring (structured effects, context rules)
                          → hybrid retrieval (site query + one query per problem, bge-small + BM25, RRF, MMR)
                          → projections: effect sizes scaled to this site's baseline
                          → LLM site-specific synthesis (Groq gpt-oss-120b, optional)
                          → grounding verifier (unknown citations / unsupported numbers removed)
                          → phased action plan + monitoring indicators
                          → validated JSON response → single-page app / Streamlit / REST API / CLI / Markdown
```

Full details, diagrams and the scoring formula: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

### Database / schema

SQLite file `data/darukaa.db` (built from `data/knowledge/*.yaml`):

| Table | Purpose | Key columns |
|---|---|---|
| `sources` | Bibliography (50 curated + 4 indexed PDFs) | `id`, `title`, `authors`, `publisher`, `year`, `type`, `tier` (1 = assessment/meta-analysis), `url` |
| `chunks` | Retrievable evidence passages (53 curated + 532 from PDFs) | `id`, `source_id → sources`, `origin` (curated/pdf), `domains` JSON, `variables` JSON, `text` |
| `practices` | Interventions, applicability rules and a structured `projection` block | `id`, `kind` (do/avoid), `action`, `mechanism`, `addresses` {issue: weight}, `suits`, `requires`, `avoid_when`, `adaptations`, `tradeoffs`, `variables_linked`, `monitoring` [{indicator, method, frequency}], `water_penalty` |
| `practice_effects` | Quantified metric effects | `practice_id → practices`, `metric`, `direction`, `estimate`, `horizon`, `evidence_id → chunks`, `source_id → sources` |
| `relationships` | Variable interaction graph | `from_var`, `to_var`, `sign`, `mechanism`, `evidence_id → chunks` |
| `sessions` | Conversation memory | `id`, `profile` JSON, `state` JSON, timestamps |
| `messages` | Conversation history | `session_id → sessions`, `role`, `content`, `payload` JSON (full structured response) |

Vector index: `data/index/vectors.npy` (384-d normalised embeddings), `meta.json` and `fingerprint`
(it rebuilds automatically when the knowledge files change). Extracted PDF text is cached in
`data/index/pdf_chunks.json`, and embeddings are reused when the corpus is unchanged — otherwise a fresh
database would re-parse 38 MB of PDFs on every run.

---

## Project structure

```
frontend/                   single-page app served at /app — index.html, styles.css, app.js
                            (spring engine, draggable sheet, translucent chrome; no build step, no dependencies)
app.py                      Streamlit console (same engine, server-rendered; used for the Streamlit Cloud demo)
api.py                      FastAPI REST API (/chat, /sessions, /knowledge/*, /health) + serves frontend/
render.yaml                 Render blueprint for deploying API + front end
Dockerfile                  container image (serves the API + single-page app; Streamlit via an override)
darukaa/
  config.py                 env / Streamlit secrets
  schemas.py                Pydantic contracts (SiteProfile, Recommendation, AssistantResponse …)
  engine.py                 per-turn orchestration
  llm.py                    Groq / Gemini OpenAI-compatible client (optional)
  geo.py                    SoilGrids + Open-Meteo enrichment
  memory.py                 SQLite session memory
  render.py                 Markdown rendering
  cli.py                    command-line interface
  kb/build.py               validate + ingest + index pipeline
  kb/store.py               SQLite schema and knowledge cache
  kb/vector.py              hybrid retriever
  reasoning/profile_parser.py   text/JSON → variables
  reasoning/clarifier.py        sufficiency + question selection
  reasoning/diagnosis.py        thresholds → issue codes
  reasoning/graph.py            causal chains
  reasoning/recommender.py      practice scoring, confidence, horizon
  reasoning/planner.py          phased action plan + baseline measurements
  reasoning/projections.py      effect sizes scaled to the site's own baseline (t C/ha, % , farm total)
  reasoning/voi.py              value of information: ranks unknowns by how much they change the advice
  reasoning/verifier.py         LLM grounding verification
scripts/fetch_sources.py    downloads the open-access PDFs into data/raw/ (not committed)
data/knowledge/             sources.yaml · evidence.yaml · practices.yaml · relationships.yaml
data/raw/                   optional PDFs to index
eval/                       scenarios.yaml + run_eval.py (behavioural evaluation)
tests/                      pytest suite
examples/                   sample JSON inputs
.github/workflows/ci.yml    CI pipeline
```

---

## Local setup

Requirements: Python 3.10+ (tested on 3.10 and 3.11). Internet access is needed on first run, to download
the ~130 MB embedding model and, optionally, to call Groq and the geo APIs.

```bash
git clone <your-repo-url>
cd Darukaa.Earth
python -m venv .venv
```

Activate the environment. On Windows (PowerShell):

```bash
.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

Configure the LLM (optional; without a key the system runs in deterministic mode):

```bash
cp .env.example .env
```

Then edit `.env` and set `GROQ_API_KEY` (a free key is available from https://console.groq.com).
To run with no LLM at all, set `LLM_PROVIDER=none`.

Optionally index the primary literature first — this downloads four open-access reports (~38 MB: FAO soil
carbon, FAO RECSOIL, IPCC SRCCL summary, IPBES Global Assessment summary) and indexes them beside the
curated passages. Without it the system runs on the 53 curated passages alone.

```bash
python scripts/fetch_sources.py --rebuild
```

Build the knowledge base (the app also does this automatically on first start):

```bash
python -m darukaa.kb.build
```

Run the app (FastAPI + single-page front end at http://localhost:8000, API docs at /docs):

```bash
uvicorn api:app --reload
```

Or the Streamlit console:

```bash
streamlit run app.py
```

Use the CLI with structured input:

```bash
python -m darukaa.cli --json examples/semi_arid_wheat.json
```

```bash
python -m darukaa.cli --json examples/acidic_cotton.json --raw
```

```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"site\": {\"soil_organic_carbon\": \"0.3%\", \"rainfall\": \"low\", \"crop\": \"monoculture wheat\", \"region\": \"semi-arid\"}}"
```

Pass the returned `session_id` in the next request to continue the conversation.

Run with Docker:

```bash
docker build -t darukaa-earth .
```

```bash
docker run -p 8000:8000 --env-file .env darukaa-earth
```

Then open http://localhost:8000. For the Streamlit console instead, override the command:

```bash
docker run -p 8501:8501 --env-file .env darukaa-earth streamlit run app.py --server.address=0.0.0.0
```

Or chat from the terminal:

```bash
python -m darukaa.cli
```

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq`, `gemini` or `none` |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | — | API key for the chosen provider |
| `LLM_MODEL` | `openai/gpt-oss-120b` (Groq) / `gemini-2.0-flash` | Model name |
| `LLM_FALLBACK_MODEL` | `openai/gpt-oss-20b` (Groq) | Used automatically on rate limits or errors |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model |
| `GEO_ENABLED` | `true` | Enable coordinate lookups |
| `DARUKAA_DB_PATH` | `data/darukaa.db` | SQLite location |

### Adding knowledge

* **Curated:** add a source to `sources.yaml`, a passage to `evidence.yaml`, then reference the passage from a
  practice effect or relationship. `python -m darukaa.kb.build` fails if any reference is broken.
* **PDFs:** drop files into `data/raw/` (optional sidecar YAML for the citation) and rebuild. See `data/raw/README.md`.

---

## Testing & evaluation

Unit, integration, API and front-end-contract tests (42):

```bash
pytest
```

Behavioural evaluation, deterministic:

```bash
python eval/run_eval.py --no-llm
```

Behavioural evaluation with the configured LLM:

```bash
python eval/run_eval.py
```

The evaluation runs 11 multi-turn scenarios:
- the brief's example
- clarification behaviour
- memory and follow-ups
- acidic soil
- deforestation and fragmentation
- dry grassland
- sodic soil
- skipped questions
- value updates
- a humid-climate contrast
- the demo rainfall update in a semi-arid site

A 20-case manual pass over the web app (gestures, caching, mobile layout, accessibility) is recorded in
[TESTING.md](TESTING.md).

Every recommendation response is also checked against the output contract:
- what/why/metric/reference present
- ≥ 2 issues addressed
- ≥ 3 variables linked overall
- no dangling citations
- no generic phrases

| Mode | Scenarios | Avg variables linked / rec | Avg references / rec |
|---|---|---|---|
| Deterministic (`--no-llm`) | 11/11 | 3.4 | 2.3 |
| Groq `gpt-oss-120b` | 11/11 | 3.5 | 3.4 (verifier removed 1 unsupported LLM sentence) |

---

## CI/CD

**CI:** GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and on every pull request,
on Python 3.10 and 3.11. It needs no secrets because it runs in deterministic mode.

1. `pip install -r requirements-dev.txt` (pip cache + cached embedding model)
2. `ruff check .` — lint
3. `python -m darukaa.kb.build` — builds the KB; **fails on any broken citation**
4. `pytest` — unit and integration tests
5. `python eval/run_eval.py --no-llm` — behavioural evaluation (reasoning regressions fail the build)
6. **docker** job (after tests pass): builds the image, starts the REST API in the container and smoke-tests `/health` and `/chat`

**CD — single-page app + API** (Render free tier, blueprint in `render.yaml`): connect the repo, add
`GROQ_API_KEY` as a secret, deploy. The build command builds the knowledge base; the health check is `/health`.
Any Docker host works too — the image defaults to serving the API and front end.

**CD — Streamlit console:** Streamlit Community Cloud redeploys `app.py` automatically on every push to `main`.

1. Push the repo to GitHub.
2. At https://share.streamlit.io, choose **Create app**, select the repo and branch `main`, and set the main file to `app.py`.
   Under *Advanced settings*, pick Python 3.11.
3. Under *Secrets*, paste the contents of `.streamlit/secrets.toml.example` with your real key.
4. Deploy. The first start builds the knowledge base and downloads the embedding model (about 1 minute).

---

## The three sections, and why they exist

| Section | What it is | Why it earns its place |
|---|---|---|
| **Consult** | The conversation: diagnosis, causal chains, recommendations, action plan. | The product itself. |
| **Knowledge** | The corpus, browsable: every source, every practice with its quantified effects and monitoring indicators, and a live search box that runs the same hybrid retriever the engine uses. | The brief scores *Knowledge System Design* (20%) and asks to "clearly show how knowledge is retrieved and used". This is the evidence that the knowledge layer is real and inspectable, rather than an assertion — an evaluator can trace any citation back to its passage. |
| **Method** | The ten-step pipeline, stated plainly: what the rule engine decides and what the language model is *not* allowed to decide. | The brief forbids "generic LLM-only solutions". This is the argument that the LLM never chooses a practice or a number, and it doubles as the demo script for explaining the system. |

## Demo script (≈ 5 minutes)

Run `uvicorn api:app --reload` and open http://localhost:8000.

1. *"Biodiversity is declining on my land"* → the system asks targeted questions (SOC, rainfall, land use).
2. *"SOC is 0.3%, about 350 mm rain, only wheat every year, semi-arid"* → shows the diagnosis, causal chains,
   four sequenced recommendations plus one "avoid" warning, and the confidence, time horizon and references
   for each. Open the **Retrieval trace** and the **Raw JSON**.
3. *"Why not cover crops?"* → explains the water trade-off with evidence.
4. *"Actually rainfall is about 1200 mm"* → the water constraint disappears and the advice changes, with an explanation.
5. **＋ New** → **Enter site data** (the brief's example JSON) → the same quality from structured input.
6. **＋ New** → **Use coordinates** (Jodhpur, 26.24 / 73.02) → soil, climate and GBIF species are fetched with
   provenance, then land use is asked for because coordinates cannot supply it.
7. Open a recommendation's **Impact** tab → the projection in your own units, with its assumptions.
   Note the follow-up question: it says which unknown would change the advice, and by how much.
8. Tap any **recommendation card** → the detail sheet springs up. Drag it by the grabber: it tracks your pointer
   1:1, resists past the top, and a downward flick throws it closed (momentum, not a fixed animation). Grab it
   mid-flight to show that motion is interruptible.
9. **Knowledge** tab → search the corpus the way the engine does; tap a practice for its effects and monitoring.
10. **Method** tab → the ten-step pipeline.
11. **History** (☰) → every past conversation with its title, age and site variables; reopen one to show that
    memory is server-side, not browser state. A plain refresh starts a new conversation on purpose.
12. Open http://localhost:8000/docs → `POST /chat` with the brief's JSON to show the API.
13. (Optional) `streamlit run app.py` → the console view with dataframes, the reasoning map and downloads.

---

## Limitations

* Effect sizes are paraphrased from the cited papers and should be verified against the originals before field
  use. Projections are arithmetic on those ranges — an evidence-based estimate, not a prediction: real gains
  depend on site history, management quality and weather, and they saturate over decades.
* Bulk density is inferred from soil texture when not measured, which moves the t C/ha figures by roughly ±15%.
* Rainfall-mm bands and the heat threshold are heuristics, and are flagged as such in the output.
* Geo enrichment covers soil, climate and GBIF species records, but not land cover yet. GBIF counts reflect sampling effort as well as real richness.
* This is decision support, not a substitute for local agronomic or ecological advice.
