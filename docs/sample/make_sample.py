"""Made-up numbers for the README screenshots and the "try the page" sample. Not measurements of any model."""
import csv, os, random, datetime as dt, sys
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
rng = random.Random(7)
COLS = ['n', 'judged', 'err', 'err_lo', 'err_hi', 'redirect', 'interrupt', 'apol', 'concede', 'shortcut', 'handback', 'tool_err', 'edit_fail',
        'read_edit', 'think_med', 'think_p75', 'think_per_call', 'zero_think', 'out_med', 'tools_med', 'ctx_med_k', 'compaction', 'api_err',
        'start_ctx_k', 'reread', 'reread_compact', 'verify', 'rejected', 'fallback', 'cache_hit', 'cc_version', 'cc_versions', 'top_effort']
A, B = 'Model A', 'Model B'
weeks = [(dt.date(2026, 9, 21) + dt.timedelta(weeks=i)).isoformat() for i in range(8)]

def row(n, err, think=1500, effort='high', version='2.4.10', versions=1, compaction=3.0, reread=2.4, reread_c=0.5, verify=74, start=62, cache=98.7, ctx=180, fallback=0.0):
    judged = int(n * rng.uniform(.92, .97)); w = 38 / (judged ** .5) * rng.uniform(.9, 1.5)
    j = lambda v, s: round(v * rng.uniform(1 - s, 1 + s), 1)
    return dict(n=n, judged=judged, err=err, err_lo=round(max(0, err - w * .8), 1), err_hi=round(err + w, 1), redirect=j(27, .25), interrupt=j(1.1, .5),
                apol=j(.7, .5), concede=j(6, .3), shortcut=j(5.5, .3), handback=j(1.4, .5), tool_err=round(rng.uniform(1.9, 2.8), 2),
                edit_fail=round(rng.uniform(.1, .5), 2), read_edit=round(rng.uniform(.8, 1.5), 2), think_med=int(think * rng.uniform(.93, 1.07)),
                think_p75=int(think * rng.uniform(2.3, 2.8)), think_per_call=int(think / rng.uniform(5.5, 7)), zero_think=j(3.4, .25), out_med=int(rng.uniform(4300, 6200)),
                tools_med=rng.choice([5, 6, 7, 8]), ctx_med_k=j(ctx, .12), compaction=j(compaction, .15), api_err=j(.8, .6), start_ctx_k=j(start, .04),
                reread=round(reread * rng.uniform(.85, 1.15), 2), reread_compact=round(reread_c * rng.uniform(.8, 1.2), 2), verify=j(verify, .05),
                rejected=j(1.6, .5), fallback=fallback, cache_hit=round(cache * rng.uniform(.997, 1.003), 1), cc_version=version, cc_versions=versions, top_effort=effort)

