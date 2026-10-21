# Deploying to Vercel

This project uses Vercel's Node.js function runtime for `/api/*` and serves the files in `public/` as static assets.

## Private photo-to-meme research demo

Set these server-side environment variables before sharing the app:

- `GEMINI_API_KEY`: required for describing photos and drafting the three captions. `GEMINI_MODEL` is optional and uses the existing default when omitted.
- `MATCH_SERVICE_URL`: match-service base URL; defaults to `http://127.0.0.1:8808` for local development. A deployed Vercel function cannot reach a service running on your laptop's loopback address, so use a reachable service URL for a deployed demo.
- `MATCH_SERVICE_KEY`: sent only from the server to the match service in `X-Match-Key`.
- `SITUATION_MATCH_URL`: base URL of **match service v2** (see the repository README). It powers the "Situation" and "Photo + situation" modes (`POST /api/situation-meme`), which also need `GEMINI_API_KEY` (embeddings and caption adaptation) and the same `MATCH_SERVICE_KEY`. The "Photo only" mode keeps using `MATCH_SERVICE_URL` (match service v1).

The photo flow resizes uploads in the browser to at most 1280 pixels on the longest side. The server accepts JPEG photos up to 5 MiB, sends the image to Gemini for a short scene description, and sends only that text description to the match service. The app does not save uploaded photos; the browser renders the captioned PNG locally.

The `/api/photo-meme` route expects the match service contract v1 `POST /match` response. If the service is unavailable or slow, the app shows a retry message. Tests use fake Gemini and match-service responses and never make paid API calls.

1. Sign in to Vercel from the project directory with `vercel login`.
2. Add `IMGFLIP_API` in the Vercel project’s Environment Variables settings. Select Production (and Preview if needed); keep the value out of source control and deployment command arguments.
3. Deploy with `vercel --prod` and follow the prompts to create or link the Vercel project.
4. If using a custom domain, add `APP_ORIGIN` as its full origin, such as `https://memes.example.com`. The generated Vercel deployment and project production URLs are also allowed automatically.
5. Add an appropriate Vercel Firewall rate limit for both `POST /api/generate` and `POST /api/photo-meme`, using the source IP as the key and returning `429` when limited. This limits casual overuse, not deliberate abuse or paid API spend. Review the Firewall pricing prompt when enabling it. [Rate-limiting setup](https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting) · [pricing](https://vercel.com/docs/vercel-firewall/vercel-waf/usage-and-pricing).

Add `GEMINI_API_KEY` to Vercel Production to enable Gemini. Gemini creates distinct joke angles and, after Imgflip picks each template, rewrites captions to fit that template's exact number of text boxes. The optional “Let Gemini look at the meme images” checkbox also sends the generated Imgflip images (up to 1 MB each) to Gemini for visual context. If Gemini is missing or temporarily unavailable, or an image cannot be read, the app falls back to Imgflip's captions or text-only captioning. The key is used server-side only. The default model is `gemini-3.6-flash`; `GEMINI_MODEL` can override it. Gemini API billing is separate from Imgflip Premium.

After adding or changing environment variables, redeploy so the function receives them. Select 1, 5, or 7 options in the app. Matched batches make one `/automeme` request, one `/ai_meme` request per option, and one `/caption_image` render per option when Gemini caption writing succeeds; general batches skip `/automeme`. This means larger batches make more Imgflip calls. Generation requires Imgflip API Premium. Check Imgflip's [current API documentation](https://imgflip.com/api) for pricing and included requests.

The Origin check protects against browser cross-site requests; it does not stop direct API clients. Keep the Firewall rule enabled when sharing the public URL because each successful generation can consume paid Imgflip requests. Rate limits are per source IP, so this is a sensible guard for a small friend demo, not a guarantee against deliberate abuse or shared-NAT users.

## Situation and photo + situation modes

`POST /api/situation-meme` accepts `{ "situation": "...", "photo": "data:image/jpeg;base64,..." }` (photo optional). The server embeds the situation (and photo) with Gemini Embedding 2, sends the vectors to match service v2, then asks Gemini to adapt the closest real captions. Gemini requests use `responseMimeType` and `responseSchema` (the older `responseFormat` field is rejected with HTTP 400) and a large `maxOutputTokens`, because the model's hidden thinking tokens count against it. `POST /api/feedback` logs 1 to 5 ratings to the server log only; nothing is stored.
