# Meme Moment

Turn a real-life moment into memes built from **real viral captions**, adapted to you.

Tell it a **situation**, give it a **photo**, or give it **both**. Instead of asking an AI to invent a joke from nothing, Meme Moment first searches ~19,000 real meme captions and 1,500 meme formats for the closest ones that already landed, then asks Gemini to adjust only what doesn't fit yet, using *your* details. Every result credits the real caption it came from.

> Research prototype built for an academic demo. Live deployment: <https://super-meme-three.vercel.app>

| Mode | You give | You get |
|---|---|---|
| **Situation** | a sentence | adapted captions drawn on the real meme template pictures |
| **Photo only** | a photo | three captions for the best-fitting template, drawn on your photo |
| **Photo + situation** | a photo and the story behind it | ~5 memes drawn on your photo, using what is visible in it |

The situation is treated as the *reason behind the photo*: if the light was switched on while you worked in the dark, the jacket over your head is a reaction to the light.

## How it works

```
 situation ─┐                          ┌─ 1 words  ↔ caption words         (BM25 keywords)
            ├─► Gemini Embedding 2 ───►├─ 2 situation ↔ real captions      (meaning)
 photo ─────┘   768-number vectors     ├─ 3 situation ↔ meme pictures      (text ↔ image)
                                       ├─ 4 photo     ↔ meme pictures      (image ↔ image)
                                       └─ 5 photo     ↔ real captions      (image ↔ text)
                                                   │ rank + merge, round-robin pool of 8 templates
                                                   ▼
                           Gemini sees the photo + situation + 8 templates × 3 real captions
                           and ADAPTS one real caption per option (keeps structure and wording
                           where they still fit; changes only what the situation needs)
                                                   ▼
                           server validates every option → browser draws the captions
                           on your photo / the template picture, credits the original author
```

* **Embeddings.** Gemini Embedding 2 puts text and images in one 768-dimensional space, so a sentence can be compared directly with a picture. Closeness is cosine similarity. Stored vectors use `RETRIEVAL_DOCUMENT`, queries use `RETRIEVAL_QUERY`.
* **Five searches, one pool.** Each search ranks the 1,500 templates (a template scores as its best caption or picture). Rankings are merged by reciprocal rank fusion with hand-set weights (words 1.0, situation↔captions 1.0, photo↔pictures 0.75, situation↔pictures 0.5, photo↔captions 0.4). The pool of 8 is filled round-robin, one slot at a time per search, so no search can crowd out another. Inside a template, captions are ordered by closeness to the situation plus a small upvote bonus.
* **Adaptation, not invention.** Options naming an unknown template, the wrong number of text boxes, over-long text, or a repeated template are discarded; at least three must survive. Near-copies of a real caption are allowed on purpose, because the original and its author are credited.
* **Explainable.** Each card says which searches found it (“your photo ↔ meme pictures”, …), and the page has an *Under the hood* section with a worked example using real scores.
* **Privacy.** The photo goes to Gemini only (embedding and adaptation). The matcher receives your words and vectors, never the image. Nothing is stored; ratings are only written to the server log.

## What was measured

Leave-one-out test: take one real caption as the "situation", hide it, and check whether search recovers its template among 1,500 (2,500 sampled captions, random ≈ 1.3% in the top 20).

| Method | Right template in top 20 |
|---|---|
| Gemini Embedding 2 + keywords (merged) | **41.0%** |
| Gemini Embedding 2 | 40.6% |
| Keywords (BM25) | 34.4% |
| SigLIP 2 text encoder | 29.8% |
| MiniLM-L6 | 26.9% |

Not measured yet: whether people find the results funnier than a plain AI caption (the 1 to 5 buttons on each card are there to find out), the photo-based searches on their own (their scores are nearly tied in the worked example, so they mostly add variety), and the merge weights (hand-set). Upvotes are only a rough stand-in for “went viral”, and the collection leans toward older, popular templates.

An earlier SigLIP 2 experiment (`spike_bakeoff/`) found that matching a photo's own embedding against template pictures ranked the "right" template 230th of 1,500 on a test photo, while describing the photo in text first ranked it 5th. That is why the final design leans on text and Gemini embeddings.

## Repository layout