def write(name, head, rows):
    with open(os.path.join(out, name), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n'); w.writerow(head); w.writerows(rows)

# The story the sample tells: week 6 looks like a nerf, and the harness table shows why. A client release that week
# dropped the default effort to medium and doubled the context a fresh session starts with.
plan = [(412, 8.3, {}), (538, 9.1, {}), (601, 7.6, {'version': '2.4.12', 'versions': 2}), (577, 8.8, {'version': '2.4.12'}), (489, 8.1, {'version': '2.4.12'}),
        (533, 14.9, {'version': '2.5.0', 'versions': 2, 'effort': 'medium', 'think': 820, 'start': 118, 'compaction': 7.8, 'reread': 3.9, 'reread_c': 2.1, 'verify': 61, 'cache': 93.5, 'ctx': 260}),
        (458, 9.4, {'version': '2.5.1', 'versions': 2, 'start': 66, 'compaction': 3.6}), (396, 8.7, {'version': '2.5.1', 'start': 64})]
weekly = [row(n, e, **kw) for n, e, kw in plan]
write('weekly.csv', ['week_of'] + COLS + ['model'], [[w] + [r[c] for c in COLS] + [A] for w, r in zip(weeks, weekly)])
eff = []
for w, (n, e, kw) in zip(weeks, plan):
    med = .85 if kw.get('effort') == 'medium' else .18
    for name, share, shift in (('medium', med, 2.6), ('high', 1 - med, -.9)):
        if n * share >= 40:
            r = row(int(n * share), round(e + shift, 1), **dict(kw, effort=name, think=900 if name == 'medium' else 1650))
            eff.append([w, name] + [r[c] for c in COLS] + [A])
write('weekly_by_effort.csv', ['week_of', 'effort'] + COLS + ['model'], eff)
ctx = [('<50k', 310, 5.1, 30), ('50-150k', 1240, 7.2, 100), ('150-300k', 1120, 9.0, 220), ('300-600k', 890, 11.8, 420), ('600k+', 444, 14.6, 710)]
write('by_context.csv', ['context'] + COLS + ['model'], [[b] + [row(n, e, ctx=c)[k] for k in COLS] + [A] for b, n, e, c in ctx])
write('error_types.csv', ['error_type', 'turns', 'model'], [[t, n, A] for t, n in (('broken_or_buggy', 148), ('misunderstood', 96), ('incomplete_or_lazy', 51), ('false_claim', 38), ('ignored_instruction', 33), ('overreach', 12))])
models = [[w, A] + [r[c] for c in COLS] for w, r in zip(weeks, weekly)]
for w, n, e in zip(weeks[5:], (64, 151, 188), (10.9, 8.2, 7.9)):
    r = row(n, e, think=2100, version='2.5.1' if w != weeks[5] else '2.5.0', start=65)
    models.append([w, B] + [r[c] for c in COLS])
write('weekly_by_model.csv', ['week_of', 'model'] + COLS, sorted(models))
prs = [[w, A, p, c, cm, 0, mj, cm - mj, 0, ci, ok] for w, (p, c, cm, mj, ci, ok) in zip(weeks, [(9, 4, 11, 3, 8, 7), (14, 6, 19, 6, 12, 11), (17, 7, 22, 6, 15, 14), (15, 6, 17, 5, 13, 12), (12, 5, 14, 4, 11, 10), (16, 10, 41, 15, 14, 9), (11, 4, 12, 3, 10, 9), (10, 4, 10, 3, 9, 9)])]
prs += [[w, B, p, c, cm, 0, mj, cm - mj, 0, ci, ok] for w, (p, c, cm, mj, ci, ok) in zip(weeks[5:], [(2, 1, 2, 0, 2, 2), (5, 2, 4, 1, 5, 5), (7, 2, 5, 1, 6, 6)])]
write('prs_by_model.csv', ['week_of', 'model', 'prs', 'cr_prs', 'cr_comments', 'cr_critical', 'cr_major', 'cr_minor', 'cr_other', 'ci_prs', 'ci_pass'], sorted(prs))
rv = [[w, A, p, rc, cl, sm, bg] for w, (p, rc, cl, sm, bg) in zip(weeks, [(8, 1, 5, 2, 0), (13, 2, 8, 2, 1), (16, 2, 10, 3, 1), (14, 2, 9, 2, 1), (11, 1, 7, 2, 1), (15, 4, 5, 3, 3), (10, 1, 7, 2, 0), (9, 1, 6, 2, 0)])]
rv += [[w, B, p, rc, cl, sm, bg] for w, (p, rc, cl, sm, bg) in zip(weeks[5:], [(2, 0, 2, 0, 0), (5, 1, 3, 1, 0), (6, 1, 4, 1, 0)])]
write('reviews_by_model.csv', ['week_of', 'model', 'passes', 'recheck', 'clean', 'small', 'big'], sorted(rv))
sw = [(31, 0, '', 0, 0, '', 1, 0), (38, 0, '', 0, 0, '', 0, 0), (44, 0, '', 0, 0, '', 1, 1), (41, 0, '', 0, 0, '', 0, 0), (36, 0, '', 0, 0, '', 1, 0), (39, 5, B, 3, 4, 412.5, 4, 3), (33, 1, B, 0, 0, 228.1, 1, 0), (29, 0, '', 0, 0, '', 0, 0)]
write('switches.csv', ['week_of', 'sessions', 'switches', 'per_100_sessions', 'to', 'frustrated', 'compacted_before', 'ctx_at_switch_k', 'model', 'restarts', 'retries'],
      [[w, s, n, round(100 * n / s, 1), to, fr, cb, cx, A, rs, rt] for w, (s, n, to, fr, cb, cx, rs, rt) in zip(weeks, sw)])
