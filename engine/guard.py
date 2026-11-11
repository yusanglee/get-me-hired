"""Run third-party posting text through the vendored posting_guard before any LLM reads it."""
from .vendor.posting_guard import guard


def clean_posting(p):
    """Clean p['description'] in place. Returns the findings; p['guard'] holds the one-line verdict."""
    text, findings = guard(p.get('description') or '', 'text')
    p['description'] = text
    p['guard'] = findings['verdict']
    return findings


def flagged(p):
    return '⚠' in (p.get('guard') or '')
