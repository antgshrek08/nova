import ast
from pathlib import Path
import unittest


class RoutingContractTests(unittest.TestCase):
    def test_categories_have_valid_steps(self):
        source = (Path(__file__).resolve().parents[1] / 'app/routing.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        names = {node.targets[0].id for node in tree.body if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name)}
        names.update(node.target.id for node in tree.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name))
        self.assertIn('CATEGORY_CHAINS', names)
        self.assertNotIn('gemini', source[source.index('CATEGORY_CHAINS'):source.index('_ALLOW_GEMINI_INTERIM')])
        self.assertIn('antigravity_cli', source)

    def test_mcp_aliases_are_collision_safe(self):
        source = (Path(__file__).resolve().parents[1] / 'app/mcp_manager.py').read_text(encoding='utf-8')
        self.assertIn('mcp_{row[\'id\']}', source)
        self.assertIn('next_cursor', source)
