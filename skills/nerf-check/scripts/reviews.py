"""Review signals per model: PRs a model opened (and what the review bot said about them) and recorded pre-push reviews.

`reviews.py [days]` rescans transcripts touched in the last `days` (default 14) and merges into
  data/prs.json      keyed by PR url: the model whose `gh pr create` call opened it, when, and the review bot's inline
                     comments by severity (fetched with `gh api`; PRs opened in the last 21 days are refetched).
  data/reviews.json  keyed by timestamp: each call of the configured `review_mark` command, the model that made it,
                     its one-line verdict and what that says it surfaced (big, small, clean or recheck).
                     Skipped when `review_mark` is not set in config.json.
                     Also how the first CI run on each PR ended (`ci`), read once per PR; off with "ci": false.
Only reads from GitHub, with the user's own `gh` login. A PR that can't be fetched keeps `cr: null` and is retried on
the next run; without `gh` the PR list is still kept, just without comment counts.
"""
import json, os, re, sys, glob, shutil, subprocess, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from common import TRANSCRIPTS, config, in_subagent, load, save

CFG = config()
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
NOW = dt.datetime.now(dt.timezone.utc)
PR_URL = re.compile(r'https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)')
ARG = r'(?:"(?:[^"\\]|\\.)*"|\'[^\']*\'|[^\s;&|<>]+)'
MARK = re.compile(r'(?:' + CFG['review_mark'] + r')((?:[ \t]+' + ARG + r')+)') if CFG['review_mark'] else None
MARK_PRE = re.compile(CFG['review_mark']) if CFG['review_mark'] else None   # cheap line filter
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
# Severities are read from CodeRabbit's format; comments from another `review_bot` are counted, all as "other".
# CodeRabbit's two comment headers: an icon then "Major**", or "**<emoji> Major**"; older ones use "_<emoji> Major_".
SEV = re.compile(r'(?:</picture>|\*\*\S+)\s*(Critical|Major|Minor|Trivial|Nitpick|Info)\w*\*\*|_(?:\S+\s)?(Critical|Major|Minor|Trivial|Nitpick)_', re.I)
SEVS = ['critical', 'major', 'minor', 'trivial']
RECHECK = re.compile(r're-?review|rebas|\bmerge of\b|on top of reviewed|same (single )?commit'
                     + ('|' + CFG['review_recheck'] if CFG['review_recheck'] else ''), re.I)
_SEVW = r'(criticals?|highs?|majors?|mediums?|minors?|lows?|findings?|nits?)'
NEGATED = re.compile(r'\b(no|zero|0)\s+((open|new)\s+)?' + _SEVW + r'(\s+open)?(\s*(,|/|or|and)\s*' + _SEVW + r')*', re.I)


def week(ts):
    return dt.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone().strftime('%G-W%V')


def outcome(verdict):
    """What a one-line verdict says the pass surfaced: big (Critical, Major, High), small (Medium, Minor, Low, nit or an
    unlabelled finding), clean, or recheck (a re-mark after a rebase, merge or follow-up fix, not a fresh review)."""
    if RECHECK.search(verdict):
        return 'recheck'
    v = NEGATED.sub(' ', verdict)
    if re.search(r'critical|major|\bHighs?\b', v, re.I):
        return 'big'
    if re.search(r'\bMediums?\b|minor|\bLows?\b|\bnits?\b|trivial|\bfindings?\b|\binfo:', v):
        return 'small'
    return 'clean'


def scan():
    prs, marks = {}, {}
    files = [f for f in glob.glob(os.path.join(TRANSCRIPTS, '**', '*.jsonl'), recursive=True)
             if os.path.getmtime(f) > (NOW - dt.timedelta(days=DAYS)).timestamp() and not in_subagent(f)]
    for f in files:
        pending = {}
        for line in open(f, errors='ignore'):
            if 'gh pr create' not in line and 'tool_result' not in line and not (MARK_PRE and MARK_PRE.search(line)):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get('message') or {}
            c = m.get('content')
            if not isinstance(c, list):
                continue
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'tool_use' and b.get('name') == 'Bash' and m.get('model') and d.get('timestamp'):
                    cmd = (b.get('input') or {}).get('command', '')
                    if 'gh pr create' in cmd:
                        pending[b['id']] = (m['model'], d['timestamp'])
                    for i, mk in enumerate(MARK.finditer(cmd) if MARK else ()):
                        quoted = QUOTED.findall(mk.group(1))
                        if not quoted:
                            continue   # the command was only read or listed, not run with a verdict
                        verdict = quoted[-1]
                        marks[f"{d['timestamp']}|{i}"] = dict(
                            model=m['model'], at=d['timestamp'], week=week(d['timestamp']), verdict=verdict[:300],
                            outcome=outcome(verdict))
                elif b.get('type') == 'tool_result' and b.get('tool_use_id') in pending and not b.get('is_error'):
                    model, at = pending.pop(b['tool_use_id'])
                    u = PR_URL.search(str(b.get('content')))
                    if u and (u.group(0) not in prs or at < prs[u.group(0)]['at']):
                        prs[u.group(0)] = dict(model=model, at=at, week=week(at))
    return len(files), prs, marks


