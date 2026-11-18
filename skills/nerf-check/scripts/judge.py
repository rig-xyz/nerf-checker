"""Judge bookkeeping. The labelling itself is done by a model (see references/judge-prompt.md).

  judge.py pending          write prompts that still need a label into data/judge/judge_in_<n>.jsonl, plus
                            judge_in_repeat.jsonl: a sample of the same prompts to be judged a second time
  judge.py prompt <file>    print the judge prompt for one batch file, paths filled in
  judge.py merge <judge>    fold judge_out_<n>.jsonl into data/labels.json, recording the judge model's id and the
                            prompt version; compare judge_out_repeat.jsonl against it and log how often they agree;
                            then drop the text of every labelled prompt

The judge is the measuring instrument, so each label records which model and which prompt produced it. A week judged
by a different model or prompt is not comparable with the others, and report.py says so.
"""
import json, os, sys, glob, random, hashlib, datetime as dt
from common import DATA as D, config, counted, load, save, slim

Q = os.path.join(D, 'judge')
PROMPT = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'judge-prompt.txt')).read()
PROMPT_VERSION = hashlib.sha1(PROMPT.encode()).hexdigest()[:8]
LABELS = ('error', 'redirect', 'continue', 'new')


def judgeable(t):
    return counted(t) and t.get('next_prompt')


def pending(batch_size=450):
    turns, labels = load('turns.json'), load('labels.json')
    items = [dict(id=k, assistant_said=(t.get('last_text') or '')[-500:], user_next=t['next_prompt'][:300])
             for k, t in turns.items() if judgeable(t) and k not in labels]
    os.makedirs(Q, exist_ok=True)
    for f in glob.glob(os.path.join(Q, '*.jsonl')):
        os.remove(f)
    random.seed(0); random.shuffle(items)
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    names = [f'judge_in_{n}.jsonl' for n in range(len(batches))]
    if len(items) >= 20:   # a second, independent pass over a sample: how consistent is the judge with itself?
        batches.append(random.Random(1).sample(items, min(50, max(10, len(items) // 10))))
        names.append('judge_in_repeat.jsonl')
    for name, batch in zip(names, batches):
        with open(os.path.join(Q, name), 'w') as f:
            for it in batch:
                f.write(json.dumps(it) + '\n')
    print(f'{len(items)} turns need labels, in {len(names)} batch file(s) under {Q}')
    for name in names:
        print(os.path.join(Q, name))


def prompt(path):
    path = os.path.abspath(path)
    print(PROMPT.replace('{in}', path).replace('{out}', path.replace('judge_in_', 'judge_out_')))


def read_out(path, want):
    out = {}
    for line in open(path):
        line = line.strip().rstrip(',')
        if not line.startswith('{'):
            continue
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if j.get('id') in want and j.get('label') in LABELS:
            out[j['id']] = dict(label=j['label'], error_type=j.get('error_type') if j['label'] == 'error' else None)
    return out


def merge(judge='unknown'):
    labels = load('labels.json')
    want = set()
    for f in glob.glob(os.path.join(Q, 'judge_in_*.jsonl')):
        want |= {json.loads(l)['id'] for l in open(f) if l.strip()}
    repeat_path = os.path.join(Q, 'judge_out_repeat.jsonl')
    fresh = {}
    for f in glob.glob(os.path.join(Q, 'judge_out_*.jsonl')):
        if f != repeat_path:
            fresh.update(read_out(f, want))
    for k, v in fresh.items():
        labels[k] = dict(v, by=judge, prompt=PROMPT_VERSION)
    save('labels.json', labels)
    missing = len(want - set(labels))
    print(f'merged {len(fresh)} labels by {judge} (prompt {PROMPT_VERSION}); {len(labels)} total; {missing} pending turns still unlabelled')

    if os.path.exists(repeat_path):
        again = read_out(repeat_path, set(fresh))
        if again:
            e1 = {k for k in again if fresh[k]['label'] == 'error'}
            e2 = {k for k, v in again.items() if v['label'] == 'error'}
            log = load('agreement.json') or {'runs': []}
            log['runs'].append(dict(at=dt.datetime.now(dt.timezone.utc).isoformat(), by=judge, prompt=PROMPT_VERSION,
                                    n=len(again), same_label=sum(fresh[k]['label'] == v['label'] for k, v in again.items()),
                                    error_either=len(e1 | e2), error_both=len(e1 & e2)))
            save('agreement.json', log, indent=1)
            r = log['runs'][-1]
            print(f"judged twice: {r['n']} prompts, same label on {r['same_label']}; of {r['error_either']} called an "
                  f"error by either pass, both agreed on {r['error_both']}")

    turns = load('turns.json')
    keep = config()['keep_text']
    for k, t in turns.items():
        slim(t, k in labels, keep)
    if turns:
        save('turns.json', turns)
    if not missing:   # the batch files hold the same text; nothing needs them once every prompt has its label
        for f in glob.glob(os.path.join(Q, '*.jsonl')):
            os.remove(f)


if __name__ == '__main__':
    {'pending': pending, 'prompt': prompt, 'merge': merge}[sys.argv[1]](*sys.argv[2:3])
