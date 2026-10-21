# Prompt-to-meme MVP design

## Intent

Build the first usable version of the user's Supermeme-inspired product in the currently empty `super-meme` workspace. The MVP should help someone who knows the situation they want to joke about but does not know which meme template to choose. The success case is: enter a situation, receive a fitting editable meme, make a quick change, and download it.

The current Supermeme homepage describes this prompt-first loop as its key workflow: understand the situation, match a template, draft captions, and let the user edit the result before download. REA controlled browser observations of `https://supermeme.ai/` and `/text-to-meme` support that workflow (Evidence IDs `ev_d860b812447937fb8a758e768777c1f3ddabdd94442eb6ebbac54c39a06de200` and `ev_b81642c2c6770e93866f6eda5dcdb8a91cd2a30ae67785610128cc38e2a59899`). These observations establish the public product flow and page claims; they do not establish Supermeme's private backend implementation.

## MVP user experience

The first page has a prompt composer and a clear generate action. A user enters a short situation in natural language. The app generates one result, showing the meme image and the selected template identifier (and a name only when available from the provider). The user can edit each generated caption in text fields, regenerate the image, request another result explicitly, or download the current image. Loading, API failure, and missing-key states should be understandable without exposing configuration details.

Caption controls are driven by the actual text array returned by Imgflip's AI-meme endpoint. Do not assume every meme has two boxes. When rendering edits, submit one `boxes` entry per caption and omit coordinates so Imgflip applies that template's configured default positions. This uses Imgflip's template layout rather than trying to erase text from a finished image.

## Proposed Imgflip flow

For each user-requested result:

1. Send the prompt to Imgflip `/automeme` to get its chosen template ID. This endpoint chooses a template from its top 2,048 based on the input text, but does not return editable caption strings.
2. Call `/ai_meme` with that template ID and a concise prefix derived from the original prompt to obtain a rendered result plus its `texts` array. Imgflip documents a 64-character maximum for `prefix_text`; the app may accept a longer prompt for template selection but will trim the caption seed to 64 characters at a word boundary and tell the user when it had to shorten it. If Imgflip rejects the selected template, offer a separate user-triggered general-generation action without the selected ID; do not silently make that extra provider call.
3. When the user edits captions, call `/caption_image` for that template ID with the current `boxes` text. Keep the API's image URL as the displayed/download target.

These endpoints require Imgflip API authentication. Imgflip documents `/automeme` and `/ai_meme` as Premium features with 50 included creations per month per endpoint and $0.02 per creation after the included amount. The proposed two-stage flow therefore uses two Premium calls for an initial result; edited renders use `/caption_image`, which is a free endpoint but carries the Imgflip watermark by default. No watermark-removal setting is included in this MVP. Source: https://imgflip.com/api (consulted 2026-10-20).

## Technical shape

This workspace contains no application source or package manifest. The initial implementation choice was a small TypeScript web app using Next.js and React. During implementation, the npm registry was unreachable (`ENOTFOUND registry.npmjs.org`) and none of Next.js, React, Vitest, Vite, or TypeScript were available locally. Since the framework was an implementation default rather than a user requirement, the implementation uses only the already-installed Node.js runtime and browser-native HTML, CSS, and JavaScript. This keeps the same user experience and server-side credential boundary without requiring a package download.

Keep `IMGFLIP_API` server-side. Implement narrow server routes for generation, caption rendering, and safe image download; never expose the bearer key to browser code, log it, or send it in a URL. The browser should receive only the data needed to show a template/result and edit its caption strings. Use the server-side download route, allowing only `https://i.imgflip.com/` URLs and rejecting redirects.

The generation process must not start automatically on page load. A user click initiates the two generation calls. “Try another” initiates a new pair of calls, making potential API usage visible through the interaction. Edited caption renders are also explicitly user initiated. Surface provider errors without exposing request authorization data.

## Goals

- Prompt-first template matching and meme creation.
- Editable generated captions with the right number of controls for the returned result.
- A simple, polished, responsive web interface that works without an account.
- Download or open the finished image.
- Keep the Imgflip credential on the server and avoid unintended generation calls.

## Non-goals for this MVP

- Reproducing Supermeme's complete paid product, private backend, or exact visual design.
- A curated semantic database of templates, custom embeddings, or human curation workflows.
- User accounts, saved libraries, history, payments, brand kits, custom uploads, GIFs, multilingual controls, or social publishing.
- Removing the Imgflip watermark or copying Imgflip's finished output to permanent storage.

## Constraints and risks

- Imgflip's `/automeme` is an approximate match over its own top 2,048 and its docs say shorter, simpler prompts work better; it is not Supermeme's documented curated semantic retrieval.
- `/automeme` returns an image URL and template ID but not the caption text; `/ai_meme` is needed to obtain editable caption strings.
- Imgflip's current docs specify a bearer API key. The local `.env` contains a non-empty `IMGFLIP_API` setting, but this design has not made a paid API request or verified that the value is valid or Premium-enabled.
- The first prompt result uses two Premium generation calls. The user should be aware of the documented usage pricing before testing beyond included credits.
- Imgflip-generated image URLs are public to anyone who knows the URL and may be deleted if they receive few views; do not treat them as private or permanent storage.
- Third-party meme-template rights vary. The MVP should not make blanket commercial-use promises.
- If the automeme-selected ID cannot be reused by `/ai_meme` or `/caption_image`, this is a provider constraint that should be confirmed by a user-triggered test before changing the flow.

## Decisions left to implementation

- Exact colors, typography, layout spacing, and small-screen behavior.
- Input length limits and the precise wording of empty, loading, success, and error states.
- Framework implementation details that do not change the user-facing scope.
- Whether to expose Imgflip's template name and source page link alongside the generated result.

## Implementation ruling

Ruling: use a dependency-free Node.js HTTP server and native browser UI instead of Next.js/TypeScript — npm package acquisition fails in this environment and required packages are not cached, while Node.js 22 is available; the user-facing workflow and API credential handling remain unchanged; cost if wrong: the app uses a smaller, less feature-rich framework and should be ported if the project later requires Next.js or TypeScript.

