"""Shared paths and settings for the nerf-check scripts.

Everything a run keeps lives in one folder outside the skill, so the history survives skill updates and Claude Code's
transcript cleanup: $NERF_CHECK_HOME, or <Claude config dir>/nerf-check when unset (~/.claude unless
$CLAUDE_CONFIG_DIR says otherwise).
  data/         turns.json, labels.json, sessions.json, prs.json, reviews.json, agreement.json, judge/
  csv/          what report.py writes
  config.json   optional; every key is optional (see DEFAULTS)

What is kept per prompt is numbers, not text: the prompt itself is never stored, and the two snippets the judge reads
(the end of the reply, the start of the next message) are dropped as soon as the prompt has a label. See slim().
"""
import json, os, re

CLAUDE = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude')
HOME = os.path.expanduser(os.environ.get('NERF_CHECK_HOME') or os.path.join(CLAUDE, 'nerf-check'))
DATA = os.path.join(HOME, 'data')
CSV = os.path.join(HOME, 'csv')
TRANSCRIPTS = os.path.expanduser(os.environ.get('NERF_CHECK_TRANSCRIPTS') or os.path.join(CLAUDE, 'projects'))

DEFAULTS = {
    # Model id the headline, weekly chart, context chart and effort chart follow. null: the model with the most prompts.
    'primary_model': None,
    # Display names by model id, e.g. {"claude-opus-5-5": "Opus 5.5"}. Ids not listed get a name derived from the id.
    'model_labels': {},
    # First ISO week to report, e.g. "2026-W41". null: the first week with data.
    'first_week': None,
    # A model shows in the by-model comparison for a week only with at least this many prompts that week.
    'min_prompts': 20,
    # Session entrypoints counted for "fresh session overhead", e.g. ["claude-desktop"] or ["cli"]. null: all.
    'entrypoints': None,
    # Regex for prompts no person typed, searched in the first 2000 characters, on top of the built-in scheduled-task
    # markers. Use it for your own scripted runs, e.g. "^<nightly-run>".
    'automated': None,
    # Regex for shell commands that count as checking the work after an edit, on top of the built-in test, build, lint
    # and run commands. E.g. "\\./scripts/check\\.sh|just test".
    'verify': None,
    # Read the first CI run of each pull request a model opened (needs `gh`). false: skip it.
    'ci': True,
    # GitHub login whose inline PR comments are counted. Severities are read from CodeRabbit's comment format; another
    # bot's comments are still counted, all as "other".
    'review_bot': 'coderabbitai[bot]',
    # Regex for a shell command that records a pre-push review with a quoted one-line verdict as its last argument,
    # e.g. "record-review\\.sh". null: no recorded-review signal.
    'review_mark': None,
    # Regex for verdicts that are a re-mark (after a rebase, a merge, a fix round) rather than a fresh review, on top of
    # the built-in ones. null: built-in only.
    'review_recheck': None,
    # Keep the judge's two text snippets after a prompt is labelled, so old weeks can be re-judged later. Off by default:
    # the snippets are your words and the model's, and nothing else needs them.
    'keep_text': False,
    # Where the dashboard lives once it has been created; the weekly refresh reads it from here.
    'dashboard_url': None,
}


def config():
    cfg = dict(DEFAULTS)
    p = os.path.join(HOME, 'config.json')
    if os.path.exists(p):
        cfg.update(json.load(open(p)))
    return cfg


def load(name):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else {}


def save(name, obj, **kw):
    """Write through a temp file: these stores outlive the transcripts they came from, so a crash mid-write must not
    leave a half-written file as the only copy."""
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    with open(p + '.tmp', 'w') as f:
        json.dump(obj, f, **kw)
    os.replace(p + '.tmp', p)


def label(model_id, cfg):
    """claude-opus-5-5 -> Opus 5.5, claude-sonnet-4-5-20250929 -> Sonnet 4.5; anything else is shown as it is."""
    if model_id in cfg['model_labels']:
        return cfg['model_labels'][model_id]
    m = re.match(r'claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(?:\[.*\])?$', model_id or '')
    if not m:
        return model_id or 'unknown'
    return f"{m.group(1).capitalize()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else '')


def counted(turn):
    """A prompt a person typed in a normal session: not a scheduled or scripted run, not an SDK session."""
    return not turn.get('automated') and not str(turn.get('entrypoint') or '').startswith('sdk-') and bool(turn.get('model'))


def in_subagent(path):
    return 'subagents' in path.split(os.sep)


# The first message to a new model after a mid-session switch, saying the old one was not coping. English only.
FRUSTRATED = re.compile(r"nerf|confus|not happy|frustrat|struggl|stuck|lost the|keeps? (breaking|forgetting|getting)|isn'?t getting|doesn'?t get", re.I)
# Fields older versions stored and nothing reads. Dropped on the next save.
RETIRED = ('prompt', 'project', 'bash', 'blind_edits', 'think_ms', 'ctx_max', 'text_chars', 'denied', 'next_correction',
           'end', 'stop_reasons', 'dur_s', 'day', 'models', 'efforts', 'versions')


def slim(turn, labelled, keep_text=False):
    """Reduce a stored turn to what the report needs. The prompt text goes (after the one flag that needs it is taken);
    the judge's two snippets stay only while the prompt is still waiting for a label."""
    if 'frustrated' not in turn:
        turn['frustrated'] = bool(FRUSTRATED.search((turn.get('prompt') or '')[:600]))
    for k in RETIRED:
        turn.pop(k, None)
    waiting = counted(turn) and turn.get('next_prompt') and not labelled
    if not waiting and not keep_text:
        turn.pop('last_text', None)
        if turn.pop('next_prompt', None):
            turn['has_next'] = True
    return turn
