"""End-to-end test on made-up transcripts: extract, judge bookkeeping, report. No packages, no network.

    python3 tests/test_pipeline.py

It writes a few fake sessions into a temp folder, runs the scripts against them the way the skill does, plays the
judge itself, and checks the numbers and what is left on disk.
"""
import csv, datetime as dt, json, os, subprocess, sys, tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'plugins', 'nerf-check', 'skills', 'nerf-check', 'scripts')
TMP = tempfile.mkdtemp(prefix='nerf-check-test-')
ENV = dict(os.environ, NERF_CHECK_HOME=os.path.join(TMP, 'home'), NERF_CHECK_TRANSCRIPTS=os.path.join(TMP, 'projects'))
ENV.pop('CLAUDE_CONFIG_DIR', None)
HOME = ENV['NERF_CHECK_HOME']
SECRET_PROMPT, SECRET_REPLY, SECRET_NEXT = 'PROMPT-TEXT-MUST-NOT-BE-STORED', 'REPLY-TAIL-MUST-GO', 'NEXT-TEXT-MUST-GO'


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args], env=ENV, capture_output=True, text=True)
    assert r.returncode == 0, f'{script} {args} failed:\n{r.stderr}'
    return r.stdout


def data(name):
    return json.load(open(os.path.join(HOME, 'data', name)))


def rows(name):
    return list(csv.DictReader(open(os.path.join(HOME, 'csv', name))))


def dump(o):
    return json.dumps(o, separators=(',', ':'))   # Claude Code writes compact JSON, and the scripts pre-filter on it


def bash(cmd):
    return dict(type='tool_use', id='t', name='Bash', input=dict(command=cmd))


def session(sid, start, prompts, cwd='/tmp/project'):
    """prompts: (text, model) or (text, model, steps), two minutes apart. Each gets one API call and a short reply.
    A step is a tool call the model makes, or 'compact' / 'reject' for a compaction or a tool call the user turned down."""
    out = []
    for i, (text, model, *steps) in enumerate(prompts):
        at = (start + dt.timedelta(minutes=2 * i)).isoformat().replace('+00:00', 'Z')
        at2 = (start + dt.timedelta(minutes=2 * i + 1)).isoformat().replace('+00:00', 'Z')
        base = dict(sessionId=sid, entrypoint='cli', version='2.1.325', cwd=cwd)
        tools = [s for s in (steps[0] if steps else []) if isinstance(s, dict)]
        out.append(dump(dict(base, type='user', timestamp=at, turnOrigin='human', message=dict(content=text))))
        if 'compact' in (steps[0] if steps else []):   # the compaction comes before the model's tool calls
            out.append(dump(dict(base, type='system', subtype='compact_boundary', timestamp=at)))
        out.append(dump(dict(base, type='assistant', timestamp=at2, effort='high', requestedModel=model, message=dict(
            id=f'{sid}-{i}', model=model, content=[dict(type='text', text=f'Done with step {i}. {SECRET_REPLY}')] + tools,
            usage=dict(input_tokens=1000 + 100 * i, cache_read_input_tokens=40000, cache_creation_input_tokens=0,
                       output_tokens=200, output_tokens_details=dict(thinking_tokens=50 * (i % 3)))))))
        for s in (steps[0] if steps else []):
            if s == 'reject':
                out.append(dump(dict(base, type='user', timestamp=at2, toolDenialKind='user-rejected',
                                     message=dict(content=[dict(type='tool_result', tool_use_id='t', content='no')]))))
    return '\n'.join(out) + '\n'