| Path | What it is |
|---|---|
| `imgflip_memes/` | Polite scraper → SQLite: templates, boxes, tags, images, example captions with authors; CSV export |
| `match_service/` | Retrieval library and HTTP API: BM25, vector search, rank fusion, candidate pool, `found_by` trace. Contract in `CONTRACT.md` |
| `match_vercel_v2/` | **Match service v2** deployment (numpy only, no model): used by *Situation* and *Photo + situation* |
| `match_vercel/` | Legacy **match service v1** (SigLIP 2 text tower, sharded into <100 MB files): used by *Photo only* |
| `retrieval_v2/` | Gemini embedding pipeline (`embed_gemini.py`) and a quick quality check |
| `retrieval_bench/` | The leave-one-out benchmark behind the table above |
| `spike_bakeoff/` | Throwaway SigLIP / Jina experiments and the caption-on-photo script |
| `web/` | The website and API routes (Node 22, no dependencies), deployed on Vercel |
| `tests/` | Python tests (scraper, matcher, exporters) with saved page fixtures |

## Quick start

```bash
# Python 3.12+ (tested on 3.13)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q                      # 195 passed, 1 skipped (the skip needs torch)

cd web && npm test && cd ..              # 118 tests, no network, no paid APIs
```

### Rebuild the data (not included in this repository)

```bash
# 1. Scrape (about 1 request / 1.5 s; resumable; images and example captions included)
python -m imgflip_memes --limit 1500                  # -> data/memes.db, data/images/
python -m imgflip_memes.export                        # optional CSVs in data/export/

# 2. Export templates + captions, then embed them with Gemini
python -m match_service.export_templates --db data/memes.db --out match_service/data
export GEMINI_API_KEY=...                             # never commit this
python retrieval_v2/embed_gemini.py                   # -> retrieval_v2/pictures.npy, captions.npy
python retrieval_v2/check.py                          # leave-one-out sanity check
```

### Deploy match service v2 (Vercel)

```bash
cd match_vercel_v2
python tools/make_bundle.py                           # copies code + data + vectors (~34 MB)
vercel link --yes --project match-service-v2
printf '%s' "$MATCH_SERVICE_KEY" | vercel env add MATCH_SERVICE_KEY production --sensitive
vercel deploy --prod --yes
```

### Run / deploy the website

```bash
cd web
cp .env.example .env     # set GEMINI_API_KEY, MATCH_SERVICE_KEY, SITUATION_MATCH_URL (https URL of v2)
npm run dev              # http://127.0.0.1:3000
vercel deploy --prod --yes
```

Environment variables are documented in `web/.env.example` and `web/DEPLOYING.md`. *Photo only* additionally needs `MATCH_SERVICE_URL` (match service v1) and the original prompt tool needs `IMGFLIP_API` (Imgflip API Premium).

## Things learned the hard way

* Gemini's `generationConfig` needs `responseMimeType` + `responseSchema`; the `responseFormat` shape returns HTTP 400. Hidden "thinking" tokens count against `maxOutputTokens`, so give it room (4096 and up).
* Vercel rejects any single uploaded file over 100 MB, and a Python bundle over 500 MB needs `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`. The default PyPI `torch` is the multi-GB CUDA build; pin `torch==X+cpu` from PyTorch's CPU index.
* SigLIP's 428M-parameter vision tower took ~9 s per image on a laptop CPU, far too slow for serverless, which is why the final design embeds with Gemini's API and keeps the matcher model-free.
* The mocked tests all passed while the real Gemini API rejected every request. Keep at least one test that pins the exact request shape, and run one real call before shipping.

## Data and licensing

The scraped data (meme pictures, captions, usernames) is **not** in this repository and must not be committed: the pictures are third-party images and the captions belong to their authors. [Imgflip's terms](https://imgflip.com/terms) say content may not be used without its owner's permission. The scraper only follows what `robots.txt` allows and is deliberately slow, but that is not permission. This project is a private research prototype and is not affiliated with Imgflip; get permission or use a licensed collection before any public or commercial use. The `tests/fixtures/` HTML files are small saved copies of Imgflip pages used only by the parser tests. They will be removed on request from Imgflip or any author.

No license has been chosen yet (all rights reserved).

## Roadmap

* Store the 1 to 5 ratings and compare against a plain-LLM baseline on a fixed set of situations.
* Tune merge weights and the pool size with those ratings.
* Add newer templates (the collection has only a handful from 2026).
* Retire match service v1 by moving *Photo only* onto the same Gemini-embedding search.
