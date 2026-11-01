"""Static UI contract checks; not visual/browser acceptance tests."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.guide_targets = []
        self.tabs = []
        self.copy_predecessors = []
        self.previous_end = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if 'data-tab' in attrs:
            self.tabs.append(attrs['data-tab'])
        if 'data-open-guide' in attrs:
            self.guide_targets.append(attrs['data-open-guide'])
        if 'copy-command' in attrs.get('class', '').split():
            self.copy_predecessors.append(self.previous_end)

    def handle_endtag(self, tag):
        self.previous_end = tag


class GuideTests(unittest.TestCase):
    def test_guide_targets_exist_and_ids_unique(self):
        tree = Elements()
        tree.feed((ROOT / 'dashboard/index.html').read_text())
        self.assertEqual(len(tree.ids), len(set(tree.ids)))
        self.assertIn('guide', tree.ids)
        for tab in tree.tabs:
            self.assertIn(tab, tree.ids)
        for tab in ('sites', 'sql', 'files', 'mqtt'):
            self.assertIn(tab, tree.tabs)
        self.assertIn('site-form', tree.ids)
        self.assertTrue(tree.guide_targets)
        for target in tree.guide_targets:
            self.assertIn(target, tree.ids)
        self.assertTrue(tree.copy_predecessors)
        self.assertEqual(set(tree.copy_predecessors), {'pre'})

    def test_guide_uses_internal_container_names_for_monitors(self):
        page = (ROOT / 'dashboard/index.html').read_text()
        self.assertIn('http://web:8080/', page)
        self.assertIn('Hostname db · Port 3306', page)
        self.assertIn('Hostname mqtt · Port 1883', page)
        self.assertNotIn('http://localhost:3306', page)
        self.assertIn('worker MQTT→SQL chưa kèm', page)
        self.assertIn('Không gửi ảnh có mật khẩu/token', page)
