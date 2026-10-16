"""Build and read the catalog of M4B audiobooks on quranaudiobooks.com.

The site publishes the library twice over: six *collection* folders (the
#m4b section) and ~33 *item* folders, each behind its own pCloud public link.
The collection folders cover everything except one item folder, and every link
holds tens of thousands of entries, so the tree is scraped once, laid out into
a stable relative-path catalog, and committed here as ``catalog.json``.  That
way a download job is reproducible, reviewable in git, and needs no network
until it actually transfers files.  ``build --refresh`` re-scrapes and reports
what changed.

Target layout under ``/mnt/media/audiobooks/islam``:

    Quran/Recitations/<Reciter>/<file>.m4b
    Quran/Translations/<Reciter + Translator>-<Lang>/<file>.m4b
    Quran/Tafseer/<Work - Author>/<file>.m4b
    Quran/Supplications/<Set>/<file>.m4b
    Seerah/<Speaker>/<file>.m4b
    Speeches/<Speaker>/<file>.m4b
    Hamd & Naat/Mix Collection/Volume-4/<file>.mp3

Source folder names are kept verbatim so any file can be traced back (the
``source`` field records the original pCloud path); only the collection roots
are remapped through ROOT_MAP, because the source spells one of them
``Suplications`` and parks the rest flat.
"""
import argparse
import concurrent.futures
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

PAGE = 'https://quranaudiobooks.com/downloads/'
HERE = Path(__file__).resolve().parent
CATALOG = HERE / 'catalog.json'
ROOT = '/mnt/media/audiobooks/islam'
VERSION = 1
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/126'

# pCloud collection root folder -> top level of our tree
ROOT_MAP = {
    'Tafseer': 'Quran/Tafseer',
    'Translations': 'Quran/Translations',
    'Recitations': 'Quran/Recitations',
    'Suplications': 'Quran/Supplications',      # the source root is misspelled
    'Seerah': 'Seerah',
    'Speeches': 'Speeches',
}
# item-level M4B folder that no collection folder covers
ITEM_MAP = {'Volume-4': 'Hamd & Naat/Mix Collection'}
JUNK_NAMES = {'.ds_store', '.iampreventingitunesfromremovingmyparentfolder'}

ITEM_RE = re.compile(r'<article class="download-item-card">(.*?)</article>', re.S)
LINK_RE = re.compile(r'href="https://(?:my|u)\.pcloud\.(?:com|link)/publink/show\?code='
                     r'([A-Za-z0-9]+)"[^>]*>(MP3|M4B)<')


def clean(name):
    """Normalise a source name into a safe single path component."""
    name = unicodedata.normalize('NFC', name).replace('\u00a0', ' ').replace('\u200b', '')
    name = name.replace('/', '-')
    return re.sub(r'\s+', ' ', name).strip().rstrip('.').strip()


def safe_parts(rel):
    """Split a catalog-relative path, rejecting anything that could escape the root."""
    text = str(rel)
    if text.startswith('/'):
        raise ValueError('catalog paths are relative to the library root: ' + repr(rel)[:120])
    parts = [p for p in text.split('/') if p not in ('', '.')]
    if not parts or any(p == '..' or '\x00' in p or len(p) > 255 for p in parts):
        raise ValueError('unsafe catalog path: ' + repr(rel)[:120])
    return parts


def destination(rel, root=ROOT):
    """Absolute destination for a catalog path, refused if it lands outside the root."""
    base = Path(root).resolve()
    path = base.joinpath(*safe_parts(rel)).resolve()
    if base not in path.parents:
        raise ValueError('path escapes the library root: ' + repr(rel)[:120])
    return str(path)


# ---------------------------------------------------------------- scrape side

def _html(url):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    return urllib.request.urlopen(request, timeout=90).read().decode('utf-8', 'replace')


def publink_tree(code):
    """The folder tree behind one public link, as embedded in its page."""
    html = _html('https://u.pcloud.link/publink/show?code=' + code)
    marker = 'var publinkData = '
    start = html.index(marker) + len(marker)
    depth = 0
    for index, char in enumerate(html[start:], start):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return json.loads(html[start:index + 1])
    raise ValueError('publinkData not closed in ' + code)


