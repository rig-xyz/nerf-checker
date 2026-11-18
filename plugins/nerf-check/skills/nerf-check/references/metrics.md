# What is measured, and what it can't tell you

## The unit

A **prompt** is one message the user typed in a main Claude Code thread, plus everything the model did until their
next message. Subagent threads, scheduled or scripted runs and SDK sessions are left out, and a turn that appears in
two transcripts because a session was forked is counted once. Each prompt keeps its model id, effort level, Claude
Code version and context size, so any trend can be split by them.

Only complete ISO weeks are reported. The current week is always missing; that is deliberate, since a partial week
has a different mix of work.

## The judged error share (the main signal)

For each prompt that has a next message, a judge model reads the end of the reply and the start of that next message
and labels it `error` (the user is correcting a mistake), `redirect` (new requirement or taste, no mistake),
`continue` or `new`. The error share is errors over judged prompts, with a 95% interval.

The interval resamples whole sessions rather than single prompts. Corrections come in runs: a session that goes badly
produces several, so prompts are not independent draws, and an interval that assumes they are (Wilson) comes out too
narrow, sometimes by half. The reported interval is the session-resampled one, and never narrower than Wilson, which
stays the floor when a week has too few sessions to resample.

It is a proxy. It counts the mistakes the user bothered to point out, so it moves with their patience and with how
hard the week's work was, not only with the model. This is why the comparison that matters is one week against the
range of the others, with intervals: overlapping intervals mean no detectable change.

Two things it misses by construction. The last prompt of a session has no next message, so it is never judged; a
session abandoned in frustration ends on exactly such a prompt. And the judge sees only 500 characters of the reply
and 300 of the answer.

## The judge is an instrument too

The judge is a model, and models change. Three guards:

- Every label records the judge model's id and a hash of the prompt it was given. `report.py` prints a `NOTE` when
  the latest week was read by a judge no earlier week used; treat that week as a new series.
- Each run has the judge label a sample of the new prompts twice, independently. `report.py` prints the running
  result: the share given the same label, and of the prompts either pass called an error, how many both did. The
  second number is the one to read, since most prompts are plainly not errors. Quote it rather than guessing at
  "judge noise".
- The prompt is one file, `assets/judge-prompt.txt`, and is passed as printed.

## Columns in the weekly CSVs

| Column | Meaning |
|---|---|
| `n`, `judged` | Prompts, and how many of them had a next message that was judged |
| `err`, `err_lo`, `err_hi` | Judged error share and its 95% interval, % |
| `redirect` | Share of judged prompts followed by a redirect, % |
| `interrupt` | Share of prompts the user interrupted, % |
| `apol`, `concede`, `shortcut`, `handback` | Keyword hits per 100 prompts: apologies; concessions ("you're right", "good catch"); shortcut phrases ("for brevity", "placeholder"); hand-backs ("you can run…") |
| `tool_err` | Tool calls that returned an error, % of tool calls |
| `edit_fail` | Edits that failed (text not found, file not read), % of edits |
| `read_edit` | File reads per file edit |
| `think_med`, `think_p75` | Thinking tokens per prompt, median and 75th percentile |
| `think_per_call` | Mean thinking tokens per API call |
| `zero_think` | Share of prompts with no thinking at all, % |
| `out_med`, `tools_med` | Median output tokens and tool calls per prompt |
| `ctx_med_k` | Median context already held when the prompt started, thousands of tokens |
| `compaction`, `api_err` | Share of prompts that hit a compaction, or an API error, % |
| `start_ctx_k` | Median context a fresh session holds before the first prompt (system prompt, tools, memory, skills), thousands of tokens |
| `reread` | File reads that covered lines already in the context window, with the file not edited since, % of file reads |
| `reread_compact` | File reads that covered lines read before a compaction, % of file reads |
| `verify` | Of the prompts where the model edited code, the share where it then ran a test, build, type check, linter or the code itself, % |
| `rejected` | Share of prompts where the user turned down a tool call, % |
| `fallback` | API calls answered by a different model than the one requested, % of calls that requested this model |
| `cache_hit` | Share of input tokens read from the prompt cache, % |
| `cc_version`, `cc_versions` | The Claude Code version most prompts ran on that week, and how many versions were used |
| `top_effort` | The effort level most prompts ran at |

The last nine were added in 0.3. They need fields that older stored prompts don't have, so weeks from before then are
blank until those transcripts are rescanned (`extract.py 400` picks up whatever is still on disk).

Thinking tokens come from the API usage record, so they are exact even when thinking text is hidden. That record is
part of Claude Code's transcript format, which is not documented and can change: `extract.py` prints a `WARNING` when
a Claude Code version stops writing the count, and when a tenth or more of a row's prompts lack it, those prompts are
left out of the thinking columns instead of being read as zero. Written against Claude Code 2.1.247 to 2.1.325.

