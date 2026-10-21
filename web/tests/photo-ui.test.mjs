import assert from "node:assert/strict";
import test from "node:test";
import { createPhotoMemeActions, resizePhotoFile, wrapCaptionText } from "../public/photo-meme.mjs";

test("photo upload is downscaled to a maximum 1280-pixel edge and encoded as JPEG", async () => {
  let dimensions;
  const photo = await resizePhotoFile({ type: "image/png" }, {
    createImageBitmapImpl: async () => ({ width: 2560, height: 1920, close() {} }),
    canvasFactory: (width, height) => {
      dimensions = { width, height };
      return {
        getContext: () => ({ drawImage() {} }),
        toBlob: (callback, mime) => callback(new Blob(["jpeg"], { type: mime })),
      };
    },
  });
  assert.deepEqual(dimensions, { width: 1280, height: 960 });
  assert.match(photo.dataUrl, /^data:image\/jpeg;base64,/);
});

test("photo upload rejects files the browser does not identify as images", async () => {
  await assert.rejects(resizePhotoFile({ type: "text/plain" }), /Choose an image/);
});

test("caption wrapping produces no more than two lines per block", () => {
  const lines = wrapCaptionText("one two three four five six seven", (text) => text.length * 10, 70);
  assert.ok(lines.length <= 2);
  assert.equal(lines[0], "one two");
});

test("photo action returns three locally rendered caption options and lets the tester switch", async () => {
  const requests = [];
  const rendered = [];
  const actions = createPhotoMemeActions({
    resizeImpl: async () => ({ dataUrl: "data:image/jpeg;base64,/9j/2Q==", width: 300, height: 200 }),
    renderImpl: async (photo, texts) => {
      rendered.push({ photo, texts });
      return new Blob([texts.join(" ")], { type: "image/png" });
    },
    createUrl: (_blob, index) => `blob:option-${index}`,
    fetchImpl: async (url, init) => {
      requests.push({ url, body: JSON.parse(init.body) });
      return new Response(JSON.stringify({
        description: "A person smiles while reading.",
        selectedMatch: { template: { asset_id: 42, box_count: 1, name: "Reader", source_url: "https://imgflip.com/meme/42/reader", image_url: "https://i.imgflip.com/reader.jpg" } },
        matches: [],
        options: [{ texts: ["First"] }, { texts: ["Second"] }, { texts: ["Third"] }],
      }));
    },
  });

  const result = await actions.generate({ type: "image/jpeg" });
  assert.equal(result.ok, true);
  assert.equal(requests[0].url, "/api/photo-meme");
  assert.match(requests[0].body.photo, /^data:image\/jpeg/);
  assert.equal(rendered.length, 3);
  assert.ok(rendered.every(({ photo }) => photo === requests[0].body.photo));
  assert.equal(actions.getState().imageUrl, "blob:option-0");
  assert.equal(actions.selectOption(2), true);
  assert.equal(actions.getState().imageUrl, "blob:option-2");
});
