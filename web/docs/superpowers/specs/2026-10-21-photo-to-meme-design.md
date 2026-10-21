# Photo-to-meme demo design

## Intent

Let a tester upload a photo and receive that same photo with one of three meme caption options, alongside the matching meme templates and credited community examples that informed the suggestion. Prompts and copy must suit varied role-play personas; never assume a tester's profession or identity.

## User flow

2. The tester selects an image. The browser decodes it, scales its longest side to at most 1280 pixels, and encodes JPEG. The server accepts only validated JPEG data up to 5 MiB and never stores or logs image bytes.
3. The server sends the photo to Gemini to produce one concise description of the situation, emotion, and notable objects. It must not identify people or infer who they are.
4. The server sends only that description to the configured match service (`POST /match`, `k: 12`, `captions_per_template: 8`) with `X-Match-Key`. It asks Gemini to choose the best returned template and write three caption sets, exactly `box_count` texts each. Public examples are style/context only; generated texts must not repeat any example verbatim.
5. The browser renders each caption set over the user's resized photo in classic white Impact-style text with a black outline. One box is a single block, two boxes go top/bottom, and three or more are stacked; each block wraps to at most two lines.
6. Results include the generated PNG, three selectable caption options, matched template thumbnails/name/source links, and community-example author/source credits.

## Safety and privacy

- `GEMINI_API_KEY`, `MATCH_SERVICE_URL`, and `MATCH_SERVICE_KEY` remain server-side.
- The uploaded image is passed to Gemini for description, never to the match service, and is not persisted by this application.
- Accept a JPEG data URL only, verify its JPEG bytes and dimensions, and reject payloads over 5 MiB. Bound JSON parsing and upstream response sizes/timeouts.
- Match-service errors/timeouts and Gemini failures produce short, friendly errors without upstream details or secrets.
- Use only fake service/Gemini fixtures in automated tests; never call real APIs.

## UI copy

Explain in four short plain-language lines: choose a photo (resized to 1280 px); Gemini describes the scene without identifying anyone; the description finds meme formats and public examples; Gemini selects a fit and writes three fresh captions, then the browser captions the user's photo. Clarify that the photo is sent to Gemini, not to the matcher, and is not saved by the app.

## Scope boundaries

- Keep the existing text-prompt workflow working.
- No dataset ingestion, image storage, user accounts, public gallery, or deployment.
- No identity recognition or appearance-based humor.
- Match-service contract v1 is fixed; use its supplied fields and `POST /match` endpoint.

## Implementation choices

- Use the existing dependency-free Node HTTP/Vercel handler and native browser modules.
- Keep resized image and canvas output in browser memory. The endpoint returns description, selected match, all shortlisted matches, and three text arrays; the browser creates the PNG locally.
- Call the match service with a 15-second timeout and Gemini with bounded timeouts. Never log request bodies.
