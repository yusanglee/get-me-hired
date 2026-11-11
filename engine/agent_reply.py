"""gmh reply: save a helper agent's JSON reply to a file without the session typing it out again.

    gmh reply <agent output file> <out.json>     the agent's last message, its JSON checked, saved to out.json

The agent output file is what the tool gives for a finished background agent: in Claude Code, the task
notification's <output-file> (the agent's transcript, one JSON event per line). A plain file holding the reply text
works too (any tool: save the agent's reply as it came, then run this to check and normalize it). The reply may be
bare JSON or one ```json fenced block. Prints `saved <out> (<what>)`; exit 1 with the reason when there is no JSON
reply (the agent failed or is still running: nothing is written).
"""
import argparse, json, os, re, sys

FENCE = re.compile(r'```(?:json)?\s*\n?(.*?)```', re.S)


def _texts(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(x.get('text', '') for x in content if isinstance(x, dict) and x.get('type') == 'text')
    return ''


def last_message(path):
    """The agent's last non-empty assistant text from a transcript (JSON lines), or the whole file when it isn't one."""
    with open(path, encoding='utf-8') as fh:
        raw = fh.read()
    last, events = None, 0
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get('message') if isinstance(ev, dict) else None
        if not isinstance(msg, dict) or 'role' not in msg:
            continue
        events += 1
        if msg.get('role') == 'assistant':
            t = _texts(msg.get('content'))
            if t.strip():
                last = t
    return last if events else raw


def parse_reply(text):
    """The reply's JSON: the text itself, else its last fenced block, else from the first { or [ to the last } or ]."""
    t = (text or '').strip()
    candidates = [t] + list(reversed(FENCE.findall(t)))
    starts = [i for i in (t.find('{'), t.find('[')) if i >= 0]
    if starts:
        s = min(starts)
        e = max(t.rfind('}'), t.rfind(']'))
        if e > s:
            candidates.append(t[s:e + 1])
    for c in candidates:
        try:
            return json.loads(c.strip())
        except ValueError:
            continue
    raise ValueError('no JSON reply in the agent output' + (f': it ends "{t[-120:]}"' if t else ' (empty)'))


def describe(obj):
    if isinstance(obj, dict):
        bits = [f'{k}: {len(v)}' for k, v in obj.items() if isinstance(v, list)]
        return ', '.join(bits) or f"{len(obj)} keys"
    if isinstance(obj, list):
        return f'{len(obj)} items'
    return type(obj).__name__


def save(src, out):
    if not os.path.exists(src):
        raise ValueError(f'no such file: {src}')
    obj = parse_reply(last_message(src))
    d = os.path.dirname(os.path.abspath(out))
    os.makedirs(d, exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    return obj


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gmh reply', description=__doc__.split('\n\n')[0])
    ap.add_argument('output', help="the agent's output file (Claude Code: the task notification's output-file)")
    ap.add_argument('out', help='where to save the reply JSON')
    a = ap.parse_args(argv)
    try:
        obj = save(os.path.expanduser(a.output), os.path.expanduser(a.out))
    except (OSError, ValueError) as e:
        sys.exit(f'nothing saved: {e}')
    print(f'saved {a.out} ({describe(obj)})')


if __name__ == '__main__':
    main()
