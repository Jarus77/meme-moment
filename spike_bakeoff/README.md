# THROWAWAY SPIKE: embedding bake-off for "photo -> meme template + caption"

Not production code, no tests. Purpose: find out which embedding setup puts the right meme
templates in the top 3 for a user's photo. Delete or rewrite once we know.

## Run (after the crawl + example-caption pass finish)

    cd <repo root>
    spike_bakeoff/.venv/bin/python spike_bakeoff/build_index.py --n 100
    # put photos in spike_bakeoff/photos/, optionally label them in spike_bakeoff/photos/labels.csv
    spike_bakeoff/.venv/bin/python spike_bakeoff/evaluate.py

`labels.csv` (optional): `photo,acceptable_slugs` e.g. `three_doors.jpg,Three-Doors|Monty-Hall`
(slugs separated by `|`; any one counts as a hit). Without labels you just get each photo's top 3.

## What is compared
Models: SigLIP 2 (so400m) and Jina CLIP v2, both local. (No paid embedding API: no key available.)
Retrieval modes per model:
- A  photo  -> template pictures
- B  photo  -> example caption text (best caption per template)
- C  A + B fused
- D  Claude's one-line description of the photo -> example caption text
- E  Claude's description -> template pictures
