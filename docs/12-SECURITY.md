# 12 — Security

**Scope:** Secrets, trust boundaries, LLM containment, dependency hygiene, and what a prototype handling financial data must still get right.
**Derived from:** master spec §37, §48, §50.

> Security tooling remains **subordinate to shipping**. This document covers what is cheap to do correctly and expensive to retrofit. It does not justify installing a plugin ecosystem that slows a 24-hour build.

---

## 1. Threat model for this prototype

CCE is a local, single-user, simulated-execution prototype. That removes many concerns and sharpens the ones that remain.

### Out of scope
Multi-tenant isolation · authentication and session security · network attack surface (nothing is exposed publicly) · real money movement · PII of real customers · regulatory data-retention obligations.

### In scope

| Risk | Why it matters here |
|---|---|
| **Leaked API key** | An LLM key committed to a public hackathon repo is a real, immediate loss |
| **Prompt injection via LLM output** | The one place untrusted text enters the system |
| **SQL injection** | User-editable thresholds and scenario names reach the database |
| **Unsafe deserialisation** | Cached market data is loaded from files |
| **Untrusted third-party data** | Provider responses are parsed without guarantees |
| **Secrets rendered in the UI** | Streamlit displays whatever you hand it, including tracebacks |
| **Dependency supply chain** | An unpinned install can pull anything |

---

## 2. Secrets

### Rules

1. **No hard-coded secrets.** Ever, including in comments, notebooks, test fixtures and commit messages.
2. Configuration via environment variables loaded from `.env`.
3. `.env` is git-ignored. `.env.example` is committed with **placeholder values only**.
4. Secrets never appear in the UI, logs, error messages, or the audit database.
5. If a key is ever committed: rotate it first, then rewrite history. Rotation comes first — history rewriting does not un-leak a key that was already pushed.

### `.env.example`

```bash
# Data
CCE_DATA_PROVIDER=cached          # cached | jugaad
CCE_DB_PATH=./data/cce.db

# Config
CCE_POLICY_FILE=./config/policy.yaml
CCE_UNIVERSE_FILE=./config/universe.yaml
CCE_SCENARIOS_FILE=./config/scenarios.yaml

# Reproducibility
CCE_RANDOM_SEED=42

# Optional LLM explanation layer — the system works fully without it
CCE_LLM_ENABLED=false
CCE_LLM_API_KEY=                  # leave empty; never commit a real key
CCE_LOG_LEVEL=INFO
```

### `.gitignore` essentials

```gitignore
.env
.env.*
!.env.example
*.db
*.sqlite3
data/raw/
data/processed/
__pycache__/
.venv/
.streamlit/secrets.toml
```

`data/cache/` is **not** ignored — the committed snapshots are what make the demo reproducible and network-free.

### Streamlit-specific

- Never `st.write` a config object; it will happily print your key.
- `.streamlit/secrets.toml` is git-ignored.
- Ship with `client.showErrorDetails = false` for the demo so a traceback cannot surface a path or a token on the projector.

---

## 3. LLM containment — the primary trust boundary

The LLM is the only component consuming and producing untrusted natural language. Containment is **architectural**, not prompt-based: it holds because the code cannot act on the output, not because the prompt asked it not to.

### The rule

```
Deterministic engine → structured Explanation → LLM → display text → screen
                              ▲                                         │
                              └───────── NO PATH BACK ──────────────────┘
```

### Enforced boundaries

| Boundary | Enforcement |
|---|---|
| LLM cannot choose weights | `llm.py` returns `str`. There is no code path from LLM output to a weight vector. |
| LLM cannot alter thresholds | Thresholds load from `Policy` only. |
| LLM cannot approve | `ApprovalService` accepts a `Candidate` and a `HumanActionRecord`; neither is constructible from text. |
| LLM output is never parsed | It is stored in `explanations.llm_text` and rendered. Never `json.loads`ed into a decision. |
| LLM output is never executed | No `eval`, `exec`, or dynamic dispatch on model output. |
| LLM cannot see secrets | The prompt contains only the structured `Explanation` — no keys, no paths, no connection strings. |

### Input to the model

Send **only** the structured `Explanation` object. Do not send raw market data, file paths, environment values, or database contents. Smaller input is both cheaper and a smaller disclosure surface.

### Output handling

```python
def narrate(explanation: Explanation) -> NarratedExplanation:
    template = render_template(explanation)          # always available
    if not llm_enabled():
        return NarratedExplanation(explanation, template)
    try:
        text = call_llm(explanation)
        text = sanitize_for_display(text)            # strip markup, cap length
        return NarratedExplanation(explanation, template, llm_text=text)
    except Exception as e:
        logger.warning("LLM narration failed: %s", e)
        return NarratedExplanation(explanation, template, llm_error=str(e))
```

`sanitize_for_display` strips HTML/markup, caps length (e.g. 4000 chars), and removes control characters. Render with `st.text` / `st.markdown(..., unsafe_allow_html=False)` — never with raw HTML enabled.

### Failure behaviour
An LLM failure **never** blocks the decision loop. The deterministic narrator serves, and the UI notes that the enriched explanation was unavailable. `[INV-1]` `FR-146`

---

## 4. Database

