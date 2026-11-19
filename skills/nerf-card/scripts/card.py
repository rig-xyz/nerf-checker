"""Draw the nerf card: one shareable picture of the latest week's verdict, from the numbers nerf-check already wrote.

  card.py                    draw the card for the primary model's latest complete week
  card.py --model "Opus 5.5" another model that has rows in weekly_by_model.csv
  card.py --week 2026-10-26  the card as it stood that week (weeks after it are left out)
  card.py --share x          draw it, copy the picture to the clipboard and open a draft post (x, bluesky, linkedin,
                             threads). Nothing is posted: the person pastes the picture and presses Post.
  card.py --share x --dry-run   the same, but only print the draft's address

It reads <home>/csv/weekly.csv (see nerf-check), so it sees weekly aggregates only, never prompts. It writes
<home>/cards/nerf-card-<week>.html (one self-contained file) and, when a Chrome-family browser is installed, the same
card as a 2400x1350 PNG. It sends nothing anywhere.

The verdict compares the latest complete week's error share (prompts the next message had to correct) with the earlier
weeks, the way the nerf-check summary does:
  NERFED      the whole 95% interval sits above the highest earlier week
  SUS         the share is above the highest earlier week, but the interval reaches back into the earlier range
  BUFFED      the whole 95% interval sits below the lowest earlier week
  NOT NERFED  anything else
  TOO EARLY   fewer than 3 earlier weeks to compare with, or fewer than 100 judged prompts in the latest week
"""
import argparse, base64, csv, datetime as dt, html, json, os, shutil, statistics, subprocess, sys, tempfile, urllib.parse, webbrowser

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(SKILL, 'assets')
# The same folder nerf-check keeps its history in.
CLAUDE = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude')
HOME = os.path.expanduser(os.environ.get('NERF_CHECK_HOME') or os.path.join(CLAUDE, 'nerf-check'))

MIN_WEEKS, MIN_JUDGED, MIN_WEEK_JUDGED, MAX_WEEKS = 3, 100, 50, 10
REPO = 'https://github.com/rig-xyz/nerf-checker'

# Per verdict: the word, its colour, the ink on the badge, the badge's icon, and the size the word is set at.
LOOK = {
    'nerfed':     ('NERFED', '#ff6b5e', '#2a0906', 'M6.5 6.5l11 11M17.5 6.5l-11 11', 112),
    'sus':        ('SUS', '#f5b84a', '#2a1a02', 'M8.6 9.2a3.5 3.5 0 1 1 5.5 2.9c-1.1.8-2.1 1.5-2.1 3.1M12 18.6v.01', 132),
    'not_nerfed': ('NOT NERFED', '#4ade80', '#06240f', 'M5.5 12.5l4.3 4.3L18.5 7.5', 78),
    'buffed':     ('BUFFED', '#62a4f5', '#06162b', 'M6 12.5l6-6 6 6M6 18.5l6-6 6 6', 112),
    'early':      ('TOO EARLY', '#a3acb6', '#0b0d10', 'M6 12v.01M12 12v.01M18 12v.01', 84),
}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct(v):
    return f'{v:.1f}%'


def day(iso):
    d = dt.date.fromisoformat(iso)
    return f'{d.day} {d:%b}'


def load(csv_dir, model=None):
    """The weekly rows of one model, oldest first. No --model: the primary model, which is what weekly.csv holds."""
    name = 'weekly_by_model.csv' if model else 'weekly.csv'
    path = os.path.join(csv_dir, name)
    if not os.path.exists(path):
        sys.exit(f'No {name} in {csv_dir}. Run a nerf check first: this card is drawn from its weekly numbers.')
    rows = list(csv.DictReader(open(path, newline='')))
    if model:
        names = sorted({r['model'] for r in rows})
        rows = [r for r in rows if r['model'].lower() == model.lower()]
        if not rows:
            sys.exit(f'No weeks for "{model}". Models with rows: {", ".join(names) or "none"}.')
    if not rows:
        sys.exit(f'{name} has no complete week yet. Run a nerf check once a full week of work is on disk.')
    for r in rows:
        for k in ('n', 'judged', 'err', 'err_lo', 'err_hi', 'think_med', 'verify', 'apol', 'concede'):
            r[k] = num(r.get(k))
    return sorted(rows, key=lambda r: r['week_of'])


