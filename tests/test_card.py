"""The nerf card on made-up weeks: each verdict, the figures it quotes, and that drawing it touches nothing outside its
output folder. No packages, no network, no browser (the PNG step is skipped).

    python3 tests/test_card.py
"""
import csv, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD = os.path.join(ROOT, 'skills', 'nerf-card', 'scripts', 'card.py')
COLS = ['week_of', 'n', 'judged', 'err', 'err_lo', 'err_hi', 'think_med', 'verify', 'apol', 'concede', 'cc_version',
        'top_effort', 'model']
WEEKS = ['2026-09-21', '2026-09-28', '2026-10-05', '2026-10-12', '2026-10-19']
tmp = tempfile.mkdtemp()


def week(i, err, lo, hi, judged=400, cc='2.4.10', effort='high', model='Model A'):
    return dict(week_of=WEEKS[i], n=judged + 20, judged=judged, err=err, err_lo=lo, err_hi=hi, think_med=1400 + 10 * i,
                verify=70 + i, apol=0.5, concede=5.0, cc_version=cc, top_effort=effort, model=model)


def card(name, rows, *args, by_model=False):
    """Write the weeks as nerf-check would and draw the card. Returns (the JSON it prints, its notes, the page)."""
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'weekly_by_model.csv' if by_model else 'weekly.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(rows)
    r = subprocess.run([sys.executable, CARD, '--csv', d, '--out', os.path.join(d, 'out'), '--no-png', *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    return out, r.stderr, open(out['html']).read()


steady = [week(0, 8.3, 6.8, 10.2), week(1, 9.1, 7.8, 10.8), week(2, 7.6, 5.7, 9.9), week(3, 8.8, 7.5, 10.4)]

# Inside the earlier range.
out, notes, page = card('same', steady + [week(4, 8.1, 6.6, 10.0)])
assert out['verdict'] == 'NOT NERFED' and out['usual'] == [7.6, 9.1] and out['earlier_weeks'] == 4, out
assert out['png'] is None and 'NOT NERFED' in page and 'data-verdict="not_nerfed"' in page
assert 'Model A' in page and '8.1%' in page and 'not a benchmark' in page and 'Rig Labs' in page
assert '{{' not in page, 'a placeholder was left unfilled'
# The keyword rates (per 100 prompts) come out as that week's counts: 5.0 and 0.5 per 100 of 420 prompts.
assert out['said_youre_right'] == 21 and out['said_sorry'] == 2, out
assert '>21<small>times</small>' in page and 'and said sorry 2 times' in page
assert '420 of my own Claude Code prompts that week, 2,100 over 5 weeks' in page
# One file, nothing fetched: the fonts are inlined and no address is loaded.
assert 'src="http' not in page and 'url(http' not in page and '@import' not in page and page.count('data:font/woff2') == 3
assert 'Rig Labs' in out['post_text'] or '@riglabs_' in out['post_text']
assert 'github.com/rig-xyz/nerf-checker' in out['post_text'] and len(out['post_text']) <= 280

# Above every earlier week, interval and all, in a week the client changed.
out, notes, page = card('nerfed', steady + [week(4, 14.9, 13.5, 16.6, cc='2.5.0', effort='medium')])
assert out['verdict'] == 'NERFED', out
assert out['changed'] == ['Claude Code went 2.4.10 → 2.5.0', 'effort went high → medium'], out['changed']
assert 'Before blaming the model' in page and '2.5.0' in page

# Above the earlier weeks, but the interval reaches back into their range.
out, notes, page = card('sus', steady + [week(4, 10.9, 8.2, 13.9)])
assert out['verdict'] == 'SUS' and 'may be noise' in page, out

# Below every earlier week, interval and all.
out, notes, page = card('buffed', steady + [week(4, 4.1, 2.6, 6.0)])
assert out['verdict'] == 'BUFFED', out
# Below, but the interval reaches the range: not a buff.
out, notes, page = card('lower', steady + [week(4, 7.0, 5.0, 9.0)])
assert out['verdict'] == 'NOT NERFED', out

# Too little to compare with: few earlier weeks, a thin latest week, or earlier weeks too thin to count.
assert card('two', steady[:2] + [week(4, 30.0, 25.0, 35.0)])[0]['verdict'] == 'TOO EARLY'
assert card('thin', steady + [week(4, 30.0, 10.0, 50.0, judged=40)])[0]['verdict'] == 'TOO EARLY'
thin_before = [week(i, 8.0, 6.0, 10.0, judged=30) for i in range(4)]
assert card('thin-before', thin_before + [week(4, 30.0, 25.0, 35.0)])[0]['verdict'] == 'TOO EARLY'

# An old latest week is called out, so a stale card is not shared as this week's.
assert 'Run a nerf check to refresh it' in notes

# Another model comes from the by-model file; a name with no rows says which names exist.
both = [dict(r, model='Model B') for r in steady + [week(4, 4.1, 2.6, 6.0)]] + steady + [week(4, 8.1, 6.6, 10.0)]
out, notes, page = card('models', both, '--model', 'model b', by_model=True)
assert out['verdict'] == 'BUFFED' and out['model'] == 'Model B' and 'model-b' in out['html'], out
r = subprocess.run([sys.executable, CARD, '--csv', os.path.join(tmp, 'models'), '--no-png', '--model', 'Model Z'],
                   capture_output=True, text=True)
assert r.returncode != 0 and 'Model A, Model B' in r.stderr, r.stderr

# An earlier week on request: the weeks after it are left out, and a week that is not on file is refused.
late = steady + [week(4, 14.9, 13.5, 16.6)]
out, notes, page = card('asof', late, '--week', WEEKS[3])
assert out['verdict'] == 'NOT NERFED' and out['week_of'] == WEEKS[3] and out['earlier_weeks'] == 3, out
assert 'refresh' not in notes, 'an asked-for week is not a stale one'
r = subprocess.run([sys.executable, CARD, '--csv', os.path.join(tmp, 'asof'), '--no-png', '--week', '2026-01-05'],
                   capture_output=True, text=True)
assert r.returncode != 0 and WEEKS[0] in r.stderr, r.stderr

# Weeks written before the keyword columns existed still draw.
old = [{k: r[k] for k in r if k not in ('apol', 'concede')} for r in steady + [week(4, 8.1, 6.6, 10.0)]]
out, notes, page = card('old', old)
assert out['said_youre_right'] is None and 'concession phrases, by keyword' in page, out

# No weekly numbers at all: say what to do.
r = subprocess.run([sys.executable, CARD, '--csv', os.path.join(tmp, 'nowhere'), '--no-png'], capture_output=True, text=True)
assert r.returncode != 0 and 'Run a nerf check first' in r.stderr, r.stderr

# A dry run of sharing gives the draft's address and touches neither the clipboard nor the browser.
out, notes, page = card('share', steady + [week(4, 8.1, 6.6, 10.0)], '--share', 'x', '--dry-run', '--text', 'my words & more')
assert out['compose_url'] == 'https://x.com/intent/post?text=my%20words%20%26%20more', out['compose_url']
assert 'copied' not in out and 'opened' not in out

print('nerf card: all checks passed')
