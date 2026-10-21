# Match service contract (v1)

A small Python HTTP service that answers: "given a one-sentence description of a photo, which
meme templates fit it, and what captions do people write on them?"  It holds the SigLIP 2 *text*
encoder plus precomputed picture vectors for ~1,500 templates (option E: description text vs
template pictures). It never receives the uploaded photo, only text.

Base URL: `MATCH_SERVICE_URL` (default `http://127.0.0.1:8808`).
Auth: every request except `/health` needs header `X-Match-Key: <MATCH_SERVICE_KEY>`.

## GET /health
200 `{"ok": true, "templates": 1500, "model": "siglip2-so400m-patch14-384"}`

## POST /match
Request JSON:
```json
{"description": "A smiling man reading an open book in a bookstore", "k": 12, "captions_per_template": 8}
```
- `description`: string, 3..600 chars (required). `k`: int 1..30 (default 12).
  `captions_per_template`: int 0..20 (default 8).

200 response:
```json
{
  "model": "siglip2-so400m-patch14-384",
  "matches": [
    {
      "rank": 1,
      "score": 0.0712,
      "template": {
        "asset_id": 63592143, "slug": "Peter-parker-reading-a-book",
        "name": "Peter parker reading a book",
        "source_url": "https://imgflip.com/meme/63592143/Peter-parker-reading-a-book",
        "image_url": "https://i.imgflip.com/1a2b3c.jpg",
        "width": 200, "height": 450, "safe_for_work": true,
        "box_count": 2, "boxes_explicit": true,
        "boxes": [{"x": 0, "y": 0, "w": 100, "h": 50, "rotation": 0, "font": "impact",
                   "font_color": "#ffffff", "outline_color": "#000000"}]
      },
      "example_captions": [
        {"box_texts": ["HOW TO KEEP A RELATIONSHIP", "FIRST YOU NEED TO BE IN A RELATIONSHIP"],
         "author": "Running_Mark", "url": "https://imgflip.com/i/5mh1bf", "upvotes": 23}
      ]
    }
  ]
}
```
- `score` is cosine similarity; only meaningful for ranking within one response.
- `boxes` is empty when `boxes_explicit` is false (imgflip default layout of `box_count` boxes).
- `example_captions` are community captions, most upvoted first; always show `author` + `url`.
- Templates with `safe_for_work: false` are never returned.
- `image_url` points at imgflip's own CDN; we return URLs, not image files.

Errors: 400 `{"error": "..."}` bad input; 401 bad/missing key; 503 model still loading.

## Out of scope for this service
Photo description, caption writing, rendering text on the photo, and all UI belong to the web app.