def read(rows):
    """The verdict for the latest week, and the figures the card quotes."""
    last, before = rows[-1], rows[:-1]
    earlier = [r for r in before if (r['judged'] or 0) >= MIN_WEEK_JUDGED and r['err'] is not None]
    v = dict(model=last.get('model') or 'the model', week=last['week_of'], err=last['err'], err_lo=last['err_lo'],
             err_hi=last['err_hi'], judged=int(last['judged'] or 0), n=int(last['n'] or 0), weeks=len(earlier),
             total=int(sum(r['n'] or 0 for r in rows)), all_weeks=len(rows))
    if len(earlier) < MIN_WEEKS or v['judged'] < MIN_JUDGED or None in (v['err'], v['err_lo'], v['err_hi']):
        v['key'] = 'early'
    else:
        v['lo'], v['hi'] = min(r['err'] for r in earlier), max(r['err'] for r in earlier)
        if v['err'] > v['hi']:
            v['key'] = 'nerfed' if v['err_lo'] > v['hi'] else 'sus'
        elif v['err'] < v['lo'] and v['err_hi'] < v['lo']:
            v['key'] = 'buffed'
        else:
            v['key'] = 'not_nerfed'
    # What changed around the model that week: the first thing to look at before blaming the model.
    v['changed'] = []
    if before:
        prev = before[-1]
        if last.get('cc_version') and prev.get('cc_version') and last['cc_version'] != prev['cc_version']:
            v['changed'].append(f"Claude Code went {prev['cc_version']} → {last['cc_version']}")
        if last.get('top_effort') and prev.get('top_effort') and last['top_effort'] != prev['top_effort']:
            v['changed'].append(f"effort went {prev['top_effort']} → {last['top_effort']}")
    for k in ('think_med', 'verify'):
        usual = [r[k] for r in earlier if r[k] is not None]
        v[k], v[k + '_usual'] = last[k], statistics.median(usual) if usual else None
    # nerf-check keeps these as keyword hits per 100 prompts; the card shows them as the week's count.
    for k, name in (('concede', 'conceded'), ('apol', 'sorry')):
        v[name] = None if last[k] is None else round(last[k] * (last['n'] or 0) / 100)
    return v


def sentence(v):
    """The one line under the verdict, in the first person: the person sharing it is the one speaking."""
    week = f"the week of {day(v['week'])}"
    if v['key'] == 'early':
        if v['judged'] < MIN_JUDGED:
            return f"Only <b>{v['judged']}</b> judged prompts in {week}. Too few to read anything into."
        return f"Only <b>{v['weeks']}</b> earlier week{'' if v['weeks'] == 1 else 's'} to compare with. Ask me again in a few."
    usual = f"my usual <b>{v['lo']:.1f}–{v['hi']:.1f}%</b>"
    share = f"<b>{pct(v['err'])}</b> of my prompts needed a correction in {week}"
    return {
        'nerfed': f"{share}. That is clear of {usual}, interval and all.",
        'sus': f"{share}, above {usual}. The interval still reaches back into that range, so it may be noise.",
        'buffed': f"Only {share}. That is clear below {usual}, interval and all.",
        'not_nerfed': f"{share}. That is inside {usual}.",
    }[v['key']]


def post_text(v):
    """A draft post to go with the picture. The person edits it; nothing here is sent by this script."""
    week = f"week of {day(v['week'])}"
    head = {
        'nerfed': f"Is {v['model']} nerfed? On my work, yes.",
        'sus': f"Is {v['model']} nerfed? Sus, but not proven.",
        'buffed': f"Is {v['model']} nerfed? The opposite, on my work.",
        'not_nerfed': f"Is {v['model']} nerfed? Not on my work.",
        'early': f"Is {v['model']} nerfed? Too early to say.",
    }[v['key']]
    if v['key'] == 'early':
        body = f"Not enough weeks of my own Claude Code work to compare yet ({week})."
    else:
        body = (f"{pct(v['err'])} of my prompts needed a correction in the {week}, "
                f"against my usual {v['lo']:.1f}–{v['hi']:.1f}%.")
    return f"{head} {body}\n\nMeasured on my own Claude Code transcripts with nerf-check by @riglabs_\n{REPO}"


