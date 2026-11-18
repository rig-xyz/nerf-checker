"""Aggregate stored turns, labels and review signals into the CSVs the dashboard reads. Complete ISO weeks only.

  weekly.csv            one row per week for the primary model
  weekly_by_effort.csv  the same, split by effort level (weeks with at least `min_prompts` prompts at that level)
  by_context.csv        the primary model's judged prompts by context size at the start of the prompt
  error_types.csv       what the primary model's corrections were about
  weekly_by_model.csv   one row per week and model, for every model with at least `min_prompts` prompts that week
  prs_by_model.csv      PRs each model opened per week, with the review bot's inline comments by severity
  reviews_by_model.csv  recorded pre-push reviews per week and model, by what the verdict says they surfaced
  switches.csv          sessions moved off the primary model to another one mid-conversation, and sessions started
                        over in a new one, per week
The primary model is `primary_model` in config.json, or the model with the most prompts.
"""
import os, csv, math, random, collections, datetime as dt
from common import CSV as OUT, config, load, label, counted

CFG = config()
turns, labels, sessions = load('turns.json'), load('labels.json'), load('sessions.json')
this_week = dt.date.today().strftime('%G-W%V')
FIRST_WEEK = CFG['first_week'] or min((t['week'] for t in turns.values() if counted(t)), default=this_week)
MIN_N = CFG['min_prompts']

ALL = []
for k, t in turns.items():
    if not counted(t) or not FIRST_WEEK <= t['week'] < this_week:
        continue
    t['judge'] = labels.get(k)
    ALL.append(t)
by_model = collections.Counter(t['model'] for t in ALL)
MODEL = CFG['primary_model'] or (by_model.most_common(1)[0][0] if by_model else None)
NAME = lambda m: label(m, CFG)
T = [t for t in ALL if t['model'] == MODEL]


def wilson(k, n, z=1.96):
    if not n:
        return (None, None, None)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * p, 1), round(100 * max(0, c - h), 1), round(100 * (c + h), 1))


def interval(J, draws=1000):
    """Error share of judged prompts J with a 95% interval, in %.

    Prompts are not independent: a session that goes badly produces several corrections in a row, so an interval that
    treats each prompt as its own draw (Wilson) is too narrow. This resamples whole sessions instead, and never reports
    less than the Wilson interval, which stays the floor when there are too few sessions to resample."""
    p, lo, hi = wilson(sum(r['judge']['label'] == 'error' for r in J), len(J))
    by = collections.defaultdict(lambda: [0, 0])
    for r in J:
        by[r['session']][0] += 1; by[r['session']][1] += r['judge']['label'] == 'error'
    S = list(by.values())
    if len(S) > 1:
        rng = random.Random(0)
        est = []
        for _ in range(draws):
            pick = rng.choices(S, k=len(S))
            est.append(100 * sum(e for _, e in pick) / sum(n for n, _ in pick))
        est.sort()
        lo = min(lo, round(est[int(.025 * draws)], 1)); hi = max(hi, round(est[int(.975 * draws) - 1], 1))
    return (p, lo, hi)


def q(x, p):
    x = sorted(x)
    return round(x[min(len(x) - 1, int(p * len(x)))], 1) if x else None


def week_start(w):
    y, n = w.split('-W')
    return dt.date.fromisocalendar(int(y), int(n), 1).isoformat()


# Context a new session already holds before the first prompt. 20k-150k skips forks and big pasted openers.
start_ctx = collections.defaultdict(list)
for s in sessions.values():
    if (CFG['entrypoints'] is None or s.get('entrypoint') in CFG['entrypoints']) and 20000 < s.get('ctx', 0) < 150000:
        start_ctx[(dt.datetime.fromisoformat(s['at']).astimezone().strftime('%G-W%V'), s.get('model'))].append(s['ctx'] / 1000)

