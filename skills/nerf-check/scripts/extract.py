"""Nerf check: mine Claude Code transcripts for behaviour/quality proxies over time.

Unit of analysis = a "turn": one human prompt in a main (non-subagent) thread and everything
the model did until the next human prompt. Every turn carries its confounds (model, effort,
CC version, context size) so trends can be stratified instead of eyeballed.

`extract.py [days]` rescans transcripts touched in the last `days` (default 14) and merges into data/turns.json.
What is stored is numbers: the prompt text is used for the row key and one flag, then dropped (common.slim).
"""
import json, glob, os, re, sys, collections, hashlib, datetime as dt
from common import DATA, TRANSCRIPTS, FRUSTRATED, config, in_subagent, load, save, slim
from probes import END, Reads, same_ask, shell_reads, words

CFG = config()

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14   # re-scan window; older turns stay in data/turns.json
SESSION_START = {}   # sessionId -> first main-thread API call (fixed overhead before the user's first prompt)
SESSION_META = {}    # sessionId -> folder (hashed), first prompt, last activity, for the restart probe
NOW = dt.datetime.now(dt.timezone.utc)
START = NOW - dt.timedelta(days=DAYS)

TAG_BLOCK = re.compile(r'<(system-reminder|artifact-view-context|ide_[a-z_]+|command-[a-z]+|local-command-[a-z]+|task-notification|side-sessions-event|ci-monitor-event)\b[^>]*>.*?</\1>', re.S)
INTERRUPT = '[Request interrupted by user'
APOLOGY = re.compile(r"\b(i apologi[sz]e|sorry|my (mistake|bad|apologies)|apologies for)\b", re.I)
CONCEDE = re.compile(r"\b(you'?re (absolutely |completely |totally )?right|good catch|i was wrong|i should have|i (made|introduced) (a|an) (error|mistake|bug)|i (missed|overlooked))\b", re.I)
HANDBACK = re.compile(r"\b(you (can|could|may want to|might want to|'ll need to|will need to|should) (now )?(run|try|check|verify|test|update|add|replace)|let me know if)\b", re.I)
SHORTCUT = re.compile(r"\b(for brevity|rest (of the|unchanged)|simplified version|placeholder|stub(bed)? (out|for now)|for now,? (i'?ll|we'?ll)|skip(ping)? (the )?tests?|mock(ed)? (out|for now)|todo:)\b", re.I)
READ_BASH = re.compile(r'^\s*(cd [^;&]+(&&|;)\s*)?(cat|sed -n|head|tail|grep|rg|find|ls|wc|less|nl|awk|jq|git (show|diff|log|grep|blame))\b')
EDIT_BASH = re.compile(r"(sed -i|perl -pi|\bcat\s*>|\btee\b|>\s*[\w./-]+\.(py|ts|tsx|js|swift|go|md|json|ya?ml|toml|html|css)\b|apply_patch|python3? - <<)")
FILE_TOKEN = re.compile(r'[\w.-]+\.\w{1,6}\b')
REWRITES_TREE = re.compile(r'\bgit (checkout|switch|stash|pull|merge|rebase|reset|restore|apply|cherry-pick|revert)\b')
# Verify-before-done probe: an edit to code, and then a test, build, type check, lint or a run of the code itself.
DOCS = ('.md', '.mdx', '.txt', '.rst', '.csv')
CODE_EDIT_BASH = re.compile(r"sed -i|perl -pi|apply_patch|>\s*[\w./-]+\.(py|ts|tsx|js|jsx|swift|go|rs|java|kt|rb|c|cc|cpp|h|css|html|sql|sh)\b")
VERIFY_BASH = re.compile(
    r"\b(pytest|py\.test|unittest|py_compile|compileall|tox|nox|mypy|pyright|ruff|flake8|pylint|tsc|jest|vitest|mocha|playwright|"
    r"cypress|eslint|shellcheck|xcodebuild|rspec|phpunit|ctest|make|gradlew?|mvn|"
    r"go (test|build|vet|run)|cargo (test|build|check|clippy|run)|swift (build|test|run)|dotnet (test|build|run)|"
    r"mix (test|compile)|bazel (test|build)|rake|(npm|pnpm|yarn|bun)( run)? [\w:-]*(test|build|lint|check|tsc)[\w:-]*|"
    r"node --check|curl\s[^|;&]*(localhost|127\.0\.0\.1)|"
    r"(python3?|node|bash|sh|zsh|ruby|deno|bun|tsx|ts-node)\s+(-\w+\s+)*[\w./-]+\.(py|js|mjs|ts|sh|rb))\b|(^|[;&|]\s*)\./[\w./-]+")