Keyword counts are cheap and noisy, and English only; use them as a second opinion, never as the headline.

## Keeping track and checking the work

- **Re-reads** (`reread`, `reread_compact`). Reads are taken from the Read tool and from shell commands that print a
  file (`cat`, `nl`, `less`, `sed -n a,bp`, `head`), each as a file and a line range. A read counts as a re-read when at
  least 80% of its lines were already read in the same context window and the file was not edited in between. If
  they were only read before a compaction, it counts as `reread_compact` instead: the first is the model losing
  track, the second is what compaction costs. Logs, temp files and images are left out, since they change under the
  model. Files are matched on their last two path parts, so two `README.md` files reached by bare name can be
  confused, and reads through other commands (`grep`, `tail`, a script) are not seen.
- **Checked its work** (`verify`). An edit to a code file, followed later in the same prompt by a test, build, type
  check or lint command, a run of a script, a request to localhost, or a browser or simulator tool. Edits to docs
  alone are not counted. Add your own check commands with `verify` in the config. It says a check ran, not that it
  passed or that it was the right check.
- **Rejected tool calls** (`rejected`). Only calls the user turned down by hand. In an auto-approve mode this stays
  at zero and says nothing.

## What changed around the model

`cc_version`, `cc_versions`, `top_effort`, `fallback`, `cache_hit` and `start_ctx_k` describe the harness, not the
model. Past "nerfs" have turned out to be a client release, a lower default effort or a caching bug. When the error
share moves, look for a step in one of these in the same week before blaming the model. `fallback` compares the
model the client requested with the one that answered; it should be zero.

## Sessions moved to another model, or started over

`switches.csv` has one row per week: sessions that used the primary model, and how many were moved to a different
model partway through. A switch is the user's own verdict on how the session was going, and it catches what the
correction share misses, since frustration builds over a long session. `frustrated` counts switches where the first
message to the new model said the old one was confused, stuck, nerfed or similar (a keyword match, English only);
`compacted_before` those where the session had already been compacted; `ctx_at_switch_k` is the median context at the
switch. It counts every move off the primary model, including handing a small job to a cheaper one, so read `to`.

`restarts` counts sessions that were given up on without a word: a conversation of two prompts or more whose last
prompt was on the primary model, with a new session opened in the same folder within 15 minutes of it going quiet for
good. `retries` are the ones where the new session's first prompt asked for much the same thing (compared by shared
words, in memory, nothing stored). A new session opening with the very same words is taken for a template and not
counted. This is the only view of the last prompt of a session, which the judge never sees. It is a small tally and
it also catches someone simply moving to the next task, so don't turn it into a rate.

## Review signals

- **Pull requests by model.** A pull request belongs to the model whose `gh pr create` call opened it, even if another
  model pushed later commits; pull requests opened any other way are not seen. The review bot's inline comments are
  counted with the severity the bot gave, read from CodeRabbit's comment format (another bot's comments all count as
  "other"); replies and its summary comments are not. `ci_prs` and `ci_pass` are the pull requests whose first CI run
  finished, and those where it was all green: every check on the commit the pull request was opened with, each at its
  first attempt, the review bot's own check left out. It needs only `gh` and a repository with CI. A red first run
  counts whatever caused it, a flaky runner included, and a branch rebased since it was opened can't be read. Pull requests opened in the last three weeks are read again at each run, since
  comments keep arriving.
- **Recorded reviews.** Where a team has a command that records a pre-push review with a one-line verdict
  (`review_mark` in the config), each call is sorted by what the verdict says it surfaced: big (Critical, Major, High),
  small (Medium, Minor, Low, a nit, an unlabelled finding), clean, or recheck (a re-mark after a rebase, merge or fix
  round). This is read by pattern from a sentence the model wrote, so it is the model's own account of its review, and
  it only works well when verdicts name severities.

These are counts of small numbers. A model with five pull requests has no rate worth quoting.

## Reading a comparison between models

Two models in the same week did not get the same prompts. People try a new model on particular work, often at a
different effort level, and for fewer prompts. So the by-model view is a side-by-side, not an experiment: it can show
that nothing dramatic differs, and it can show differences in how the models work (thinking, output, tool calls), but
a gap in error share between two models needs many weeks, or matched tasks, before it means anything.

## What is kept

Numbers per prompt, keyed by session, start time and a hash of the prompt's first 200 characters. Never the prompt
text. The judge's two snippets are held until the prompt is labelled and then deleted, unless `keep_text` is set.
Pull-request URLs and recorded-review verdict lines are kept as text.

## What none of this sees

Changes in the work itself. A week of migrations is not a week of prototypes. Fixed-task trackers that rerun the same
benchmark on a schedule answer "did the model change"; this answers "did my experience change", which is closer to
what people feel and less controlled.
