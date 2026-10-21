import { createFetchHandler } from "../server.mjs";

const handler = createFetchHandler();

export default {
  fetch(request) {
    return handler(request);
  },
};