VERIFY_TOOL = re.compile(r'browser|chrome|playwright|simulator|preview', re.I)
VERIFY_MORE = re.compile(CFG['verify']) if CFG['verify'] else None
MODEL_SUFFIX = re.compile(r'(-\d{8})?(\[.*\])?$')

# prompts no person typed: scheduled tasks, plus whatever the config's `automated` pattern adds
AUTOMATED = re.compile(r'\s*(<scheduled-task|\[SCHEDULED TASK)')
AUTOMATED_MORE = re.compile(CFG['automated']) if CFG['automated'] else None
# API calls per Claude Code version, and how many carried the thinking-token count (see drift_warnings)
FIELDS = collections.defaultdict(lambda: [0, 0])
EDIT_TOOLS = {'Edit', 'MultiEdit', 'Write', 'NotebookEdit'}
READ_TOOLS = {'Read', 'Grep', 'Glob'}


def ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def human_text(d):
    c = d.get('message', {}).get('content')
    if isinstance(c, str):
        parts = [c]
    elif isinstance(c, list):
        if any(b.get('type') == 'tool_result' for b in c if isinstance(b, dict)):
            return None
        parts = [b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text']
    else:
        return None
    return TAG_BLOCK.sub('', '\n'.join(parts)).strip()


def is_human(d):
    if d.get('type') != 'user' or d.get('isMeta') or d.get('isSidechain') or d.get('isCompactSummary'):
        return False
    if d.get('toolUseResult') is not None:
        return False
    to = d.get('turnOrigin') or (d.get('origin') or {}).get('kind')
    if to is not None:
        return to == 'human'
    t = human_text(d)
    return bool(t) and not t.startswith('<') and not t.startswith('Caveat:') and not t.startswith('[Request interrupted')


def mode(c):
    return c.most_common(1)[0][0] if c else None


def new_turn(d, text):
    text = text or ''
    automated = bool(AUTOMATED.match(text)) or bool(AUTOMATED_MORE and AUTOMATED_MORE.search(text[:2000]))
    return dict(session=d.get('sessionId'), start=ts(d['timestamp']),
                key=hashlib.sha1(text[:200].encode()).hexdigest()[:10], prompt_len=len(text),
                frustrated=bool(FRUSTRATED.search(text[:600])), calls=0, tools=0, tool_err=0, edit_fail=0,
                reads=0, edits=0, thinking_tok=0, think_known=False, out_tok=0, ctx_start=None,
                file_reads=0, reread=0, reread_compact=0, code_edit=False, verified=False, rejected=0,
                in_tok=0, cache_tok=0, req_calls=0, fallback_calls=0, requested=collections.Counter(),
                apology=0, concede=0, handback=0, shortcut=0, interrupted=False,
                models=collections.Counter(), efforts=collections.Counter(), versions=collections.Counter(),
                next_prompt=None, ctx_bucket=None, compactions=0, api_errors=0, last_text='',
                entrypoint=d.get('entrypoint'), automated=automated)


def process(path, turns):
    recs = []
    for line in open(path, errors='ignore'):
        if '"type":"assistant"' not in line and '"type":"user"' not in line and '"subtype":"api_error"' not in line and '"subtype":"compact_boundary"' not in line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    # Some compactions write a stretch of earlier records into the file a second time, same ids and all. Read each
    # record once: replayed, they would cut the prompt in progress short and hand its tail to a prompt from hours ago.
    once, known = [], set()
    for d in recs:
        if d.get('uuid') not in known:
            once.append(d)
            if d.get('uuid'):
                known.add(d['uuid'])
    recs = once
    turn = None
    seen_msg = {}
    reads = Reads()   # built from the whole file, so a session older than the window still knows its past

    def close(turn):
        if turn['start'] >= START:   # older turns are already stored
            turns.append(turn)

    for d in recs:
        t = ts(d.get('timestamp', ''))
        if not t:
            continue
        if d.get('isSidechain'):
            continue
        meta = SESSION_META.setdefault(d.get('sessionId'), dict(first=None, last=t))
        meta['last'] = max(meta['last'], t)
        if d['type'] == 'system':
            if d.get('subtype') == 'compact_boundary':
                reads.window += 1
                if turn:
                    turn['compactions'] += 1
            elif turn and d.get('subtype') == 'api_error' and not (d.get('error') or {}).get('isNetworkDown'):
                turn['api_errors'] += 1
            continue
        if d['type'] == 'user':
            if is_human(d):
                text = human_text(d) or ''
                if turn:
                    turn['next_prompt'] = text[:300]
                    close(turn)
                turn = new_turn(d, text)
                if not turn['automated']:
                    meta['prompts'] = meta.get('prompts', 0) + 1
                    if meta['first'] is None or t < meta['first']:
                        meta.update(first=t, words=words(text), entrypoint=d.get('entrypoint'),
                                    dir=hashlib.sha1((d.get('cwd') or '').encode()).hexdigest()[:10])
                continue
            if not turn:
                continue
            c = d.get('message', {}).get('content')
            if isinstance(c, str) and INTERRUPT in c:
                turn['interrupted'] = True
            if isinstance(c, list):
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get('type') == 'text' and INTERRUPT in b.get('text', ''):
                        turn['interrupted'] = True
                    if b.get('type') == 'tool_result' and b.get('is_error'):
                        turn['tool_err'] += 1
                        s = str(b.get('content'))[:300]
                        if 'String to replace not found' in s or 'has not been read' in s or 'modified since read' in s:
                            turn['edit_fail'] += 1
            if d.get('toolDenialKind') == 'user-rejected':
                turn['rejected'] += 1
        elif d['type'] == 'assistant' and turn:
            m = d.get('message', {})
            if m.get('model') == '<synthetic>':
                continue
            mid = m.get('id') or d.get('requestId')
            u = m.get('usage') or {}
            first = mid not in seen_msg
            sid = d.get('sessionId')
            if first and not d.get('isSidechain') and (sid not in SESSION_START or t.isoformat() < SESSION_START[sid]['at']):
                SESSION_START[sid] = dict(at=t.isoformat(), model=m.get('model'), entrypoint=d.get('entrypoint'), version=d.get('version'),
                    ctx=(u.get('input_tokens') or 0) + (u.get('cache_read_input_tokens') or 0) + (u.get('cache_creation_input_tokens') or 0))
            if first:
                seen_msg[mid] = 1
                ctx = (u.get('input_tokens') or 0) + (u.get('cache_read_input_tokens') or 0) + (u.get('cache_creation_input_tokens') or 0)
                details = u.get('output_tokens_details') or {}
                known = 'thinking_tokens' in details
                seen = FIELDS['.'.join(str(d.get('version') or '?').split('.')[:3])]
                seen[0] += 1; seen[1] += known
                turn['calls'] += 1
                turn['thinking_tok'] += details.get('thinking_tokens') or 0
                turn['think_known'] = turn['think_known'] or known
                turn['out_tok'] += u.get('output_tokens') or 0
                if turn['ctx_start'] is None:
                    turn['ctx_start'] = ctx
                turn['models'][m.get('model')] += 1
                turn['efforts'][d.get('effort') or 'none'] += 1
                turn['versions'][d.get('version')] += 1
                turn['in_tok'] += ctx
                turn['cache_tok'] += u.get('cache_read_input_tokens') or 0
                asked_for = d.get('requestedModel')
                if asked_for:   # what the client asked for against what answered: a mismatch is a silent fallback
                    turn['req_calls'] += 1
                    turn['requested'][MODEL_SUFFIX.sub('', asked_for)] += 1
                    turn['fallback_calls'] += MODEL_SUFFIX.sub('', asked_for) != MODEL_SUFFIX.sub('', m.get('model') or '')
            for b in m.get('content') or []:
                bt = b.get('type')
                if bt == 'text':
                    x = b.get('text', '')
                    if x.strip():
                        turn['last_text'] = x[-700:]
                    turn['apology'] += len(APOLOGY.findall(x))
                    turn['concede'] += len(CONCEDE.findall(x))
                    turn['handback'] += len(HANDBACK.findall(x))
                    turn['shortcut'] += len(SHORTCUT.findall(x))
                elif bt == 'tool_use':
                    turn['tools'] += 1
                    name, inp = b.get('name'), b.get('input') or {}
                    if name in READ_TOOLS:
                        turn['reads'] += 1
                        p = inp.get('file_path')
                        if name == 'Read' and p:
                            lo = inp.get('offset') or 1
                            reads.read(p, lo, lo + inp['limit'] - 1 if inp.get('limit') else END, turn)
                    elif name in EDIT_TOOLS:
                        turn['edits'] += 1
                        p = inp.get('file_path') or inp.get('notebook_path') or ''
                        reads.changed({os.path.basename(p)})
                        if not p.lower().endswith(DOCS):
                            turn['code_edit'], turn['verified'] = True, False
                    elif name == 'Bash':
                        cmd = inp.get('command', '')
                        if REWRITES_TREE.search(cmd):
                            reads.forget()
                        if EDIT_BASH.search(cmd):
                            turn['edits'] += 1
                            reads.changed(set(FILE_TOKEN.findall(cmd)))
                            if CODE_EDIT_BASH.search(cmd):
                                turn['code_edit'], turn['verified'] = True, False
                        elif READ_BASH.search(cmd):
                            turn['reads'] += 1
                            for p, lo, hi in shell_reads(cmd):
                                reads.read(p, lo, hi, turn)
                        if VERIFY_BASH.search(cmd) or (VERIFY_MORE and VERIFY_MORE.search(cmd)):
                            turn['verified'] = turn['code_edit']
                    elif VERIFY_TOOL.search(name or ''):
                        turn['verified'] = turn['code_edit']
    if turn:
        close(turn)


def bucket(n):
    for lim, lab in [(50e3, '<50k'), (150e3, '50-150k'), (300e3, '150-300k'), (600e3, '300-600k')]:
        if n < lim:
            return lab
    return '600k+'


def turn_key(t):
    """session | start | hash of the prompt's first 200 characters. Stable across rescans, and holds no prompt text."""
    return f"{t['session']}|{t['start']}|{t.pop('key')}"


def drift_warnings():
    """The thinking numbers come from a usage field Claude Code does not document. If a release stops writing it, every
    prompt would read as zero thinking, which looks exactly like a nerf. Say so instead."""
    out = []
    for version, (calls, known) in sorted(FIELDS.items()):
        if calls >= 200 and known < 0.9 * calls:
            out.append(f'WARNING: Claude Code {version} wrote the thinking-token count on {known} of {calls} API calls. '
                       'The thinking columns are incomplete for it; check whether the transcript format changed.')
    return out


def restarts(gap=dt.timedelta(minutes=15)):
    """Sessions that were given up on: a new session opened in the same folder within 15 minutes of this one going
    quiet for good, after a real conversation (two prompts or more). `retried` when the new session's first prompt
    asks for much the same as this one's did. A new session opening with the very same words is a template, not a
    person starting over, and is not counted. Recomputed for every session seen in this run; a session that later picks up again stops counting."""
    by_dir = collections.defaultdict(list)
    for sid, m in SESSION_META.items():
        if m.get('first') and not str(m.get('entrypoint') or '').startswith('sdk-'):
            by_dir[m['dir']].append((m['first'], sid, m))
    out = {sid: dict(last=m['last'].isoformat(), restarted=False, retried=False) for sid, m in SESSION_META.items() if m.get('first')}
    for group in by_dir.values():
        group.sort(key=lambda g: g[0])
        for first, sid, m in group:
            before = [(o['last'], osid, o) for _, osid, o in group
                      if osid != sid and o['first'] < first and o['last'] <= first and first - o['last'] <= gap
                      and o.get('prompts', 0) >= 2 and o['words'] != m['words']]
            if before:
                _, osid, o = max(before, key=lambda b: b[0])
                out[osid]['restarted'] = True
                out[osid]['retried'] = same_ask(m['words'], o['words'])
    return out


def main():
    files = [f for f in glob.glob(os.path.join(TRANSCRIPTS, '**', '*.jsonl'), recursive=True)
             if os.path.getmtime(f) > START.timestamp() and not in_subagent(f)]
    turns = []
    for f in files:
        process(f, turns)
    store = load('turns.json')
    labels = load('labels.json')
    added = 0
    for t in turns:
        if t['calls'] == 0:
            continue
        t['model'] = mode(t['models']); t['effort'] = mode(t['efforts']); t['version'] = mode(t['versions'])
        t['requested'] = mode(t['requested'])
        t['ctx_bucket'] = bucket(t['ctx_start'] or 0)
        t['week'] = t['start'].astimezone().strftime('%G-W%V')
        t['start'] = t['start'].isoformat()
        k = turn_key(t)
        added += k not in store
        store[k] = t   # newer scan wins: a turn still in progress last week gets its final numbers
    for k, t in store.items():   # every stored turn, so a history written by an older version is slimmed too
        slim(t, k in labels, CFG['keep_text'])
    save('turns.json', store)
    ss = load('sessions.json')
    for k, v in SESSION_START.items():
        if k not in ss or v['at'] < ss[k]['at']:
            ss[k] = dict(ss.get(k, {}), **v)
    for sid, r in restarts().items():
        if sid in ss:
            ss[sid].update(r)
    save('sessions.json', ss)
    print(f'{len(files)} transcripts scanned, {added} new turns, {len(store)} turns stored, {len(ss)} sessions, in {DATA}')
    for w in drift_warnings():
        print(w)


if __name__ == '__main__':
    main()