def chart(rows, v, colour):
    """Dots and whiskers by week: the earlier weeks in grey, the latest in the verdict's colour, the usual range as a band."""
    rows = rows[-MAX_WEEKS:]
    W, H, L, R, T, B = 432, 252, 36, 14, 26, 26
    pw, ph = W - L - R, H - T - B
    errs = [r['err'] for r in rows if r['err'] is not None]
    top = max(errs + [v['err_hi'] or 0, v.get('hi') or 0]) * 1.12
    step = 5 if top <= 22 else 10 if top <= 45 else 25
    top = max(step * 2, step * -(-top // step))
    y = lambda p: T + ph * (1 - min(p, top) / top)
    x = lambda i: L + (i + 0.5) * pw / len(rows)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Share of prompts corrected, by week">']
    t = 0
    while t <= top:
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#ffffff{"2e" if t == 0 else "12"}"/>'
                 f'<text x="{L - 8}" y="{y(t) + 3.5:.1f}" text-anchor="end" font-size="10.5" fill="#8a92a0">{t:g}%</text>')
        t += step
    label = ''
    if 'lo' in v:
        o.append(f'<rect x="{L}" y="{y(v["hi"]):.1f}" width="{pw}" height="{max(2, y(v["lo"]) - y(v["hi"])):.1f}" rx="3" fill="#ffffff10"/>')
        # Drawn after the marks, with a halo in the panel's colour, so a whisker crossing it does not strike it through.
        label = (f'<text x="{L + 7}" y="{y(v["hi"]) - 6:.1f}" font-size="9.5" letter-spacing=".06em" fill="#8a92a0" '
                 f'stroke="#181c21" stroke-width="5" stroke-linejoin="round" paint-order="stroke">USUAL RANGE</text>')
    every = 2 if len(rows) > 7 else 1
    for i, r in enumerate(rows):
        if r['err'] is None:
            continue
        latest = i == len(rows) - 1
        c, cx = (colour, x(i)) if latest else ('#a3acb6', x(i))
        if r['err_lo'] is not None and r['err_hi'] is not None:
            o.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(r["err_hi"]):.1f}" y2="{y(r["err_lo"]):.1f}" stroke="{c}" '
                     f'stroke-opacity="{.9 if latest else .45}" stroke-width="2" stroke-linecap="round"/>')
        if latest:
            o.append(f'<circle cx="{cx:.1f}" cy="{y(r["err"]):.1f}" r="17" fill="{c}" fill-opacity=".16"/>'
                     f'<circle cx="{cx:.1f}" cy="{y(r["err"]):.1f}" r="7.5" fill="{c}" stroke="#14171b" stroke-width="2"/>')
            ly = max(12, y(r['err_hi'] if r['err_hi'] is not None else r['err']) - 9)
            o.append(f'<text x="{min(cx, W - R - 20):.1f}" y="{ly:.1f}" text-anchor="middle" font-size="13" font-weight="600" fill="#f3f5f7">{pct(r["err"])}</text>')
        else:
            o.append(f'<circle cx="{cx:.1f}" cy="{y(r["err"]):.1f}" r="4.5" fill="{c}" stroke="#14171b" stroke-width="1.5"/>')
        if latest or (len(rows) - 1 - i) % every == 0:
            o.append(f'<text x="{cx:.1f}" y="{H - 7}" text-anchor="middle" font-size="10.5" fill="{"#f3f5f7" if latest else "#8a92a0"}">{day(r["week_of"])}</text>')
    return ''.join(o) + label + '</svg>'


def tiles(v):
    def tile(label, value, unit, sub):
        return (f'<div class="stat"><span class="mono">{label}</span><span class="v">{value}'
                f'{f"<small>{unit}</small>" if unit else ""}</span><span class="s">{sub}</span></div>')

    def against(now, usual, points=False):
        # A share is compared in points, a count in percent: "+3% vs 71%" would read as either.
        if now is None or not usual:
            return 'no earlier weeks to compare'
        d = round(now - usual) if points else round(100 * (now - usual) / usual)
        was = f'{usual:,.0f}%' if points else f'{usual:,.0f}'
        return f'{"+" if d > 0 else ""}{d}{(" pt" if abs(d) == 1 else " pts") if points else "%"} vs my usual {was}' if d else f'same as my usual {was}'

    out = [tile('Corrected', '—' if v['err'] is None else f"{v['err']:.1f}", '%',
                f"95% interval {v['err_lo']:.1f}–{v['err_hi']:.1f}%" if v['err_lo'] is not None else 'no interval yet')]
    out.append(tile('Thinking per prompt', '—' if v['think_med'] is None else f"{v['think_med']:,.0f}", 'tokens',
                    against(v['think_med'], v['think_med_usual'])))
    out.append(tile('Checked its work', '—' if v['verify'] is None else f"{v['verify']:.0f}", '%',
                    'of code edits, ' + against(v['verify'], v['verify_usual'], points=True) if v['verify'] is not None else 'no code edits that week'))
    sorry = ('concession phrases, by keyword' if v['sorry'] is None else 'and never said sorry' if v['sorry'] == 0
             else 'and said sorry once' if v['sorry'] == 1 else f"and said sorry {v['sorry']} times")
    out.append(tile('Said “you’re right”', '—' if v['conceded'] is None else f"{v['conceded']:,}",
                    '' if v['conceded'] is None else 'time' if v['conceded'] == 1 else 'times', sorry))
    return ''.join(out)