# Two complete ISO weeks before this one. Week A: two sessions on Opus. Week B: one session that moves to Fable.
monday = dt.datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
monday -= dt.timedelta(days=monday.weekday())
week_a, week_b = (monday - dt.timedelta(days=14)).astimezone(dt.timezone.utc), (monday - dt.timedelta(days=7)).astimezone(dt.timezone.utc)
OPUS, FABLE = 'claude-opus-5-5', 'claude-fable-5-2'
# The judge may hold the first 300 characters of a message until it is labelled; nothing may hold what comes after.
tail = ' ' + 'x' * 300 + SECRET_PROMPT
good = lambda i: (f'please do step {i}. {SECRET_NEXT}' + tail, OPUS)
bad = lambda i: (f'no, that is wrong, step {i} again. {SECRET_NEXT}' + tail, OPUS)
# Week A, session a1, with the probes exercised in its first prompts:
#   0  reads lines 1-80 of app.py, then 10-60 again (a re-read), edits it, runs the tests (checked its work)
#   1  reads 10-60 once more: fair, the file was edited since
#   2  a compaction, then 10-60 again: read before the compaction
#   3  edits code and stops without running anything; the user rejects a tool call
probe = [
    good(0) + ([bash('sed -n 1,80p src/app.py'), bash('cd /tmp/project && cat src/app.py | sed -n 10,60p'),
                dict(type='tool_use', id='t', name='Edit', input=dict(file_path='/tmp/project/src/app.py')), bash('pytest -q')],),
    good(1) + ([bash('sed -n 10,60p src/app.py')],),
    good(2) + (['compact', bash('sed -n 10,60p src/app.py')],),
    good(3) + ([dict(type='tool_use', id='t', name='Write', input=dict(file_path='/tmp/project/src/new.py')), 'reject'],),
]
ASK = 'migrate the billing tables to the new schema and keep every invoice total stable across the cutover. '
sessions = {
    'a1': (week_a, probe + [good(i) for i in range(4, 15)]),                        # 14 judged, 0 errors
    'a2': (week_a + dt.timedelta(days=1), [good(0)] + [bad(i) for i in range(1, 11)]),  # 10 judged, all errors
    'b1': (week_b, [(ASK + SECRET_NEXT + tail, OPUS)] + [good(i) for i in range(1, 12)] + [('opus keeps getting confused, take over', FABLE), ('thanks', FABLE)]),
    'auto': (week_b, [('<scheduled-task name="x">run the weekly thing</scheduled-task>', OPUS)]),
    # b1 goes quiet after 28 minutes; five minutes later a new session in the same folder asks for the same thing.
    'b2': (week_b + dt.timedelta(minutes=33), [('Start again: ' + ASK + 'Go slower this time.', OPUS)]),
}
os.makedirs(os.path.join(ENV['NERF_CHECK_TRANSCRIPTS'], 'proj'))
for sid, (start, prompts) in sessions.items():
    open(os.path.join(ENV['NERF_CHECK_TRANSCRIPTS'], 'proj', sid + '.jsonl'), 'w').write(session(sid, start, prompts))

# An empty home must not crash anything.
assert '0 turns need labels' in run('judge.py', 'pending')
run('report.py')

# Extract: every prompt becomes a turn, and no prompt text reaches the store.
out = run('extract.py', '60')
assert '42 new turns' in out and 'WARNING' not in out, out
stored = open(os.path.join(HOME, 'data', 'turns.json')).read()
assert SECRET_PROMPT not in stored, 'prompt text was stored'
turns = data('turns.json')
assert all('prompt' not in t and 'project' not in t for t in turns.values())
assert sum(t['automated'] for t in turns.values()) == 1

# Judge queue: one batch plus a repeat sample; the prompt command fills in both paths.
out = run('judge.py', 'pending')
assert '37 turns need labels' in out, out   # 14 + 10 + 13: the last prompt of each session has no next message
batch, repeat = os.path.join(HOME, 'data', 'judge', 'judge_in_0.jsonl'), os.path.join(HOME, 'data', 'judge', 'judge_in_repeat.jsonl')
assert os.path.exists(repeat)
p = run('judge.py', 'prompt', batch)
assert batch in p and batch.replace('judge_in_', 'judge_out_') in p and '{in}' not in p and '{out}' not in p

# Play the judge: an error wherever the next message starts with "no,". The repeat pass disagrees on one prompt.
def judge(path, flip=None):
    with open(path.replace('judge_in_', 'judge_out_'), 'w') as f:
        for line in open(path):
            it = json.loads(line)
            err = it['user_next'].startswith('no,') != (it['id'] == flip)
            f.write(json.dumps(dict(id=it['id'], label='error' if err else 'continue', error_type='misunderstood' if err else None)) + '\n')

judge(batch)
judge(repeat, flip=json.loads(open(repeat).readline())['id'])
out = run('judge.py', 'merge', 'test-judge-1')
assert 'merged 37 labels by test-judge-1' in out and '0 pending turns still unlabelled' in out, out
assert 'judged twice: 10 prompts, same label on 9' in out, out
labels = data('labels.json')
assert all(v['by'] == 'test-judge-1' and len(v['prompt']) == 8 for v in labels.values())

# Once labelled, the judge's snippets and batch files are gone.
stored = open(os.path.join(HOME, 'data', 'turns.json')).read()
assert SECRET_NEXT not in stored and SECRET_REPLY not in stored, 'judge snippets kept after labelling'
assert not os.listdir(os.path.join(HOME, 'data', 'judge'))

