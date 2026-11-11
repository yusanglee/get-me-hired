"""Where a developer's private workspace lives, for the few tests that need real local data.

GMH_PRIVATE_WORKSPACE names it. When that variable is unset, a single folder under <repo>/workspace/ that holds a
profile.yaml is used, so a checkout with one private workspace needs no setup. Otherwise there is none and the tests
that need it skip."""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def private_workspace():
    env = os.environ.get('GMH_PRIVATE_WORKSPACE')
    if env is not None:
        return env if os.path.isdir(env) else None
    root = os.path.join(REPO, 'workspace')
    found = [os.path.join(root, d) for d in sorted(os.listdir(root))
             if os.path.exists(os.path.join(root, d, 'profile.yaml'))] if os.path.isdir(root) else []
    return found[0] if len(found) == 1 else None
