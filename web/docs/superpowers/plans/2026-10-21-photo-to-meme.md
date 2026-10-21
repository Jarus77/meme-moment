# Photo-to-meme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a photo-to-meme flow that returns three captions for a Gemini-selected matched template and renders the user's photo as a downloadable PNG in the browser.

**Architecture:** Add a photo pipeline module with injected Gemini and match-service fetches; expose it through the existing API handler. Validate a bounded JPEG data URL, create scene description and captions with server-side Gemini, retrieve/sanitize matches, and return evidence plus options. Resize and render in browser-native canvas; keep all photo data in memory.

**Tech Stack:** Node.js 22 built-ins, existing Gemini REST pattern, browser Canvas, `node:test`.

**Spec:** `docs/superpowers/specs/2026-10-21-photo-to-meme-design.md`

## Global Constraints

- Do not read or modify `.env`; never log credentials or image bytes.
- Tests must use fake Gemini and match-service responses only.
- Do not store photos, deploy, or commit.
- Keep the text-prompt flow functional and use only native dependencies.
- Gemini and match-service credentials are server-only.
- Match service receives only the photo description, never the photo.
- Reject invalid/non-JPEG photos and decoded uploads larger than 5 MiB; downscale browser uploads to 1280 px.

## Review Focus

- Invalid data URLs, JPEG signatures/dimensions, and oversize decoded bytes are rejected before external calls.
- Match/Gemini timeouts return friendly errors and do not leak upstream content.
- Malformed match results (unsafe links, unsafe templates, invalid box counts) cannot reach the UI or Gemini selection.
- Caption JSON has exactly three options, each with exactly the selected template's box count, and no verbatim community caption reuse.

---

## File Map

- `lib/photo-meme.mjs`: JPEG validation, fakeable match client, Gemini description/caption flow, result validation.
- `server.mjs`: `POST /api/photo-meme` route with bounded body.
- `lib/validation.mjs`: allow bounded JSON size override and validate photo request input.
- `public/index.html`: demo gate, photo upload/control, 4-line explanation, result evidence/options.
- `public/photo-meme.mjs`: browser resize, API action, local canvas rendering/export.
- `public/styles.css`: style upload form, gate and evidence in the existing visual language.
- `.env.example`, `DEPLOYING.md`: document `MATCH_SERVICE_URL`, `MATCH_SERVICE_KEY`.
- `tests/photo-meme.test.mjs`, `tests/server.test.mjs`, `tests/ui.test.mjs`: test-first contract, validation, routes, and UI.
- `docs/HANDOFF-from-codex.md`: status and any service-contract questions.

## Task 1: Validate uploaded JPEG and integrate pipeline

**Interfaces:** Export `validatePhotoRequest(body)`; export `createPhotoMemeService({ geminiApiKey, model, matchServiceUrl, matchServiceKey, fetchImpl, describePhoto, draftCaptions })` returning `generate(photo)`.

- [x] Add unit tests for valid JPEG bounds, malformed/non-image/oversize inputs, valid match selection/captions, exact three outputs, and rejection of verbatim example-caption reuse.
- [x] Run `node --test tests/photo-meme.test.mjs` and verify expected failures.
- [x] Implement the smallest production API that passes, with strict URL/schema validation, injected fetch, and no real API calls.
- [x] Run the focused tests.

## Task 2: Add gated HTTP route and integration tests

**Files:** `server.mjs`, `lib/validation.mjs`, `tests/server.test.mjs`.

- [x] Add tests for open `/api/photo-meme`, valid fake pipeline flow, invalid JPEG before upstream calls, friendly match timeout/down errors, and existing text route compatibility.
- [x] Run the focused server tests and verify expected failures.
- [x] Add bounded photo body parsing and the photo-meme pipeline route; inject fakeable service dependencies.
- [x] Run the focused server tests.

## Task 3: Add photo upload, option rendering, evidence UI and setup docs

- [x] Add failing UI tests for the upload flow, privacy/process copy, evidence and author attribution, 3 selectable options, photo downscaling/render bounds, and docs/env names.
- [x] Run focused UI tests and verify expected failures.
- [x] Add the protected workflow in the existing style. Resize the selected image client-side to a maximum 1280-pixel edge JPEG; render 1, 2, or 3+ text blocks onto that photo in Canvas, maximum two lines per block; expose three PNG downloads/options and safe source/author links.
- [x] Update `.env.example` and `DEPLOYING.md` without reading or editing `.env`.
- [x] Run focused UI tests.

## Task 4: Verify and hand off

- [x] Run `npm test`, `npm run lint`, and `npm run build`.
- [x] Review changes for privacy, unsafe HTML/link rendering, unbounded memory/time, and accidental text-flow regressions.
- [x] Write completed status, test results, and any needed contract clarification to `docs/HANDOFF-from-codex.md`.