def bot_comments(url):
    owner, repo, num = PR_URL.search(url).groups()
    try:
        r = subprocess.run(['gh', 'api', f'repos/{owner}/{repo}/pulls/{num}/comments', '--paginate', '--jq',
                            '.[] | select(.user.login == "%s" and .in_reply_to_id == null) | .body[0:600] | @json' % CFG['review_bot']],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return None
    out = dict(comments=0, other=0, fetched=NOW.isoformat(), **{s: 0 for s in SEVS})
    for line in r.stdout.splitlines():
        body = json.loads(line)
        s = SEV.search(body)
        sev = (s.group(1) or s.group(2)).lower() if s else 'other'
        sev = 'trivial' if sev == 'nitpick' else sev
        out['comments'] += 1
        out[sev if sev in SEVS else 'other'] += 1
    return out


def gh(path, jq, paginate=False):
    """Rows of a read-only GitHub API call, or None if it failed."""
    try:
        r = subprocess.run(['gh', 'api', path, '--jq', jq] + (['--paginate'] if paginate else []),
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return None
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


BAD = {'failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure', 'error'}


def first_ci(url):
    """How the first CI run on a pull request ended: every check on the commit that was its head when it was opened,
    each taken at its first attempt, so a re-run that later went green does not hide a red first try. The review bot's
    own check is not CI and is left out.
      pass / fail   every check finished; `failed` says how many did not pass
      pending       something is still running; read again next time
      none          the commit has no checks: the repository has no CI
      unknown       the opening commit is gone (the branch was rebased or force-pushed), so it can't be told"""
    owner, repo, num = PR_URL.search(url).groups()
    base = f'repos/{owner}/{repo}'
    pr = gh(f'{base}/pulls/{num}', '{at: .created_at}')
    commits = gh(f'{base}/pulls/{num}/commits?per_page=100', '.[] | {sha, at: .commit.committer.date}', paginate=True)
    if not pr or commits is None:
        return None
    opened = dt.datetime.fromisoformat(pr[0]['at'].replace('Z', '+00:00')) + dt.timedelta(minutes=1)
    there = [c for c in commits if dt.datetime.fromisoformat(c['at'].replace('Z', '+00:00')) <= opened]
    if not there:
        return dict(result='unknown', runs=0, failed=0)
    sha = there[-1]['sha']
    bot = CFG['review_bot'].replace('[bot]', '').lower()

    def is_bot(name):   # "coderabbitai" the app, "CodeRabbit" the status it posts
        n = (name or '').lower().replace(' ', '')
        return bool(n) and (bot in n or (len(n) >= 5 and n in bot))
    runs = gh(f'{base}/commits/{sha}/check-runs?per_page=100&filter=all',
              '.check_runs[] | {name, status, conclusion, at: .started_at, app: .app.slug}', paginate=True)
    states = gh(f'{base}/commits/{sha}/status', '.statuses[] | {name: .context, state}')
    if runs is None or states is None:
        return None
    first = {}
    for r in sorted(runs, key=lambda r: r['at'] or ''):
        if not is_bot(r['app']) and not is_bot(r['name']):
            first.setdefault(r['name'], 'pending' if r['status'] != 'completed' else r['conclusion'])
    for st in states:   # commit statuses (older CI systems): the API only keeps each one's latest state
        if not is_bot(st['name']):
            first['status:' + st['name']] = st['state']
    if not first:
        return dict(result='none', runs=0, failed=0)
    failed = sum(v in BAD for v in first.values())
    result = 'fail' if failed else 'pending' if 'pending' in first.values() else 'pass'
    return dict(result=result, runs=len(first), failed=failed, sha=sha[:7])


def main():
    n, found, marks = scan()
    prs = load('prs.json')
    for u, p in found.items():
        if u not in prs or p['at'] < prs[u]['at']:
            prs[u] = dict(prs.get(u, {}), **p)
    fetched = failed = 0
    have_gh = bool(shutil.which('gh'))
    for u, p in prs.items():
        fresh = dt.datetime.fromisoformat(p['at'].replace('Z', '+00:00')) > NOW - dt.timedelta(days=21)
        if have_gh and (p.get('cr') is None or fresh or os.environ.get('REFETCH')):
            cr = bot_comments(u)
            fetched += cr is not None; failed += cr is None
            p['cr'] = cr or p.get('cr')
        p.setdefault('cr', None)
    ci_note = ''
    if have_gh and CFG['ci']:   # once per pull request: a first run that has finished does not change
        fresh = lambda p: dt.datetime.fromisoformat(p['at'].replace('Z', '+00:00')) > NOW - dt.timedelta(days=21)
        todo = [u for u, p in prs.items() if not p.get('ci') or (p['ci']['result'] == 'pending' and fresh(p))]
        with ThreadPoolExecutor(8) as pool:
            got = dict(zip(todo, pool.map(first_ci, todo)))
        for u, ci in got.items():
            prs[u]['ci'] = ci or prs[u].get('ci')
        ci_note = f"; first CI run read for {sum(v is not None for v in got.values())} of {len(todo)} PRs"
    save('prs.json', prs, indent=0)
    reviews = load('reviews.json')
    added = len(set(marks) - set(reviews))
    reviews.update(marks)
    for v in reviews.values():   # reclassify stored verdicts so a rule change applies to history too
        v['outcome'] = outcome(v['verdict'])
    save('reviews.json', reviews, indent=0)
    note = f'{fetched} fetched from GitHub, {failed} failed' if have_gh else 'gh not found, comment counts skipped'
    rv = f'{len(reviews)} recorded reviews ({added} new)' if MARK else 'recorded reviews off (no review_mark in config.json)'
    print(f'{n} transcripts scanned; {len(prs)} PRs stored ({note}{ci_note}); {rv}')


if __name__ == '__main__':
    main()