- **Parameterised queries only.** No f-strings, no `%`, no `.format()` in SQL. `NFR-032`
- Identifiers (table/column names) are never taken from user input.
- All access through `cce/audit/repository.py`. There is no `execute_sql` helper, and adding one would be a design regression.
- `PRAGMA foreign_keys = ON` on every connection.
- Writes run in transactions; a failure rolls back and raises. `FR-125`
- The database file lives inside the project directory and is git-ignored.

```python
# WRONG
cur.execute(f"SELECT * FROM decision_records WHERE trigger_type = '{t}'")

# RIGHT
cur.execute("SELECT * FROM decision_records WHERE trigger_type = ?", (t,))
```

---

## 5. File and data handling

### Unsafe deserialisation
- **Never `pickle.load`** on any file that is not produced by this codebase in this run. Cached market data uses **Parquet or CSV**, not pickle.
- YAML loads via `yaml.safe_load`. Never `yaml.load` without a safe loader.
- JSON payloads read from the database are validated against the contracts before use — a stored row is data, not a trusted object graph.

### Path handling
- All file access is relative to configured project paths.
- User-supplied strings (scenario names, policy labels) never become path components. Sanitise or map through an allowlist.
- No path is constructed by concatenating user input.

### Provider data
Responses from `jugaad-data` are third-party input. Validate before use: expected columns present, types correct, dates monotonic, values within sane bounds. This is already required for correctness (`FR-006`) — it also happens to be the input-validation boundary.

---

## 6. Prohibited constructs

| Construct | Why |
|---|---|
| `eval()`, `exec()` | Arbitrary code execution |
| `subprocess` / `os.system` with any user-derived input | Command injection |
| `pickle.load` on external files | Arbitrary code execution on load |
| `yaml.load` without `SafeLoader` | Arbitrary object construction |
| f-string SQL | Injection |
| `unsafe_allow_html=True` on any dynamic content | Injection into the rendered page |
| Bare `except:` | Hides security-relevant failures alongside everything else |
| Logging a whole config or environment object | Key disclosure |

---

## 7. Dependencies

- Pin versions in `requirements.txt` (`==`, not `>=`). An unpinned build is not reproducible and not auditable.
- Keep the dependency list minimal. Every added package is added attack surface and another thing that can break twenty minutes before a demo.
- Prefer well-maintained, widely-used libraries: NumPy, Pandas, SciPy, CVXPY, Streamlit, Plotly, pytest.
- Do not add TradingAgents, large multi-agent frameworks, or unnecessary MCP servers.

See `requirements.txt` for the live list. Currently installed and verified:

```
jugaad-data @ git+https://github.com/jugaad-py/jugaad-data.git   # resolves to 0.35.5
numpy==2.4.6
pandas==3.0.5
```

The remainder (scipy, cvxpy, pyyaml, pyarrow, streamlit, plotly, pytest) are listed
commented-out in `requirements.txt` and get uncommented as each build phase starts.

### On the GitHub dependency

`jugaad-data` is installed **from GitHub, not PyPI** — a deliberate project decision.
Two consequences to be aware of:

1. **A git URL is not a pin.** `git+https://…` resolves to whatever `HEAD` is at install
   time. For a reproducible build, pin the commit:
   `jugaad-data @ git+https://github.com/jugaad-py/jugaad-data.git@<sha>`.
   This matters more than usual here, because reproducibility is a stated requirement
   (`NFR-012`) and the committed cache snapshots are the demo's safety net.
2. **Installing from a git URL executes that repo's build backend.** Acceptable for a
   known, widely-used project; worth stating explicitly since it is a wider trust
   surface than a PyPI wheel.

---

## 8. Logging

| Do | Do not |
|---|---|
| Log what was attempted, with which identifiers, and what happens next | Log API keys, tokens or connection strings |
| Log control decisions and breaker activations | Log full config or environment objects |
| Log validation findings | Print tracebacks into the UI |
| Use `logger`, with levels | Use `print` |

```python
# WRONG
logger.info("Config: %s", config)             # may contain the key

# RIGHT
logger.info("Provider=%s policy_version=%s", config.provider, config.policy_version)
```

---

## 9. What the audit log is and is not

The audit log is a **record of decisions**, not a security control. It answers "what happened and who approved it" for a single trusted local user.

It deliberately provides no tamper-evidence: no signing, no hash chain, no write-once storage. A production system handling real capital would need those. Saying so explicitly is better than implying the prototype has integrity guarantees it does not — and the append-only discipline in the application code is about **correctness and honesty**, not about defending against an attacker with filesystem access.

---

## 10. Pre-submission security checklist

- [ ] No secrets in the repository, including history (`git log -p | grep -iE "api[_-]?key|secret|token"`)
- [ ] `.env` git-ignored; `.env.example` has placeholders only
- [ ] No `eval`, `exec`, or `pickle.load` on external data
- [ ] All SQL parameterised
- [ ] `yaml.safe_load` everywhere
- [ ] No `unsafe_allow_html=True` on dynamic content
- [ ] No bare `except:`
- [ ] LLM output never parsed back into decision state `[INV-1]`
- [ ] System runs fully with no API key
- [ ] Dependencies pinned
- [ ] No secrets in logs or the UI
- [ ] `showErrorDetails = false` for the demo build
- [ ] The database file is not committed
