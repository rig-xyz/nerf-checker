---
name: nerf-card
description: >-
  Turn the latest nerf-check result into one shareable picture: a big verdict (NERFED, SUS, NOT NERFED, BUFFED or
  TOO EARLY) with its badge, the week-by-week chart, and four numbers from the user's own Claude Code work (including how often
  the model said "you're right"). Optionally
  opens a draft post with the picture ready to paste. Use when the user wants to share, post, tweet or show off their
  nerf check, asks for a nerf card, a verdict image, a screenshot-able summary, or "is it nerfed, yes or no?" as a
  picture, even if they don't say "card". Needs the nerf-check skill to have run first.
---

# Nerf card

One picture that answers "is it nerfed?" for the latest complete week, made to be posted. It is drawn from the weekly
numbers the nerf-check skill already wrote, so it shows aggregates only: no prompts, no file names, no project names.
The model's name and the user's own percentages are on it, and that is all.

## Where things live

- Reads `<home>/csv/weekly.csv`, where `<home>` is nerf-check's folder: `$NERF_CHECK_HOME`, or `~/.claude/nerf-check`.
- Writes `<home>/cards/nerf-card-<model>-<week>.html` (one self-contained file) and the same card as a PNG,
  2400x1350, which is the 16:9 shape X, LinkedIn, Bluesky and Slack all show uncropped.

## Make the card

1. If `<home>/csv/weekly.csv` is missing, or the script prints a NOTE that the latest week on file is old, run the
   nerf-check skill first. If that skill is not installed, say so: this one only draws what nerf-check measured.
2. Run `python3 scripts/card.py`. For another model that has its own weeks, add `--model "<name as the dashboard shows it>"`.
   It prints JSON: the verdict, the numbers behind it, the two file paths and a draft post.
3. Look at the PNG yourself before showing it (read the image). If a NOTE says there is no PNG, no Chrome-family
   browser was found: take a 1200x675 screenshot of the HTML with whatever browser tool this session has, or give the
   user the HTML to open and screenshot.
4. Show the user the picture, and say the verdict in one line with the numbers behind it.

## What the verdict means

It compares the latest complete week's error share (prompts whose next message had to correct the model) with the
earlier weeks, the same reading the nerf-check summary gives:

| Verdict | When |
|---|---|
| NERFED | The whole 95% interval sits above the highest earlier week. |
| SUS | The share is above the highest earlier week, but the interval reaches back into the earlier range. |
| BUFFED | The whole 95% interval sits below the lowest earlier week. |
| NOT NERFED | Anything else. |
| TOO EARLY | Fewer than 3 earlier weeks to compare with, or fewer than 100 judged prompts in the latest week. |

The card says what the numbers support and no more. Keep it that way when you talk about it:

- It is one person's work, not a benchmark. The card says so in its footer; do not drop that line or reword the
  verdict into a claim about the model in general.
- A NERFED or SUS week often has a cause outside the model. When Claude Code's version or the effort level changed
  that week, the card says so under the verdict. Mention it before the user posts.
- The last tile counts how often the model said "you're right" that week, and how often it said sorry. Those are
  keyword counts (nerf-check's `concede` and `apol` columns: "you're right", "good catch", "I was wrong" and the like),
  there for fun. They are noisy and play no part in the verdict.
- Never change the verdict, the numbers or the thresholds to get a better picture. If the user wants a different
  week or model, draw that one.

## Posting it

Only when the user asks to post or share it. Never in a scheduled or unattended run.

1. Show the draft text from the JSON (`post_text`) and let the user change it. Keep the credit line: nerf-check is by
   Rig Labs (https://riglabs.ai/).
2. On their go-ahead, run `python3 scripts/card.py --share x` (or `bluesky`, `linkedin`, `threads`), with
   `--text "<their wording>"` if they changed it. That copies the PNG to the clipboard and opens a draft post in
   their browser with the text filled in. They paste the picture and press Post themselves: the script posts nothing
   and needs no account access. `--dry-run` prints the draft's address without copying or opening anything.
3. If `copied` comes back false, tell them where the PNG is so they can attach it by hand.

If this session has its own way to post somewhere the user names (a Slack or other connector), you may use it
instead, with the PNG attached, but only after they have seen the exact text and said yes to that destination.
