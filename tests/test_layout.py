"""engine.layout is the one place that reads config paths.vault. A workspace from today's /setup has no paths.vault;
one from an earlier /setup has paths.vault set to the workspace itself; a migrated one names another
folder. The first two must resolve every folder the same way. Fictional workspace (Jordan Rivera)."""
import datetime, json, os, shutil, tempfile, unittest

from engine import applied, design_editor, home, layout, linkedin, redline, setup, stages, tracker


def snapshot(ws):
    """Every folder the commands resolve for this workspace."""
    cfg = json.load(open(os.path.join(ws, 'config.json'), encoding='utf-8'))
    ctx = stages.Ctx(ws)
    links = {x['label']: x['target'] for x in home.data(ws, datetime.date(2026, 10, 31))['links']}
    return {'vault': layout.vault(ws), 'pipeline': layout.pipeline(ws), 'queue': layout.queue(ws),
            'ready': layout.ready(ws), 'tracker.vault_of': tracker.vault_of(ws), 'linkedin': linkedin._vault(ws),
            'redline': redline.vault_spec(ws, 'none')[0], 'stages': (ctx.vault, ctx.P, ctx.ready),
            'home links': links, 'design sources': design_editor.resume_sources(ws, cfg),
            'queues': applied.queues(ws), 'legacy': tracker.legacy_applied(cfg)}


class Layout(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='gmh-layout-')
        self.addCleanup(shutil.rmtree, self.root, True)
        self.ws = os.path.join(self.root, 'Jordan Rivera search')
        setup.init(self.ws, name='Jordan Rivera')
        open(os.path.join(self.ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write(
            'identity:\n  first_name: Jordan\n  last_name: Rivera\n  email: jordan@example.com\n')
        folder = os.path.join(self.ws, layout.READY, 'Brightwater - PM')
        os.makedirs(folder)
        open(os.path.join(folder, 'resume_brightwater.json'), 'w', encoding='utf-8', newline='\n').write('{}')
        q = layout.queue(self.ws)
        os.makedirs(q, exist_ok=True)
        open(os.path.join(q, 'reviewed-2026-10-30.csv'), 'w', encoding='utf-8', newline='\n').write('id,company,call\ngh-a,Brightwater,apply\n')
        open(os.path.join(q, 'review-2026-10-30.html'), 'w', encoding='utf-8', newline='\n').close()

    def _set_vault(self, value):
        p = os.path.join(self.ws, 'config.json')
        cfg = json.load(open(p, encoding='utf-8'))
        cfg['paths']['vault'] = value
        json.dump(cfg, open(p, 'w', encoding='utf-8', newline='\n'))

    def test_new_setup_has_no_vault_and_uses_the_workspace(self):
        self.assertNotIn('vault', json.load(open(os.path.join(self.ws, 'config.json'), encoding='utf-8'))['paths'])
        self.assertEqual(layout.vault(self.ws), self.ws)
        self.assertEqual(layout.ready(self.ws), os.path.join(self.ws, 'Workflow', '02-Ready to Apply'))

    def test_earlier_setup_config_resolves_the_same(self):
        """An earlier setup's workspace: paths.vault is the workspace itself. Same folders as a new workspace."""
        fresh = snapshot(self.ws)
        self._set_vault(self.ws)
        self.assertEqual(snapshot(self.ws), fresh)
        self.assertTrue(fresh['design sources'], 'built resumes in Workflow are found without paths.vault')
        self.assertTrue(fresh['queues'])

    def test_migrated_vault_elsewhere(self):
        other = os.path.join(self.root, 'Old Pipeline')
        os.makedirs(os.path.join(other, 'Pipeline', 'state'))
        open(os.path.join(other, 'Pipeline', 'state', 'applied.csv'), 'w', encoding='utf-8', newline='\n').write('id\n')
        self._set_vault(other)
        cfg = json.load(open(os.path.join(self.ws, 'config.json'), encoding='utf-8'))
        self.assertEqual(layout.vault(self.ws), other)
        self.assertEqual(stages.Ctx(self.ws).P, os.path.join(other, 'Pipeline'))
        self.assertEqual(tracker.legacy_applied(cfg), [os.path.join(other, 'Pipeline', 'state', 'applied.csv')])
        self.assertEqual(applied.queues(self.ws), [])  # the queue now lives in the other folder

    def test_tilde_is_expanded(self):
        cfg = {'paths': {'vault': '~/gmh-vault'}}
        self.assertEqual(layout.vault('/w', cfg), os.path.expanduser('~/gmh-vault'))
        self.assertEqual(layout.vault('/w', {}), '/w')
        self.assertIsNone(layout.named({'paths': {'vault': ''}}))


class Scratch(unittest.TestCase):
    def test_default_path_per_kind_and_key(self):
        import tempfile
        from engine import layout
        with tempfile.TemporaryDirectory() as ws:
            p = layout.scratch(ws, 'tailor-brief', 'gh-acme/123', date='2026-11-09', cfg={})
            self.assertEqual(p, os.path.join(ws, 'Pipeline', 'scratch', '2026-11-09', 'tailor-brief-gh-acme_123.json'))
            self.assertTrue(os.path.isdir(os.path.dirname(p)))
            with self.assertRaises(ValueError):
                layout.scratch(ws, 'nope', 'x', cfg={})


if __name__ == '__main__':
    unittest.main()