# Report: shares, intervals, the switch.
out = run('report.py')
assert 'Judge consistency, from 10 prompts judged twice' in out and 'NOTE' not in out, out
weekly = rows('weekly.csv')
assert [r['model'] for r in weekly] == ['Opus 5.5', 'Opus 5.5']
a, b = weekly
assert (a['n'], a['judged'], a['err']) == ('26', '24', '41.7'), a   # 10 errors of 24, all in one of two sessions
assert float(a['err_lo']) <= 41.7 <= float(a['err_hi'])
# Two sessions, one all errors and one none: resampling sessions must reach far beyond what 24 independent prompts give.
assert float(a['err_lo']) == 0.0 and float(a['err_hi']) > 62, a
assert (b['n'], b['err']) == ('13', '0.0'), b
# Probes, week A: 4 file reads, one of lines already in context and one of lines read before the compaction; code was
# edited in two prompts and checked in one; one prompt had a rejected tool call; nothing was served by another model.
assert (a['reread'], a['reread_compact'], a['verify']) == ('25.0', '25.0', '50.0'), a
assert (a['rejected'], a['fallback'], a['cc_version'], a['cc_versions'], a['top_effort']) == ('3.8', '0.0', '2.1.325', '1', 'high'), a
assert 95 < float(a['cache_hit']) < 100, a
sw = rows('switches.csv')
assert [(r['sessions'], r['switches'], r['to'], r['frustrated']) for r in sw] == [('2', '0', '', '0'), ('2', '1', 'Fable 5.2', '1')], sw
# b1 ended on Fable, so its restart is not the primary model's; a1 and a2 overlap and neither was started over.
assert [(r['restarts'], r['retries']) for r in sw] == [('0', '0'), ('0', '0')], sw
ss = data('sessions.json')
assert (ss['b1']['restarted'], ss['b1']['retried']) == (True, True) and not ss['a1']['restarted'] and not ss['b2']['restarted'], ss
assert len(rows('weekly_by_model.csv')) == 1   # only week A's Opus row passes min_prompts (20)

# A rescan adds nothing and does not bring the text back.
assert '0 new turns' in run('extract.py', '60')
stored = open(os.path.join(HOME, 'data', 'turns.json')).read()
assert SECRET_NEXT not in stored and SECRET_PROMPT not in stored
assert data('labels.json') == labels

# A new judge on a later week is called out. Relabel week B as if another model had judged it.
for k, t in data('turns.json').items():
    if k in labels and t['session'] == 'b1':
        labels[k]['by'] = 'test-judge-2'
json.dump(labels, open(os.path.join(HOME, 'data', 'labels.json'), 'w'))
assert 'NOTE: the latest week was judged by test-judge-2' in run('report.py')

# The preview page builds from the CSVs.
assert os.path.exists(run('preview.py').strip())

# Pure helpers.
sys.path.insert(0, SCRIPTS)
os.environ.update(NERF_CHECK_HOME=HOME)
import common, probes, reviews
assert probes.shell_reads("head -n 30 one.py; sed -n '5,9p' \"x/y.ts\"") == [('x/y.ts', 5, 9), ('one.py', 1, 30)]
assert probes.shell_reads('cat a.py') == [('a.py', 1, probes.END)] and probes.shell_reads('git diff | head -40') == []
assert not probes.same_ask(probes.words('one two'), probes.words('one two'))
assert common.label('claude-sonnet-4-5-20250929', common.DEFAULTS) == 'Sonnet 4.5'
assert common.label('some-other-model', common.DEFAULTS) == 'some-other-model'
assert reviews.outcome('T2: 1 Major, 2 Minor fixed') == 'big'
assert reviews.outcome('no Critical or Major; one Minor nit') == 'small'
assert reviews.outcome('clean, no findings') == 'clean'
assert reviews.outcome('re-review after rebase, 1 Major') == 'recheck'

# A compaction that writes earlier records into the file a second time must not split the prompt it lands in.
import extract
at = lambda m: (week_b + dt.timedelta(minutes=m)).isoformat().replace('+00:00', 'Z')
user = lambda uid, m, text: dict(type='user', uuid=uid, sessionId='dup', timestamp=at(m), turnOrigin='human', message=dict(content=text))
reply = lambda uid, m, mid: dict(type='assistant', uuid=uid, sessionId='dup', timestamp=at(m), version='2.1.325', effort='high', message=dict(
    id=mid, model=OPUS, content=[dict(type='text', text='ok')], usage=dict(input_tokens=10, output_tokens=5, output_tokens_details=dict(thinking_tokens=1))))
first, second = [user('u1', 0, 'first prompt'), reply('a1', 1, 'm1')], [user('u2', 2, 'second prompt'), reply('a2', 3, 'm2')]
lines = first + second + first + [dict(type='system', subtype='compact_boundary', sessionId='dup', timestamp=at(4)),
                                  reply('a3', 5, 'm3'), user('u3', 6, 'third prompt'), reply('a4', 7, 'm4')]
path = os.path.join(TMP, 'dup.jsonl')
open(path, 'w').write('\n'.join(dump(d) for d in lines) + '\n')
got = []
extract.process(path, got)
assert [(t['calls'], t['compactions'], t['next_prompt']) for t in got] == [(1, 0, 'second prompt'), (2, 1, 'third prompt'), (1, 0, None)], got

print('ok')
