"""Where a workspace's pipeline files live: the one place that reads config paths.vault.

A workspace made by /setup is its own vault: Pipeline/ (queue, state, specs) and Workflow/ (the application folders)
sit inside it, and its config has no paths.vault. A workspace migrated from the original pipeline (engine.migrate)
names that pipeline's folder in paths.vault. Older /setup runs wrote paths.vault as the workspace itself, which
resolves the same way.
"""
import os

READY = os.path.join('Workflow', '02-Ready to Apply')


def _cfg(ws, cfg):
    if cfg is not None:
        return cfg
    from .profile import load_config
    p = os.path.join(os.path.expanduser(ws), 'config.json')
    return load_config(p) if os.path.exists(p) else {}


def named(cfg):
    """The vault config names (expanded), or None when the workspace is its own vault."""
    v = ((cfg or {}).get('paths') or {}).get('vault')
    return os.path.expanduser(v) if v else None


def vault(ws, cfg=None):
    """config paths.vault, else the workspace itself. Pass cfg when it is already loaded."""
    return named(_cfg(ws, cfg)) or os.path.expanduser(ws)


def pipeline(ws, cfg=None):
    return os.path.join(vault(ws, cfg), 'Pipeline')


def queue(ws, cfg=None):
    return os.path.join(pipeline(ws, cfg), 'queue')


def ready(ws, cfg=None):
    return os.path.join(vault(ws, cfg), READY)


SCRATCH_KINDS = ('tailor-brief', 'tailor-reply', 'spec', 'draft-brief', 'draft', 'review-packet', 'review-edits',
                 'reads-brief', 'reads-reply', 'note-packet', 'note', 'materials-brief', 'materials-reply', 'fill-plan')


def scratch(ws, kind, key, date=None, cfg=None):
    """The default file for one brief, packet or reply: <pipeline>/scratch/<date>/<kind>-<key>.json (folder made).
    Every command that writes one takes --out and falls back to this, then prints the path."""
    import datetime, re
    if kind not in SCRATCH_KINDS:
        raise ValueError(f'unknown scratch kind {kind!r}')
    day = date or datetime.date.today().isoformat()
    folder = os.path.join(pipeline(ws, cfg), 'scratch', day)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{kind}-{re.sub(r'[^A-Za-z0-9._-]+', '_', str(key))}.json")