def _walk(node, path=(), out=None):
    out = [] if out is None else out
    here = path + (node.get('name', ''),)
    if not node.get('isfolder'):
        out.append({'path': here, 'size': node.get('size', node.get('filesize')),
                    'fileid': node.get('fileid')})
    for child in (node.get('contents') or []):
        _walk(child, here, out)
    return out


def _fetch_code(code):
    try:
        data = publink_tree(code)
        return code, {'root': data['metadata'].get('name'),
                      'files': _walk(data['metadata'])}
    except Exception as error:                        # noqa: BLE001 - report, keep scraping
        return code, {'error': str(error)[:200]}


def scrape():
    """Fetch the downloads page and every M4B link behind it."""
    html = _html(PAGE)
    items = []
    for block in ITEM_RE.findall(html):
        category = re.search(r'<p class="eyebrow">(.*?)</p>', block, re.S)
        title = re.search(r'<h3><a href="[^"]+">(.*?)</a></h3>', block, re.S)
        formats = {label: code for code, label in LINK_RE.findall(block)}
        items.append({'category': (category.group(1) if category else '').strip(),
                      'title': (title.group(1) if title else '').strip(),
                      'mp3': formats.get('MP3'), 'm4b': formats.get('M4B')})
    section = html[html.index('Downloads M4B Audiobooks'):html.index('Download by item')]
    collections = [[name.strip(), code] for name, code in
                   re.findall(r'<h3>(.*?)</h3>.*?publink/show\?code=([A-Za-z0-9]+)', section, re.S)]
    codes = {}
    for name, code in collections:
        codes.setdefault(code, None)
    for item in items:
        if item['m4b']:
            codes.setdefault(item['m4b'], None)
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        fetched = dict(pool.map(_fetch_code, list(codes)))
    failed = [code for code, value in fetched.items() if 'error' in value]
    if failed:
        raise RuntimeError('%d of %d source links failed: %s'
                           % (len(failed), len(codes), ', '.join(failed[:5])))
    return {'items': items, 'collections': collections, 'fetched': fetched}


# ------------------------------------------------------------------ layout

def layout(scraped):
    """Turn a scrape into catalog entries.  Returns (entries, dropped)."""
    fetched, collections = scraped['fetched'], scraped['collections']
    entries, dropped = [], []

    def add(code, prefix, files):
        for item in files:
            name = clean(item['path'][-1])
            if not name or name.lower() in JUNK_NAMES:
                dropped.append({'rel': ' / '.join(item['path']), 'reason': 'junk'})
                continue
            rel = prefix + '/' + '/'.join(clean(p) for p in item['path'][1:])
            entries.append({'rel': rel, 'size': item['size'], 'code': code,
                            'fileid': item['fileid'], 'source': ' / '.join(item['path'])})

    col_codes = [code for _, code in collections]
    for code in col_codes:
        info = fetched[code]
        prefix = ROOT_MAP[info['root']]
        add(code, prefix, info['files'])
    # the item-level folder nothing else covers (Mix Collection -> Volume-4)
    for code, info in fetched.items():
        if code in col_codes or info.get('root') not in ITEM_MAP:
            continue
        add(code, ITEM_MAP[info['root']] + '/' + clean(info['root']), info['files'])

    entries.sort(key=lambda entry: entry['rel'])
    entries = _dedupe(entries, dropped)
    entries = _drop_extensionless(entries, dropped)
    return entries, dropped


def _key(entry):
    return (' '.join(entry['rel'].rsplit('/', 1)[-1].lower().split()), entry['size'])


def _dedupe(entries, dropped):
    """The collections overlap each other; keep one copy of each (name, size)."""
    seen, kept = set(), []
    for entry in entries:
        key = _key(entry)
        if key in seen:
            dropped.append({'rel': entry['rel'], 'reason': 'duplicate'})
            continue
        seen.add(key)
        kept.append(entry)
    return kept


