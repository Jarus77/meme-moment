# Prompt-to-meme MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a prompt-first meme creator that uses Imgflip to select a template, generate editable captions, render edits, and download the result.

**Architecture:** A dependency-free Node.js HTTP server serves a native HTML/CSS/JavaScript interface and JSON API endpoints. A typed-by-contract Imgflip client keeps the bearer key on the server and performs the selected-template generation flow (`automeme` → `ai_meme`) and caption rendering (`caption_image`). A host-restricted download route returns generated images as attachments.

**Tech Stack:** Node.js 22 ESM, built-in `node:http`, `node:test`, browser-native HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-20-prompt-to-meme-mvp-design.md`

## Global Constraints

- Keep `IMGFLIP_API` server-side and never log or return its value.
- A user action must initiate each generation or render; do not generate on page load.
- Use Imgflip `/automeme` to select a template and `/ai_meme` with that template ID to obtain editable text.
- Create one editor control for each string in Imgflip's returned `texts` array; do not assume a fixed number of boxes.
- Submit edited text as one `boxes` item per caption and omit coordinates so Imgflip uses its default positions.
- Limit `/ai_meme` `prefix_text` to 64 characters at a word boundary and tell the user when a longer prompt was shortened.
- Do not enable watermark removal, template uploads, GIFs, accounts, history, or paid product features.
- Do not silently make an additional paid generation call as a fallback; offer an explicit retry without a selected template.
- Never proxy a user-supplied arbitrary URL; the download endpoint accepts only HTTPS URLs whose hostname is exactly `i.imgflip.com`, and it rejects redirects.
- Use built-in Node modules only because npm package acquisition is unavailable in this environment.

## Review Focus

- Empty/oversized prompt or caption input: reject clearly before a provider request; tests cover request validation.
- Missing `IMGFLIP_API`: return a setup error with no secret detail; test response and confirm no provider request.
- Provider returns an API failure or malformed/missing template ID/texts/image URL: return a safe, useful error; test provider response parsing.
- Meme returns one, two, or more captions: editor renders the exact number and the caption route sends the same count; test dynamic count and inspect the browser UI.
- Download URL is external, malformed, or redirects: reject before following it; test protocol/host/redirect allowlist.

---

## File Map

- Create `package.json` with `dev`, `start`, `test`, `lint`, and `build` scripts; no runtime dependencies.
- Create `.env.example` with only `IMGFLIP_API=` and update `.gitignore` to exclude real `.env` values and generated files.
- Create `server.mjs` for static files and HTTP routes.
- Create `lib/validation.mjs` for bounded JSON bodies and request validation.
- Create `lib/imgflip.mjs` for typed-by-contract Imgflip requests, response validation, and the two-step generation flow.
- Create `public/index.html`, `public/app.js`, and `public/styles.css` for the prompt-first editor.
- Create `tests/imgflip.test.mjs`, `tests/server.test.mjs`, and `tests/ui.test.mjs` using the built-in Node test runner.
- Preserve the existing `.env`, `outputs/`, and curation workbook.

## Task 1: Scaffold and establish tests

**Files:** `package.json`, `.gitignore`, `.env.example`, `tests/ui.test.mjs`.

**Interfaces:** `npm test` runs Node's built-in test runner; `npm run dev` and `npm start` load an existing `.env` if present and start `server.mjs`; `npm run lint` and `npm run build` run Node syntax checks.

- [ ] Add package scripts and ignore rules without reading, overwriting, or copying `.env` contents.
- [ ] Add a failing UI smoke test that reads `public/index.html` and asserts the page has the app title, prompt input, and generate button.
- [ ] Run `npm test -- --test-name-pattern="generator shell"` and confirm it fails because the page does not exist yet.
- [ ] Create the minimum semantic HTML shell with accessible prompt and generate controls.
- [ ] Run the smoke test and confirm it passes; run `npm run build` and `npm run lint`.

## Task 2: Implement and test the Imgflip client

**Files:** `lib/imgflip.mjs`, `tests/imgflip.test.mjs`.

**Interfaces:**

- `createImgflipClient({ apiKey, fetchImpl })` returns `generatePromptMeme(prompt)`, `generateGeneralMeme(prompt)`, and `renderCaptionMeme(templateId, texts)`.
- `generatePromptMeme` calls `/automeme`, then `/ai_meme` with the selected `template_id` and a prefix derived from the prompt, returning `{ templateId, imageUrl, pageUrl, texts, promptWasShortened }`.
- `generateGeneralMeme` calls only `/ai_meme` without a selected template after explicit user action.
- `renderCaptionMeme` calls `/caption_image` with `boxes[n][text]` fields and returns `{ imageUrl, pageUrl }`.
- Provider errors expose safe public messages and internal categories without retaining/logging authorization values.

- [ ] Add failing tests for Bearer auth, form encoding, two-step generation order, word-boundary 64-character prefix, 1/3 caption arrays with no coordinates, invalid provider responses, and provider failures.
- [ ] Run `node --test tests/imgflip.test.mjs` and confirm tests fail because the client does not exist.
- [ ] Implement the client with injected `fetchImpl` and key so tests make no live API calls.
- [ ] Run `node --test tests/imgflip.test.mjs` and confirm all provider-client tests pass.

## Task 3: Add generation and caption API routes

**Files:** `lib/validation.mjs`, `server.mjs`, `tests/server.test.mjs`.

**Interfaces:**

- `POST /api/generate` accepts `{ prompt: string, strategy?: "matched" | "general" }`; success returns `{ templateId, imageUrl, pageUrl, texts, matchedTemplate, promptWasShortened }`. Default strategy is `matched`; `general` skips `/automeme` and is called only after an explicit UI action.
- `POST /api/caption` accepts `{ templateId: string, texts: string[] }`; success returns `{ imageUrl, pageUrl }`.
- Errors return non-2xx JSON `{ error: string, code: string }`; no provider credentials or raw upstream body are returned.
- HTTP server factory accepts injected environment/fetch dependencies for isolated tests.

- [ ] Add failing tests that invoke the exported request handler with mocked request/response objects and a mocked provider for valid requests, missing key, malformed JSON, invalid fields, provider failure, and general strategy making only one provider call. The workspace sandbox blocks local socket binding.
- [ ] Run `node --test tests/server.test.mjs` and confirm the tests fail because routes are absent.
- [ ] Implement body-size and field validation (500-character prompt, 500-character caption, maximum 20 captions, numeric template ID).
- [ ] Implement routes using the Imgflip client; distinguish selected-template failure so the UI can offer explicit general generation.
- [ ] Run `node --test tests/server.test.mjs` and confirm route tests pass without external network requests.

## Task 4: Implement safe image download

**Files:** `server.mjs`, `tests/server.test.mjs`.

**Interface:** `GET /api/download?url=...` accepts only HTTPS URLs whose hostname is exactly `i.imgflip.com`, fetches with redirects disabled, and returns an image as an attachment with a safe generated filename.

- [ ] Add failing tests for valid image URL, HTTP URL, wrong host, malformed URL, redirect response, non-image upstream response, upstream failure, timeout, and body larger than 20 MiB.
- [ ] Run `node --test tests/server.test.mjs` and confirm these download tests fail.
- [ ] Implement URL validation, a 10-second timeout, redirect rejection, image content-type check, 20 MiB streaming cap, and safe response headers.
- [ ] Run download tests and confirm invalid URLs are never fetched and oversized bodies are stopped.

## Task 5: Build prompt, result, editor, retry, and download UI

**Files:** `public/index.html`, `public/app.js`, `public/styles.css`, `tests/ui.test.mjs`.

**Interface:** The page calls `POST /api/generate`, dynamically creates one editable caption control per returned text, calls `POST /api/caption` on explicit render, exposes “Try another”, offers a separate general-generation fallback when template matching fails, and downloads through `/api/download`.

- [ ] Add failing static/UI behavior tests for prompt validation, dynamic caption iteration, loading/error states, edit/render, explicit retry/fallback, and safe download URL construction.
- [ ] Run `node --test tests/ui.test.mjs` and confirm new behaviors fail before implementation.
- [ ] Implement an original, responsive editorial/zine-style interface with a prompt composer, result preview, caption editor, regeneration, fallback, and download.
- [ ] Disable actions while requests are pending and preserve the current result if an edit fails.
- [ ] Run UI tests and inspect the live page with REA at desktop and mobile widths without submitting a real generation request if local browser networking is permitted; otherwise record the sandbox limit and use the UI source tests.

## Task 6: Full verification and review

**Files:** all new app files.

- [ ] Run `npm test`, `npm run lint`, and `npm run build`.
- [ ] Do not make a real paid Imgflip generation request during automated tests. A user-triggered first generation is the live API smoke test; confirm success/failure without displaying the key.
- [ ] Have a fresh code reviewer inspect endpoint security, secret handling, input validation, and the plan's Review Focus list; resolve Critical/Important findings and rerun affected tests.

