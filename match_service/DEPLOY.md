# Deploying the match service to Modal (no laptop needed at request time)

One-time setup (you run these; they need your Modal account):

1. Install and log in:
   `pip install modal` then `modal setup`  (opens a browser to authenticate)
2. Store the shared key as a Modal secret **without printing it**:
   `modal secret create match-service MATCH_SERVICE_KEY="$(grep '^MATCH_SERVICE_KEY=' match_service/.env | cut -d= -f2-)"`
3. Deploy (first build downloads the 4.5 GB model into the image; allow ~10 min):
   `modal deploy match_service/modal_app.py`
4. Modal prints the HTTPS URL of the `web` endpoint. Put it in the web app's environment as
   `MATCH_SERVICE_URL` (and the same key as `MATCH_SERVICE_KEY`), e.g. in Vercel project settings, then redeploy.
5. Check it: `curl https://<that-url>/health`

Costs / behaviour
- Scales to zero. The first request after ~5 idle minutes waits for a cold start (reported 15-45 s;
  model load itself measured ~6 s locally). Later requests take a few seconds.
- To keep it warm during a demo: `MATCH_MIN_CONTAINERS=1 modal deploy match_service/modal_app.py`
  (billed while up; roughly a quarter of a dollar per hour at 2 cores / 4 GB, check Modal pricing).
- Refresh data after re-embedding: rebuild `match_service/data/` and redeploy.
- Stop it any time: `modal app stop match-service`.
