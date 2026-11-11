"""Rule checks on a draft text before the user sends it: `gmh check-text <kind> <file> [--id <id>]`.

Kinds: followup, thank-you, note, cover, answer. Checks, by rule (no model):
  - em or en dashes;
  - numbers not found in the candidate's facts (master-resume.md plus, with --id, the materials submitted for that
    application and its posting);
  - lines that volunteer a gap or weakness (redline.GAP_RE);
  - the kind's length limit: note 300 characters (linkedin.NOTE_LIMIT), follow-up 150 words, thank-you 200 words,
    cover letter 380 words (the redline check); an answer has no fixed limit.
Prints `ok`, or one line per problem. Exit 0 ok, 1 problems, 2 bad usage. Reads only; sends nothing.
HTML comments (<!-- -->) are ignored, so a filled template can keep its instructions.
"""
import argparse, os, re, sys
from . import linkedin, tracker
from .redline import DASH_RE, numbers, volunteered_gaps

KINDS = ('followup', 'thank-you', 'note', 'cover', 'answer')
WORD_LIMITS = {'followup': 150, 'thank-you': 200, 'cover': 380}


def strip_comments(text):
    return re.sub(r'<!--.*?-->', '', text or '', flags=re.S)


def check(kind, text, facts='', materials='', posting=''):
    """Problem lines for one draft (empty list: ok)."""
    text = strip_comments(text).strip()
    if not text:
        return ['empty text']
    problems = []
    m = DASH_RE.search(text)
    if m:
        problems.append(f'em or en dash ("{m.group(0)}")')
    bad = sorted(numbers(text) - numbers(facts) - numbers(materials) - numbers(posting))
    if bad:
        problems.append('number not in the resume or submitted materials: ' + ', '.join(bad))
    gaps = volunteered_gaps(text)
    if gaps:
        problems.append('volunteers a gap: ' + ', '.join(sorted(set(g.strip() for g in gaps))))
    if kind == 'note':
        n = len(text)
        if n > linkedin.NOTE_LIMIT:
            problems.append(f'{n} characters: {n - linkedin.NOTE_LIMIT} over the {linkedin.NOTE_LIMIT} limit')
    elif kind in WORD_LIMITS:
        words = len(text.split())
        if words > WORD_LIMITS[kind]:
            problems.append(f'{words} words: {words - WORD_LIMITS[kind]} over the {WORD_LIMITS[kind]} word limit'
                            + (' (may run past one page)' if kind == 'cover' else ''))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gmh check-text', description=__doc__.split('\n')[0])
    ap.add_argument('kind', choices=KINDS)
    ap.add_argument('file')
    ap.add_argument('--id', help="tracker id or job_key: also allow numbers in that application's submitted materials")
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'))
    a = ap.parse_args(argv)
    if not a.workspace:
        ap.error('--workspace is required (or set GMH_WORKSPACE)')
    ws = os.path.expanduser(a.workspace)
    try:
        with open(a.file, encoding='utf-8') as fh:
            text = fh.read()
    except OSError as e:
        sys.exit(f'cannot read {a.file}: {e.strerror}')
    mats = posting = ''
    if a.id:
        try:
            row = tracker.find(tracker.read(tracker.path_of(ws)), a.id)
        except KeyError as e:
            sys.exit(e.args[0])
        facts, mats, posting, _ = linkedin.sources(ws, row)
    else:
        paths = (os.path.join(ws, 'master-resume.md'), os.path.join(linkedin._vault(ws), 'master-resume.md'))
        facts = next((linkedin._read(p) for p in paths if os.path.exists(p)), '')
    problems = check(a.kind, text, facts, mats, posting)
    if not facts and not mats:
        problems.append('no master-resume.md or submitted materials found: numbers cannot be checked')
    print('\n'.join(problems) if problems else 'ok')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