COLS = ['n', 'judged', 'err', 'err_lo', 'err_hi', 'redirect', 'interrupt', 'apol', 'concede', 'shortcut', 'handback',
        'tool_err', 'edit_fail', 'read_edit', 'think_med', 'think_p75', 'think_per_call', 'zero_think', 'out_med',
        'tools_med', 'ctx_med_k', 'compaction', 'api_err', 'start_ctx_k',
        # added in 0.3; blank for prompts stored before then
        'reread', 'reread_compact', 'verify', 'rejected', 'fallback', 'cache_hit', 'cc_version', 'cc_versions', 'top_effort']

# Served model against requested model, per week and requested model. A prompt answered entirely by another model is
# filed under that model everywhere else, so this one is counted by what was asked for.
asked = collections.defaultdict(lambda: [0, 0])
for t in ALL:
    if t.get('requested'):
        a = asked[(t['week'], t['requested'])]
        a[0] += t['req_calls']; a[1] += t['fallback_calls']


def share(part, whole, digits=1):
    return round(100 * part / whole, digits) if whole else None


def top(values):
    c = collections.Counter(v for v in values if v not in (None, 'none'))
    return c.most_common(1)[0][0] if c else None


def summ(rs, week=None, model=None):
    n = len(rs)
    J = [r for r in rs if r['judge']]
    tools = sum(r['tools'] for r in rs); edits = sum(r['edits'] for r in rs)
    # Thinking columns. A stray call without the thinking-token count (an aborted request) reads as zero, as it always
    # has. But if a tenth or more of the prompts lack it, the transcript format has changed: leave those prompts out
    # rather than report a collapse in thinking that never happened.
    unknown = sum(r.get('think_known') is False for r in rs)
    K = rs if unknown < 0.1 * n else [r for r in rs if r.get('think_known') is not False]
    e = interval(J)
    P = [r for r in rs if 'file_reads' in r]   # prompts stored since the probes below were added
    reads = sum(r['file_reads'] for r in P)
    code = [r for r in P if r['code_edit']]
    versions = ['.'.join(str(r['version']).split('.')[:3]) for r in rs if r.get('version')]
    req = asked.get((week, model)) if week else None
    return dict(
        n=n, judged=len(J), err=e[0], err_lo=e[1], err_hi=e[2],
        redirect=wilson(sum(r['judge']['label'] == 'redirect' for r in J), len(J))[0],
        interrupt=wilson(sum(r['interrupted'] for r in rs), n)[0],
        apol=round(100 * sum(r['apology'] for r in rs) / n, 1),
        concede=round(100 * sum(r['concede'] for r in rs) / n, 1),
        shortcut=round(100 * sum(r['shortcut'] for r in rs) / n, 1),
        handback=round(100 * sum(r['handback'] for r in rs) / n, 1),
        tool_err=round(100 * sum(r['tool_err'] for r in rs) / max(1, tools), 2),
        edit_fail=round(100 * sum(r['edit_fail'] for r in rs) / max(1, edits), 2),
        read_edit=round(sum(r['reads'] for r in rs) / max(1, edits), 2),
        think_med=q([r['thinking_tok'] for r in K], .5), think_p75=q([r['thinking_tok'] for r in K], .75),
        think_per_call=round(sum(r['thinking_tok'] for r in K) / sum(r['calls'] for r in K)) if K else None,
        zero_think=round(100 * sum(r['thinking_tok'] == 0 for r in K) / len(K), 1) if K else None,
        out_med=q([r['out_tok'] for r in rs], .5), tools_med=q([r['tools'] for r in rs], .5),
        ctx_med_k=q([(r['ctx_start'] or 0) / 1000 for r in rs], .5),
        compaction=round(100 * sum(r['compactions'] > 0 for r in rs) / n, 1),
        api_err=round(100 * sum(r['api_errors'] > 0 for r in rs) / n, 1),
        start_ctx_k=q(start_ctx.get((week, model), []), .5) if week else None,
        reread=share(sum(r['reread'] for r in P), reads, 2), reread_compact=share(sum(r['reread_compact'] for r in P), reads, 2),
        verify=share(sum(r['verified'] for r in code), len(code)),
        rejected=share(sum(r['rejected'] > 0 for r in P), len(P)),
        fallback=share(req[1], req[0], 2) if req else None,
        cache_hit=share(sum(r['cache_tok'] for r in P), sum(r['in_tok'] for r in P)),
        cc_version=top(versions), cc_versions=len(set(versions)) or None, top_effort=top(r.get('effort') for r in rs),
    )


