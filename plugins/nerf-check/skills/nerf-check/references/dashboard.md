# The dashboard

The dashboard is a hosted Claude artifact of the Dashboard type: a page plus a small store of datasets. The page is
this skill's `assets/dashboard.html`. The datasets are the eight CSVs from `report.py`, attached as files. Because the
CSVs hold only weekly aggregates, the dashboard is safe to share; still, everyone who can open it can read those files,
so tell the user that when you create it.

The Dashboard type ships its own instructions and they change over time. When you create or read the dashboard, the
tool returns them: follow them for the mechanics (tool names, field names, how to check the page ran). This file says
what to put where.

## Dataset ids

`assets/datasets.json` has one entry per dataset: its id, title, description and CSV file name.

| Dataset id | CSV |
|---|---|
| `weekly` | `weekly.csv` |
| `weekly_effort` | `weekly_by_effort.csv` |
| `context` | `by_context.csv` |
| `error_types` | `error_types.csv` |
| `weekly_model` | `weekly_by_model.csv` |
| `prs` | `prs_by_model.csv` |
| `reviews` | `reviews_by_model.csv` |
| `switches` | `switches.csv` |

The page reads datasets by these ids, so they are fixed.

## Creating it (first run)

1. Start a Dashboard artifact with the Artifact tool (its quickstart for a dashboard names the type to create from).
   Title: "Claude Code nerf check", or what the user prefers.
2. Copy the eight CSVs from `<home>/csv` into the session's scratch folder and upload each to the new artifact as an
   asset. Each upload returns a `/_blob/<id>` url.
3. In one batch write to the store:
   - the dashboard's title document;
   - one `datasets/<id>` document per entry in `assets/datasets.json`, adding to each: `source.url` (its blob url),
     `fixed: true` (these are deliberate file snapshots, not a candidate for a live query),
     `schedule: "Rebuilt weekly from local Claude Code transcripts"`, `staleAfterHours: 336`,
     `updated: {at: <now UTC>, by: "Claude, from local transcripts"}` and `edit: {via: "claude", at: <now UTC>}`;
   - the page: `files/index.html` with `{text: <contents of assets/dashboard.html>, edit: {...}}`. Send it from a
     local JSON file rather than retyping it.
4. Read back how the page ran, as the type's instructions describe, and fix what it reports. If nothing has judged
   the page because nobody has it open, say so instead of claiming it works.
5. Save the artifact's url as `dashboard_url` in `<home>/config.json`, and give the user the link.

Publishing is private by default. Sharing it with a team is the user's call.

## Refreshing it (every later run)

Only the data changes. The user may have edited the page's words by hand, so leave `files/index.html` alone.

1. Read the eight `datasets/<id>` documents and note each one's version and current `source.url`.
2. Upload the eight new CSVs as assets.
3. In one batch, update each dataset with its new `source.url`, `updated: {at, by}` and `edit: {via, at}`, pinning the
   version you read. If a dataset is missing (the dashboard predates it), create it as in "Creating it".
4. Delete the assets the datasets pointed at before. Only those: other assets are not this skill's to remove.

## When the page itself changed

A skill update can bring a new `assets/dashboard.html` (a new chart, a new column). An existing dashboard keeps its
old page until someone replaces it, and the old page keeps working because columns are only ever added. Replace the
page only when the user asks for the new version: read the stored page first, and if it differs from the previous
template in more than the template changes (the user reworded something), carry their edits over rather than
overwriting them.

## No hosted dashboard

Where the Artifact tool or the Dashboard type isn't available (another agent, an account without it), run
`python3 scripts/preview.py`. It writes `<home>/preview.html`, the same page drawn from the same CSVs, to open in a
browser. It is a local file, refreshed by running the script again.
