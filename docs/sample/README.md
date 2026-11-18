# Sample data

Made-up numbers, not measurements of any model. They exist so the dashboard can be seen without running the skill,
and they are what the screenshots in the main README show. The story they tell: one week looks like a nerf, and the
"What changed around the model" table shows a client release that week lowered the effort level and doubled the
context a fresh session starts with.

    NERF_CHECK_HOME=docs/sample python3 skills/nerf-check/scripts/preview.py   # writes docs/sample/preview.html
    python3 docs/sample/make_sample.py docs/sample/csv                          # regenerates the CSVs