def fonts():
    """The three faces, inlined, so the card is one file that looks the same on any machine."""
    faces = [('Geist', 'Geist-Variable.woff2', '100 900'), ('Geist Mono', 'GeistMono-Variable.woff2', '100 900'),
             ('Space Grotesk', 'space-grotesk-latin-wght-normal.woff2', '300 700')]
    out = []
    for family, name, weight in faces:
        data = base64.b64encode(open(os.path.join(ASSETS, 'fonts', name), 'rb').read()).decode()
        out.append(f"@font-face {{ font-family: '{family}'; src: url(data:font/woff2;base64,{data}) format('woff2'); font-weight: {weight}; }}")
    return '\n'.join(out)


def page(rows, v):
    word, colour, ink, icon, size = LOOK[v['key']]
    note = ''
    if v['changed'] and v['key'] in ('nerfed', 'sus', 'buffed'):
        what = ' and '.join(v['changed'])
        note = (f'<div class="note"><span class="mono">Before blaming the model</span>'
                f'<p><b>{html.escape(what[0].upper() + what[1:])}</b> that week. The harness changed too.</p></div>')
    fill = {
        'title': f"Nerf check: {v['model']}, week of {day(v['week'])}",
        'fonts': fonts(), 'status': colour, 'status_ink': ink, 'icon': icon, 'verdict': word, 'verdict_px': str(size),
        'verdict_key': v['key'],
        'pill': f"{html.escape(v['model'])} · week of {day(v['week'])} {v['week'][:4]}",
        'question': f"Is {html.escape(v['model'])} nerfed?",
        'line': sentence(v), 'note': note,
        'chart_title': 'Prompts my next message corrected · by week',
        'chart': chart(rows, v, colour), 'stats': tiles(v),
        'caveat': (f"{v['n']:,} of my own Claude Code prompts that week, {v['total']:,} over {v['all_weeks']} weeks. "
                   'One person, not a benchmark.'),
    }
    out = open(os.path.join(ASSETS, 'card.html')).read()
    for k, val in fill.items():
        out = out.replace('{{' + k + '}}', val)
    return out