def _drop_extensionless(entries, dropped):
    """A file with no extension alongside the same name with one is a stray copy.

    Exactly one such file exists in the source (a speech that appears both as
    ``09-Shaykh al-Islam ...`` and as ``.m4b``, 2 kB apart).  Keeping both means
    the player shows the same lecture twice with no way to tell them apart.
    """
    with_ext = {' '.join(entry['rel'].rsplit('/', 1)[-1].rsplit('.', 1)[0].lower().split())
                + '\x00' + entry['rel'].rsplit('/', 1)[0]
                for entry in entries if '.' in entry['rel'].rsplit('/', 1)[-1]}
    kept = []
    for entry in entries:
        name = entry['rel'].rsplit('/', 1)[-1]
        folder = entry['rel'].rsplit('/', 1)[0]
        if '.' not in name and (' '.join(name.lower().split()) + '\x00' + folder) in with_ext:
            dropped.append({'rel': entry['rel'], 'reason': 'extensionless-duplicate'})
            continue
        kept.append(entry)
    return kept


# ------------------------------------------------------------- serialisation

def collections_of(entries):
    """Per-collection (top two path levels) file counts and byte totals."""
    groups = {}
    for entry in entries:
        name = '/'.join(entry['rel'].split('/')[:2])
        group = groups.setdefault(name, {'name': name, 'files': 0, 'bytes': 0})
        group['files'] += 1
        group['bytes'] += entry['size'] or 0
    return [groups[name] for name in sorted(groups)]


def document(entries, generated=None):
    total = sum(entry['size'] or 0 for entry in entries)
    return {'version': VERSION, 'source_page': PAGE, 'root': ROOT,
            'generated': generated or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'totals': {'files': len(entries), 'bytes': total},
            'collections': collections_of(entries), 'entries': entries}


def serialize(data):
    """One entry per line: a 3 300-line data blob that still diffs usefully."""
    head = {key: value for key, value in data.items() if key != 'entries'}
    lines = ['{']
    lines += ['%s: %s,' % (json.dumps(key), json.dumps(head[key])) for key in head]
    lines.append('"entries": [')
    lines += [json.dumps(entry, ensure_ascii=False, separators=(',', ':')) + ','
              for entry in data['entries']]
    lines[-1] = lines[-1][:-1]
    lines += [']', '}']
    return '\n'.join(lines) + '\n'


def write(data, path=CATALOG):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(serialize(data), encoding='utf-8')
    tmp.replace(path)
    return data


def build(refresh=False, scraped=None):
    """Return the catalog, refreshing it from the site only when asked."""
    if scraped is not None:
        entries, dropped = layout(scraped)
        data = document(entries)
        data['dropped'] = dropped
        return write(data)
    if not refresh and CATALOG.exists():
        return json.loads(CATALOG.read_text(encoding='utf-8'))
    entries, dropped = layout(scrape())
    data = document(entries)
    data['dropped'] = dropped
    return write(data)


def load(path=CATALOG):
    if not Path(path).exists():
        raise RuntimeError('no catalog yet: run catalog.py build --refresh')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def select(data, include=()):
    """Entries for the requested collections (empty include = the whole library)."""
    entries = data['entries']
    if not include:
        return list(entries)
    prefixes = []
    for value in include:
        prefixes.append('/'.join(safe_parts(value)))
    missing = [value for value in prefixes
               if not any(entry['rel'] == value or entry['rel'].startswith(value + '/')
                          for entry in entries)]
    if missing:
        raise ValueError('no catalog entries under: ' + ', '.join(missing)
                         + '; collections: ' + ', '.join(
                             item['name'] for item in data['collections']))
    return [entry for entry in entries
            if any(entry['rel'] == value or entry['rel'].startswith(value + '/')
                   for value in prefixes)]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('operation', choices=['build', 'show'], nargs='?', default='show')
    parser.add_argument('--refresh', action='store_true', help='re-scrape the source site')
    args = parser.parse_args()
    if args.operation == 'build':
        data = build(refresh=True)
    else:
        data = load() if CATALOG.exists() else build(refresh=args.refresh)
    print('root %s  generated %s' % (data['root'], data['generated']))
    print('%d files  %.2f GB (%.2f GiB)'
          % (data['totals']['files'], data['totals']['bytes'] / 1e9,
             data['totals']['bytes'] / 2 ** 30))
    for group in data['collections']:
        print('  %-50s %5d files %8.3f GB'
              % (group['name'], group['files'], group['bytes'] / 1e9))
    dropped = data.get('dropped', [])
    if dropped:
        reasons = {}
        for item in dropped:
            reasons[item['reason']] = reasons.get(item['reason'], 0) + 1
        print('dropped:', ', '.join('%s=%d' % kv for kv in sorted(reasons.items())))


if __name__ == '__main__':
    main()
