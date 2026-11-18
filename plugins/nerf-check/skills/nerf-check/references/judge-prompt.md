# Judge prompt

One subagent per batch file that `judge.py pending` lists, on the cheapest capable model (Haiku), all in parallel.
That includes `judge_in_repeat.jsonl` when it is there: it is judged like any other batch, by its own subagent, and
`merge` uses it to measure how often the judge agrees with itself.

Give each subagent exactly what this prints, nothing added and nothing reworded:

    python3 scripts/judge.py prompt <path to the batch file>

The prompt text lives in `assets/judge-prompt.txt`. Verbatim matters: the error share is only comparable from week to
week if every week was judged by the same instructions and the same model. So each label records both, a hash of the
prompt file and the model id passed to `merge`, and `report.py` prints a note when the latest week's judge differs
from the earlier weeks'. Changing the prompt file, or moving to another judge model, starts a new series: tell the
user before doing either.

After the subagents finish, check each output file before merging: the same number of lines as its input and the same
set of ids. Then:

    python3 scripts/judge.py merge <judge-model-id>

with the id of the model the subagents ran on (for example `claude-haiku-5-5`). `merge` ignores ids it did not ask for
and reports how many are still unlabelled; rerun the judge on a batch that came back short rather than labelling the
gap yourself. Once nothing is missing it deletes the batch files and the stored snippets of every labelled prompt.

Without subagents, label the batches yourself with the same rules and pass your own model id to `merge`. It costs more
context, and the labels are then a different judge's: the report will say so.