def browser():
    """A Chrome-family browser that can take the picture headless, or None."""
    named = os.environ.get('NERF_CARD_BROWSER')
    if named:
        return named
    mac = '/Applications/{0}.app/Contents/MacOS/{0}'
    paths = [mac.format(n) for n in ('Google Chrome', 'Chromium', 'Microsoft Edge', 'Brave Browser')]
    paths += [os.path.expanduser('~' + p) for p in paths]
    for base in (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'), os.environ.get('LOCALAPPDATA')):
        if base:
            paths += [os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                      os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe')]
    for p in paths:
        if os.path.exists(p):
            return p
    for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge', 'brave-browser'):
        if shutil.which(n):
            return shutil.which(n)
    return None


def picture(page_path, png_path):
    exe = browser()
    if not exe:
        return 'no Chrome, Chromium, Edge or Brave found (set NERF_CARD_BROWSER to one)'
    with tempfile.TemporaryDirectory() as profile:
        cmd = [exe, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
               f'--user-data-dir={profile}', '--window-size=1200,675', '--force-device-scale-factor=2',
               '--virtual-time-budget=3000', f'--screenshot={png_path}', 'file://' + urllib.parse.quote(page_path)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f'{os.path.basename(exe)} could not take the picture: {e}'
    return None if os.path.exists(png_path) else f'{os.path.basename(exe)} wrote no picture'


def copy_picture(png_path):
    """Put the PNG on the clipboard, so it can be pasted into the draft post. True when it worked."""
    try:
        if sys.platform == 'darwin':
            script = f'set the clipboard to (read (POSIX file "{png_path}") as «class PNGf»)'
            return subprocess.run(['osascript', '-e', script], capture_output=True, timeout=20).returncode == 0
        if sys.platform.startswith('win'):
            ps = ('Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; '
                  f'[System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile("{png_path}"))')
            return subprocess.run(['powershell', '-NoProfile', '-STA', '-Command', ps], capture_output=True, timeout=20).returncode == 0
        for tool in (['wl-copy', '--type', 'image/png'], ['xclip', '-selection', 'clipboard', '-t', 'image/png']):
            if shutil.which(tool[0]):
                with open(png_path, 'rb') as f:
                    return subprocess.run(tool, stdin=f, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


# Where a draft post opens. Each takes the text; none takes a picture, which is why the picture goes on the clipboard.
COMPOSE = {
    'x': 'https://x.com/intent/post?text={}',
    'bluesky': 'https://bsky.app/intent/compose?text={}',
    'threads': 'https://www.threads.net/intent/post?text={}',
    'linkedin': 'https://www.linkedin.com/feed/?shareActive=true&text={}',
}


def main():
    ap = argparse.ArgumentParser(description='Draw the nerf card from the latest nerf-check numbers.')
    ap.add_argument('--model', help='a model with rows in weekly_by_model.csv (default: the primary model)')
    ap.add_argument('--week', help='draw the card as of this week (its Monday, YYYY-MM-DD) instead of the latest')
    ap.add_argument('--csv', default=os.path.join(HOME, 'csv'), help='folder holding weekly.csv')
    ap.add_argument('--out', default=os.path.join(HOME, 'cards'), help='folder to write the card into')
    ap.add_argument('--no-png', action='store_true', help='write the HTML only')
    ap.add_argument('--share', choices=sorted(COMPOSE), help='copy the picture and open a draft post there')
    ap.add_argument('--text', help='the draft post text for --share (default: the suggested one)')
    ap.add_argument('--dry-run', action='store_true', help='with --share: print the draft address, copy and open nothing')
    a = ap.parse_args()

    rows = load(a.csv, a.model)
    if a.week:
        if a.week not in [r['week_of'] for r in rows]:
            sys.exit(f"No week starting {a.week}. Weeks on file: {', '.join(r['week_of'] for r in rows)}.")
        rows = [r for r in rows if r['week_of'] <= a.week]
    v = read(rows)
    os.makedirs(a.out, exist_ok=True)
    slug = ''.join(c if c.isalnum() else '-' for c in v['model'].lower()).strip('-')
    stem = os.path.abspath(os.path.join(a.out, f"nerf-card-{slug}-{v['week']}"))
    with open(stem + '.html', 'w') as f:
        f.write(page(rows, v))
    out = dict(verdict=LOOK[v['key']][0], model=v['model'], week_of=v['week'], err=v['err'], err_lo=v['err_lo'],
               err_hi=v['err_hi'], usual=[v.get('lo'), v.get('hi')], judged=v['judged'], earlier_weeks=v['weeks'],
               said_youre_right=v['conceded'], said_sorry=v['sorry'],
               changed=v['changed'], html=stem + '.html', png=None, post_text=a.text or post_text(v))
    if not a.no_png:
        problem = picture(stem + '.html', stem + '.png')
        if problem:
            print(f'NOTE: no PNG: {problem}. Open the HTML and screenshot it at 1200x675.', file=sys.stderr)
        else:
            out['png'] = stem + '.png'
    age = (dt.date.today() - dt.date.fromisoformat(v['week'])).days
    if age > 13 and not a.week:
        print(f"NOTE: the latest complete week on file starts {v['week']}, {age} days ago. Run a nerf check to refresh it.", file=sys.stderr)
    if a.share:
        out['compose_url'] = COMPOSE[a.share].format(urllib.parse.quote(out['post_text']))
        if not a.dry_run:
            if not out['png']:
                sys.exit('Nothing to share: there is no PNG.')
            out['copied'] = copy_picture(out['png'])
            out['opened'] = bool(webbrowser.open(out['compose_url']))
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
