"""Read Canvas pages and assignment files through the signed-in browser."""
import asyncio
import hashlib
import io
import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree
from . import browser_control, coursework, operator_store as store, operator_workflows as workflows

MAX_BYTES = 50_000_000


def extract(content, name, content_type=''):
    suffix = Path(name).suffix.lower()
    if suffix == '.pdf' or 'application/pdf' in content_type:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) > 100:
            raise ValueError('This PDF exceeds 100 pages. Read it in sections before drafting.')
        text = '\n\n'.join(page.extract_text() or '' for page in reader.pages)
    elif suffix == '.docx':
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            item = document.getinfo('word/document.xml')
            if item.file_size > 10_000_000:
                raise ValueError('Word document is too large to extract.')
            root = ElementTree.fromstring(document.read(item))
            ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text = '\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns))
    elif suffix in ('.txt','.md','.csv') or content_type.startswith('text/'):
        text = content.decode('utf-8-sig', errors='replace')
        if 'html' in content_type:
            text = coursework.plain(text)
    else:
        raise ValueError('This file format needs a separate reader. Do not draft as though its contents were read.')
    if not text.strip():
        raise ValueError('No readable text was found; this may be a scanned document requiring OCR.')
    return {'text':text[:60000], 'truncated':len(text)>60000}


async def read(url, resource_url):
    origin, course, _, normalized = coursework.assignment_location(url)
    parsed = urlsplit(resource_url)
    if f'{parsed.scheme}://{parsed.netloc}' != origin or parsed.username or parsed.password:
        raise ValueError('This reader accepts only material on the assignment’s Canvas site. Use web_fetch for public external sources.')
    async with workflows.action_lock, browser_control._lock:
        workflows.require_running()
        tab = await browser_control.page()
        if '$CANVAS' in resource_url or '/file_ref/' in resource_url:
            await tab.goto(normalized, wait_until='domcontentloaded', timeout=30000)
            await tab.locator('body').wait_for(state='attached', timeout=15000)
            links = await tab.locator('a').evaluate_all('(links) => links.map(a => ({title:a.textContent.trim(),url:a.href}))')
            links = [link for link in links if re.search(r'/files/\d+', link['url']) and '$CANVAS' not in link['url'] and '/file_ref/' not in link['url']]
            if not links:
                raise ValueError('Canvas still exposes an unresolved attachment reference, not a downloadable file link. Open the attachment in Canvas or provide the actual file; its contents have not been read.')
            return {'resolved_links':links, 'next':'Read the matching resolved file URL with coursework_material before doing the work.', 'untrusted_content':True}
        page_match = re.fullmatch(r'/courses/(\d+)/pages/([^/]+)', parsed.path)
        if page_match:
            if page_match[1] != course:
                raise ValueError('The linked page belongs to another course.')
            page = await coursework.read_json(normalized, f'courses/{course}/pages/{page_match[2]}')
            doc = coursework._Document(); doc.feed(page.get('body') or '')
            from urllib.parse import urljoin
            return {'title':page.get('title'), 'text':coursework.plain(page.get('body')), 'resources':[urljoin(resource_url,link) for link in doc.links], 'untrusted_content':True}
        match = re.fullmatch(r'(?:/courses/(\d+))?/files/(\d+)(?:/download|/preview)?/?', parsed.path)
        if not match or (match[1] and match[1] != course):
            raise ValueError('Use a Canvas course page or file URL from the assignment.')
        meta = await coursework.read_json(normalized, f'files/{match[2]}')
        if int(meta.get('size') or 0) > MAX_BYTES:
            raise ValueError('Assignment files are limited to 50 MB.')
        download_url = meta.get('url') or f'{origin}/files/{match[2]}/download'
        destination = urlsplit(download_url)
        if destination.scheme != 'https' or destination.username or destination.password:
            raise ValueError('Canvas returned an invalid download URL.')
        response = await tab.context.request.get(download_url, timeout=30000)
        if response.status != 200:
            raise ValueError('Canvas could not download this material; check login and permissions.')
        content = await response.body()
        if len(content) > MAX_BYTES:
            raise ValueError('Assignment file exceeds 50 MB.')
        name = Path(meta.get('display_name') or meta.get('filename') or 'material').name
        digest = hashlib.sha256(content).hexdigest()
        path = store.directory() / f'material-{match[2]}-{digest[:12]}{Path(name).suffix}'
        path.write_bytes(content)
        extracted = await asyncio.to_thread(extract, content, name, response.headers.get('content-type',''))
        return {'title':name, 'source':resource_url, 'path':str(path), 'sha256':digest, **extracted, 'untrusted_content':True}
