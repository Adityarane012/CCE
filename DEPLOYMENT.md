# Deploying CCE

Two things get deployed, to two different places, for a reason worth stating
up front.

| What | Where | Why there |
|---|---|---|
| The dashboard | **Streamlit Community Cloud** | It is a Streamlit app: one long-lived process holding a WebSocket per viewer |
| The pitch page | **Vercel** | Static HTML, instant, and it gives you the `vercel.app` URL |

> **Vercel cannot host the dashboard.** This is not a configuration problem and
> there is no flag that fixes it. Vercel runs stateless serverless functions
> with an execution limit and no long-lived WebSocket support; Streamlit needs
> a persistent process that keeps a socket open per session and holds server-
> side state between reruns. Anyone who tells you to add a `vercel.json` and a
> Python runtime is describing a deployment that starts and then hangs on the
> first interaction.
>
> The split below gets you the Vercel URL anyway, with the live app one click
> from it.

---

## 1. The dashboard → Streamlit Community Cloud

Free, no card, purpose-built for exactly this. About five minutes.

1. Push to GitHub (already done — the repo is public).
2. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with
   GitHub.
3. **New app** → **Deploy a public app from GitHub**, then:

   | Field | Value |
   |---|---|
   | Repository | `Adityarane012/CCE` |
   | Branch | `main` |
   | Main file path | `app.py` |
   | App URL | `capitalcontrol-engine` |

4. Open **Advanced settings** and set **Python version to 3.11**. Do not skip
   this — `requirements.txt` pins `numpy==2.4.6` and `pandas==3.0.5`, and a
   different interpreter can resolve to wheels that were never tested here.
5. **Deploy.** First build takes 3–6 minutes, mostly `cvxpy` compiling.

You do **not** need to set any secrets. The app runs with no API key and no
network — that is a deliberate property, not a limitation (`FR-146`).

### If the build fails

| Symptom | Cause | Fix |
|---|---|---|
| `cvxpy` wheel build fails | No compiler on the builder | It has prebuilt wheels for 3.11; confirm the Python version is 3.11, not 3.13 |
| `jugaad-data` install fails | It installs from a pinned git commit, not PyPI — the most fragile step in the build | **Comment that line out of `requirements.txt` and redeploy.** See below: it is not a runtime dependency |
| App starts, then "no market data" | `data/cache/prices.parquet` missing | Confirm it is committed — `git ls-files data/cache/` must list it |
| Blank page after a click | An exception being swallowed | `showErrorDetails` is on in `.streamlit/config.toml`; the real message will render |

### If `jugaad-data` blocks the build, delete it

It installs from a pinned git commit rather than PyPI, which makes it the one
line most likely to fail on a cloud builder. **The deployed app never imports
it.** `cce/data/jugaad_provider.py` imports `jugaad_data` lazily, inside the
methods that fetch live prices, and the demo runs on `CachedDataProvider`
against the committed parquet snapshot.

Verified by blocking the import entirely and running a full decision cycle:

```
WITH jugaad-data ABSENT:
  provider     CACHED
  portfolio    100.0 Cr
  risk state   GREEN   vol 10.35%
  OPTIMAL      approvable=False
  SAFE         approvable=True
```

So if the build fails on that line, comment it out and redeploy. What you lose
is `CCE_DATA_PROVIDER=live` and `scripts/build_cache.py` — neither is used by
the demo, and both still work locally where the full `requirements.txt` is
installed. It stays in the file because that file is the reproducible
development environment (`NFR-012`), not the minimum runtime.

### What to expect at runtime

The audit database (`data/cce.db`) is created on first use and lives on an
**ephemeral filesystem** — it resets when the app sleeps or redeploys. That is
fine for a demo: the schema rebuilds from migrations automatically, and drill 3
in `scripts/demo_drill.py` exists precisely to prove that deleting the database
leaves a working system. It does mean decision history does not survive a
restart, so do not promise a judge a week of audit trail on the hosted
instance.

Free-tier apps sleep after inactivity and take ~30 seconds to wake. **Open the
app five minutes before you present.**

---

## 2. The pitch page → Vercel

Static HTML in `web/`. No build step, no dependencies.

### Via the dashboard

1. **[vercel.com/new](https://vercel.com/new)** → import `Adityarane012/CCE`.
2. Framework preset: **Other**.
3. Root directory: leave as the repo root — `vercel.json` points at `web/`.
4. Leave Build and Install commands **empty**. `vercel.json` already sets both
   to `null`.
5. **Deploy.**

### Via the CLI

```bash
npx vercel --prod
```

### Why the config disables the build

`requirements.txt` sits at the repo root, and Vercel's framework detection will
happily conclude this is a Python project and try to build it. It is not — the
Python lives on Streamlit Cloud. `vercel.json` sets `framework`, `buildCommand`
and `installCommand` to `null` so nothing is detected, installed or built, and
`outputDirectory: "web"` serves the static page directly.

### Point it at your live app

`web/index.html` links to `https://capitalcontrol-engine.streamlit.app`. **Change that to
whatever URL Streamlit actually gave you** — it appears twice, in the hero
button (`id="app"`):

```bash
sed -i 's|https://capitalcontrol-engine.streamlit.app|https://YOUR-APP.streamlit.app|g' web/index.html
```

Then commit and push; Vercel redeploys on push.

---

## 3. Running it locally

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt           # Unix

.venv/Scripts/python.exe -m pytest -q          # 571 passed, 0 skipped
.venv/Scripts/streamlit.exe run app.py         # http://localhost:8501
```

Python 3.11+. No network and no API key required.

---

## 4. Configuration

Every value has a working default; `.env` is optional. Copy `.env.example` to
`.env` only if you want to change something.

| Variable | Default | Notes |
|---|---|---|
| `CCE_DATA_PROVIDER` | `cached` | `cached` \| `live`. Cached is the default and the demo must work on it |
| `CCE_LLM_ENABLED` | `false` | The deterministic narrator produces the full briefing without it |
| `CCE_LLM_API_KEY` | *(unset)* | Optional. Never commit a real key |
| `CCE_DB_PATH` | `./data/cce.db` | Rebuilt from migrations if absent |
| `CCE_RANDOM_SEED` | `42` | Seeds every stochastic routine (`NFR-012`) |
| `CCE_LOG_LEVEL` | `INFO` | |

On Streamlit Cloud, set these under **Settings → Secrets** if you need them.
Secrets go in `.streamlit/secrets.toml`, which is git-ignored by name.
`.streamlit/config.toml` **is** committed — it carries the theme and server
settings and holds nothing sensitive.

---

## 5. Before you present

```bash
.venv/Scripts/python.exe scripts/demo_drill.py     # 6 failure drills
.venv/Scripts/python.exe scripts/demo_figures.py   # re-derive every quoted number
```

`demo_figures.py` is the authority for every figure in
[`docs/14-DEMO-SCRIPT.md`](docs/14-DEMO-SCRIPT.md). If the two disagree, the
script is wrong — `docs/10-RULES.md` §5.3 forbids speaking a number aloud that
a real run has not produced.

Checklist:

- [ ] Streamlit app is awake (open it five minutes early)
- [ ] `demo_drill.py` — all six pass
- [ ] `demo_figures.py` — output matches the demo script
- [ ] Vercel page links to the correct Streamlit URL
- [ ] A local instance running as a fallback, in case the hosted one sleeps

**Have the local instance running regardless.** A free-tier app that decides to
cold-start during your third sentence is a bad thirty seconds, and the demo is
fully offline-capable — that is the whole point of the committed cache.
