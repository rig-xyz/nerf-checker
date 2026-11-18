"""Probes that need a session's history, not just one prompt: re-reads, and sessions that were started over.

Both work on text that is only ever held in memory while a transcript is being read. What reaches the store is counts
and flags.
"""
import collections, re

# Re-reads: the model reading lines of a file it has already read, with the file untouched in between. Reads are taken
# from the Read tool and from the shell (cat, nl, less, sed -n, head). Logs, temp files and images change under the
# model, so they don't count.
VOLATILE = re.compile(r'/tmp/|/dev/|scratchpad|\.(log|out|png|jpe?g|gif|webp|svg|pdf|lock)\b', re.I)
_PATH = r"""(?P<q>["']?)(?P<path>[\w@~./+-]*[\w-]\.\w{1,6})(?P=q)"""
_SED = re.compile(r"""sed\s+-n\s+["']?(?P<lo>\d+),(?P<hi>\d+)p["']?\s+""" + _PATH)
_HEAD = re.compile(r"head\s+(?:-n\s*)?-?(?P<hi>\d+)\s+" + _PATH)
_WHOLE = re.compile(r"(?:^|[;&|(]\s*)(?:cat|nl|less)\s+(?:-\w+\s+)*" + _PATH
                    + r"""\s*(?:\|\s*(?:head\s+(?:-n\s*)?-?(?P<head>\d+)|sed\s+-n\s+["']?(?P<lo>\d+),(?P<hi>\d+)p))?""")
END = 10 ** 9   # "to the end of the file"


def shell_reads(cmd):
    """(file, first line, last line) for each stretch of a file a shell command prints."""
    out = [(m['path'], int(m['lo']), int(m['hi'])) for m in _SED.finditer(cmd)]
    out += [(m['path'], 1, int(m['hi'])) for m in _HEAD.finditer(cmd)]
    for m in _WHOLE.finditer(cmd):
        lo, hi = (1, int(m['head'])) if m['head'] else (int(m['lo']), int(m['hi'])) if m['lo'] else (1, END)
        out.append((m['path'], lo, hi))
    return out


class Reads:
    """Which lines of which files the model has read in a session, to spot it reading the same lines again."""

    def __init__(self):
        self.seen = collections.defaultdict(list)   # file -> [(context window, first line, last line)]
        self.window = 0                             # goes up at each compaction

    @staticmethod
    def name(path):
        return '/'.join(path.replace('~', '').strip('/').split('/')[-2:])   # src/a.py and /repo/src/a.py are one file

    @staticmethod
    def covered(spans, lo, hi):
        got, at = 0, lo
        for a, b in sorted(spans):
            a, b = max(a, at), min(b, hi)
            if b >= a:
                got += b - a + 1
                at = b + 1
        return got / (hi - lo + 1)

    def read(self, path, lo, hi, turn):
        if VOLATILE.search(path) or hi < lo:
            return
        f = self.name(path)
        turn['file_reads'] += 1
        if self.covered([(a, b) for w, a, b in self.seen[f] if w == self.window], lo, hi) >= 0.8:
            turn['reread'] += 1           # those lines are already in this context window
        elif self.covered([(a, b) for _, a, b in self.seen[f]], lo, hi) >= 0.8:
            turn['reread_compact'] += 1   # read before a compaction: reading them again is what the compaction cost
        self.seen[f].append((self.window, lo, hi))

    def changed(self, names):
        """Files were edited: reading them again is fair."""
        for f in [f for f in self.seen if f.split('/')[-1] in names]:
            del self.seen[f]

    def forget(self):
        """The working tree was rewritten under the model (a checkout, a rebase): everything is fair to read again."""
        self.seen.clear()


# Started over: a new session whose first prompt asks for much the same as the one before it in that folder.
_WORD = re.compile(r"[a-z0-9_']{4,}")
_COMMON = set('this that with from have will would could should please they them then than there here what when where '
              'which your yours about into just like make sure need want also some more does done only still been were '
              'over after before these those their each'.split())


def words(text):
    return {w for w in _WORD.findall(text[:4000].lower()) if w not in _COMMON}


def same_ask(now, before):
    """Two prompts ask for much the same thing: most of their words are shared, or the earlier one sits inside the new
    one. Identical wording is a template or a script, not a person starting over, so it does not count."""
    if len(now) < 8 or len(before) < 8 or now == before:
        return False
    both = len(now & before)
    return both / len(now | before) >= 0.5 or both / len(before) >= 0.6