def groups(key, rs, min_n=1):
    g = collections.defaultdict(list)
    for r in rs:
        g[key(r)].append(r)
    return sorted((k, v) for k, v in g.items() if len(v) >= min_n)


def write(name, head, rows, tail=()):
    with open(os.path.join(OUT, name), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n'); w.writerow(head + COLS + [t for t, _ in tail])
        for lead, s in rows:
            w.writerow(lead + [s[c] if s[c] is not None else '' for c in COLS] + [v for _, v in tail])


os.makedirs(OUT, exist_ok=True)
primary = [('model', NAME(MODEL))]   # last column, so the page can name the model it is about
write('weekly.csv', ['week_of'], [([week_start(w)], summ(v, w, MODEL)) for w, v in groups(lambda r: r['week'], T)], primary)
write('weekly_by_effort.csv', ['week_of', 'effort'],
      [([week_start(w), e], summ(v)) for (w, e), v in groups(lambda r: (r['week'], r['effort']), [r for r in T if r['effort'] not in (None, 'none')], MIN_N)], primary)
order = ['<50k', '50-150k', '150-300k', '300-600k', '600k+']
ctx = dict(groups(lambda r: r['ctx_bucket'], [r for r in T if r['judge']], 30))
write('by_context.csv', ['context'], [([b], summ(ctx[b])) for b in order if b in ctx], primary)
write('weekly_by_model.csv', ['week_of', 'model'],
      [([week_start(w), NAME(m)], summ(v, w, m)) for (w, m), v in groups(lambda r: (r['week'], r['model']), ALL, MIN_N)])
et = collections.Counter(r['judge']['error_type'] for r in T if r['judge'] and r['judge']['label'] == 'error')
with open(os.path.join(OUT, 'error_types.csv'), 'w', newline='') as f:
    w = csv.writer(f, lineterminator='\n'); w.writerow(['error_type', 'turns', 'model'])
    for k, v in et.most_common():
        w.writerow([k or 'other', v, NAME(MODEL)])


# Review signals, one row per week and model. Only models that pass the prompt threshold in some week are kept.
shown = {m for (_, m), _ in groups(lambda r: (r['week'], r['model']), ALL, MIN_N)}


def by_week_model(items, cols, add):
    g = collections.defaultdict(lambda: dict.fromkeys(cols, 0))
    for it in items:
        if it['model'] in shown and FIRST_WEEK <= it['week'] < this_week:
            add(g[(it['week'], it['model'])], it)
    return [[week_start(w), NAME(m)] + [v[c] for c in cols] for (w, m), v in sorted(g.items())]


def add_pr(row, pr):
    cr = pr.get('cr') or {}
    row['prs'] += 1
    row['cr_prs'] += cr.get('comments', 0) > 0
    row['cr_comments'] += cr.get('comments', 0)
    for sev in ('critical', 'major', 'minor'):
        row['cr_' + sev] += cr.get(sev, 0)
    row['cr_other'] += cr.get('trivial', 0) + cr.get('other', 0)
    ci = (pr.get('ci') or {}).get('result')
    row['ci_prs'] += ci in ('pass', 'fail')   # pull requests whose first CI run finished
    row['ci_pass'] += ci == 'pass'


def add_review(row, rv):
    row['passes'] += 1
    row[rv['outcome']] += 1


for name, cols, items, add in (
        ('prs_by_model.csv', ['prs', 'cr_prs', 'cr_comments', 'cr_critical', 'cr_major', 'cr_minor', 'cr_other', 'ci_prs', 'ci_pass'], load('prs.json').values(), add_pr),
        ('reviews_by_model.csv', ['passes', 'recheck', 'clean', 'small', 'big'], load('reviews.json').values(), add_review)):
    with open(os.path.join(OUT, name), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n'); w.writerow(['week_of', 'model'] + cols); w.writerows(by_week_model(items, cols, add))

# Model switches: a session moved off the primary model to another one mid-conversation is the user's own verdict on how
# it was going. One row per complete week; a switch counts in the week of the first prompt on the new model.
by_session = collections.defaultdict(list)
for t in turns.values():
    if counted(t):
        by_session[t['session']].append(t)
sw = collections.defaultdict(lambda: dict(sessions=set(), switches=0, frustrated=0, compacted=0, ctx=[], to=collections.Counter(),
                                         restarts=0, retries=0))
for sid, ts in by_session.items():
    ts.sort(key=lambda t: t['start'])
    for i, t in enumerate(ts):
        if t['model'] == MODEL:
            sw[t['week']]['sessions'].add(sid)
        elif i and ts[i - 1]['model'] == MODEL:
            r = sw[t['week']]
            r['switches'] += 1
            r['frustrated'] += bool(t.get('frustrated'))
            r['compacted'] += any(x['compactions'] for x in ts[:i])
            r['ctx'].append((ts[i - 1]['ctx_start'] or 0) / 1000)
            r['to'][NAME(t['model'])] += 1
    # Started over: this session's last prompt was on the primary model, and a new session opened in the same folder
    # within 15 minutes of it going quiet (extract.py's restarts). Counted in the week of that last prompt.
    s = sessions.get(sid) or {}
    if ts[-1]['model'] == MODEL and s.get('restarted'):
        sw[ts[-1]['week']]['restarts'] += 1
        sw[ts[-1]['week']]['retries'] += bool(s.get('retried'))
with open(os.path.join(OUT, 'switches.csv'), 'w', newline='') as f:
    w = csv.writer(f, lineterminator='\n')
    w.writerow(['week_of', 'sessions', 'switches', 'per_100_sessions', 'to', 'frustrated', 'compacted_before', 'ctx_at_switch_k',
                'model', 'restarts', 'retries'])
    for wk in sorted(k for k in sw if FIRST_WEEK <= k < this_week):
        r = sw[wk]; n = len(r['sessions'])
        w.writerow([week_start(wk), n, r['switches'], round(100 * r['switches'] / n, 1) if n else '',
                    r['to'].most_common(1)[0][0] if r['to'] else '', r['frustrated'], r['compacted'],
                    q(r['ctx'], .5) if r['ctx'] else '', NAME(MODEL), r['restarts'], r['retries']])

unl = sum(1 for r in ALL if not r['judge'] and r.get('next_prompt'))
print(f'{len(ALL)} prompts in complete weeks {FIRST_WEEK}..{this_week} (excl.); primary model {NAME(MODEL)} with {len(T)}; '
      f'{unl} still unlabelled; CSVs in {OUT}')

# The judge is the instrument. Say when the latest week was read by a different one than the weeks it is compared with.
judges = collections.defaultdict(set)
for r in T:
    if r['judge'] and r['judge'].get('prompt'):   # labels from before judges were recorded can't be compared
        judges[r['week']].add((r['judge'].get('by'), r['judge']['prompt']))
if len(judges) > 1:
    last = max(judges)
    earlier = set().union(*(v for k, v in judges.items() if k != last))
    if judges[last] - earlier:
        new = ', '.join(f'{by} (prompt {p})' for by, p in sorted(judges[last] - earlier, key=str))
        print(f'NOTE: the latest week was judged by {new}, which no earlier week used. Its error share is not strictly '
              'comparable with theirs.')
runs = load('agreement.json').get('runs', [])
if runs:
    n = sum(r['n'] for r in runs); same = sum(r['same_label'] for r in runs)
    either = sum(r['error_either'] for r in runs); both = sum(r['error_both'] for r in runs)
    print(f'Judge consistency, from {n} prompts judged twice: same label on {round(100 * same / n)}%; of {either} called '
          f'an error by either pass, both agreed on {both}.')
print(open(os.path.join(OUT, 'weekly.csv')).read())
