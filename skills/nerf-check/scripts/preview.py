"""Write a standalone preview of the dashboard to <home>/preview.html, for when no hosted dashboard is available.

It wraps assets/dashboard.html with the CSVs from <home>/csv and a small stand-in for the dashboard runtime, so the
same page code draws locally. Opens in any browser; it loads d3 from cdnjs, so it needs a network connection.
"""
import json, os
from common import HOME, CSV

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASETS = json.load(open(os.path.join(SKILL, 'assets', 'datasets.json')))
page = open(os.path.join(SKILL, 'assets', 'dashboard.html')).read()
raw = {}
for ds_id, doc in DATASETS.items():
    p = os.path.join(CSV, doc['source']['name'])
    raw[ds_id] = open(p).read() if os.path.exists(p) else ''

STUB = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Claude Code nerf check</title>
<style>
:root{--color-fg:#1f1e1d;--color-fg-muted:#6b6a68;--color-bg:#fff;--color-panel:#f7f6f3;--color-border-line:#e3e1dc;--cds-text-secondary:#6b6a68;--cds-chart-axis:#bdbbb5;--cds-chart-grid:#eceae5;--cds-surface-popover:#fff;--cds-border:#d5d3cd;--cds-shadow-popover:0 4px 14px rgba(0,0,0,.12);--cds-gap-xs:4px;--cds-gap-sm:8px;--cds-gap-md:12px;--cds-gap-xl:28px;--cds-pad-lg:16px;--cds-pad-md:12px;--cds-radius:8px;--cds-font-size-caption:12px;--cds-font-size-body:14px;--cds-font-size-heading:17px;--cds-font-size-title:28px;--cds-font-weight-medium:600;--font-anthropic-sans:system-ui,sans-serif;--font-anthropic-serif:Georgia,serif}
@media (prefers-color-scheme: dark){:root{--color-fg:#eceae5;--color-fg-muted:#a3a19c;--color-bg:#1c1b1a;--color-panel:#262523;--color-border-line:#3a3936;--cds-text-secondary:#a3a19c;--cds-chart-axis:#5a5955;--cds-chart-grid:#33322f;--cds-surface-popover:#2b2a28;--cds-border:#45443f}}
body{font:14px/1.45 var(--font-anthropic-sans);margin:0;padding:16px;background:var(--color-bg);color:var(--color-fg)}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script>
const RAW = __RAW__;
const SRC = {}; for (const k in RAW) SRC[k] = d3.csvParse(RAW[k].trim());
const calcs = {}, draws = [], ons = [];
window.dash = {
  colors: ['#c96442', '#3b6fb6', '#4a9c6d', '#9b59b6', '#b8860b', '#2a9d9d'],
  data(id) {
    if (SRC[id]) return { status: 'ok', data: SRC[id] };
    if (calcs[id]) { try { return { status: 'ok', data: calcs[id].fn(...calcs[id].inputs.map((i) => dash.data(i).data)) }; } catch (e) { return { status: 'error', data: null, message: e.message }; } }
    return { status: 'missing', data: [] };
  },
  calc(id, o) { calcs[id] = o; }, draw(name, fn) { draws.push([name, fn]); }, onData(fn) { ons.push(fn); },
  params() { return {}; }, setParams() {}, resetParams() {}, setLink() {}, refresh() {},
};
const run = () => {
  ons.forEach((f) => f());
  draws.forEach(([n, f]) => document.querySelectorAll('[data-draw="' + n + '"]').forEach((el) => { if (!el.closest('[hidden]')) f(el); }));
};
window.addEventListener('load', run);
let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(run, 150); });
</script>
<div id="dash-root">__PAGE__</div>
'''
out = os.path.join(HOME, 'preview.html')
open(out, 'w').write(STUB.replace('__RAW__', json.dumps(raw).replace('</', '<\\/')).replace('__PAGE__', page))
print(out)
