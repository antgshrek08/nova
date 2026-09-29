import io
import unittest
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch
from app import coursework_materials
from app.coursework_materials import extract
from app.coursework import _Document

class Materials(unittest.TestCase):
    def test_canvas_placeholder_uses_canonical_file_endpoint(self):
        doc = _Document()
        doc.feed('<a href="/$CANVAS_COURSE_REFERENCE$/file_ref/opaque" data-api-endpoint="https://school.example/api/v1/courses/12/files/34">Instructions</a>')
        self.assertEqual(doc.links, ['https://school.example/courses/12/files/34'])

    def test_docx_instructions_are_read(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as package:
            package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Compare two works and cite three sources.</w:t></w:r></w:p></w:body></w:document>')
        result = extract(data.getvalue(), 'instructions.docx')
        self.assertIn('cite three sources', result['text'])
        self.assertFalse(result['truncated'])

    def test_long_text_is_explicitly_truncated(self):
        result = extract(b'a' * 60001, 'instructions.txt')
        self.assertTrue(result['truncated'])

    def test_unsupported_files_are_not_claimed_read(self):
        with self.assertRaisesRegex(ValueError, 'separate reader'):
            extract(b'example', 'instructions.doc')


class UnresolvedMaterials(unittest.IsolatedAsyncioTestCase):
    async def test_unresolved_file_reference_does_not_loop_as_resolved(self):
        tab = MagicMock()
        tab.goto = AsyncMock()
        tab.locator.return_value.wait_for = AsyncMock()
        tab.locator.return_value.evaluate_all = AsyncMock(return_value=[{
            'title': 'Download exercises', 'url': 'https://school.example/$CANVAS_COURSE_REFERENCE$/file_ref/opaque'}])
        with patch.object(coursework_materials.browser_control, 'page', AsyncMock(return_value=tab)):
            with self.assertRaisesRegex(ValueError, 'unresolved attachment'):
                await coursework_materials.read('https://school.example/courses/12/assignments/34', 'https://school.example/$CANVAS_COURSE_REFERENCE$/file_ref/opaque')
