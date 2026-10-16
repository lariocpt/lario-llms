"""Offline tests for the media toolkit: paths resolve, imports cannot run a pass,
a stray run cannot overwrite the plan, the tidy pass will not archive the only
copy of a film, and the MCP server exposes no delete verb.

No library is walked, nothing is written outside a temp dir, and no ffmpeg, GPU or
network is touched.
"""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MEDIA = Path(__file__).resolve().parents[1] / 'media'
SERVER = MEDIA / 'tools' / 'media_tools.py'
sys.path.insert(0, str(MEDIA))
from core import config  # noqa: E402


def payload(answer):
    """The JSON a tool call returned: MCP wraps it as a text content block."""
    return json.loads(answer['result']['content'][0]['text'])


# Module-level calls that can move, write, delete or shell out. None of them may
# appear at module level in a file that does not refuse import: that is the whole
# difference between a library and a command that reorganises a library.
WORK = ('remove', 'unlink', 'rename', 'rmtree', 'move', 'copy', 'copy2',
        'copyfile', 'makedirs', 'mkdir', 'symlink', 'link', 'removedirs',
        'truncate', 'write_text', 'write_bytes', 'run', 'Popen', 'call',
        'check_call', 'check_output', 'system', 'dump', 'replace')


def refuses_import(path):
    """True when importing this module raises instead of doing work."""
    for node in ast.parse(path.read_text()).body:
        if (isinstance(node, ast.If) and 'is a command' in ast.unparse(node)
                and isinstance(node.test, ast.Compare)
                and ast.unparse(node.test.left) == '__name__'):
            return True
    return False


def module_level_work(path):
    """Module-level calls that could touch the disk, outside a __main__ guard.

    Function and class bodies are NOT module level: they only run when called.
    (An earlier version of this walked into them and reported every os.replace in
    every helper as an import-time hazard.)
    """
    tree = ast.parse(path.read_text())
    guarded = set()
    for node in tree.body:
        if (isinstance(node, ast.If)
                and ast.unparse(node.test) == '__name__ == "__main__"'):
            guarded |= {id(child) for child in ast.walk(node)}
    found = []
    for node in tree.body:
        if id(node) in guarded or isinstance(node, ast.If):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Import, ast.ImportFrom)):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = ast.unparse(call.func).split('.')[-1]
            if name in WORK:
                found.append(ast.unparse(call)[:60])
    return found


def prose_lines(path):
    """Line numbers that are comments or docstring text: prose about a path is not
    code that uses it, and these files describe the library they filed."""
    source = path.read_text()
    lines = {i + 1 for i, line in enumerate(source.splitlines())
             if line.lstrip().startswith('#')}
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            lines |= set(range(node.lineno, node.end_lineno + 1))
    return lines



def corpus():
    for package in ('photos', 'music', 'video', 'audiobooks'):
        for path in sorted((MEDIA / package).rglob('*.py')):
            if path.name != 'paths.py':
                yield path


class TestPaths(unittest.TestCase):
    def test_every_domain_root_is_env_overridable(self):
        env = {'LARIO_PHOTO_LIB': '/tmp/pics', 'LARIO_VIDEO_LIB': '/tmp/vids',
               'LARIO_MUSIC_LIB': '/tmp/music', 'LARIO_MUSIC_STAGE': '/tmp/stage',
               'LARIO_MOVIES': '/tmp/movies', 'LARIO_SERIES': '/tmp/series',
               'LARIO_AUDIOBOOKS': '/tmp/ab', 'LARIO_BOOKS': '/tmp/books',
               'LARIO_PHOTO_STAGING': '/tmp/staging',
               'LARIO_PHOTO_BACKUP': '/tmp/backup', 'PLAN': '/tmp/plan.json'}
        with patch.dict(os.environ, env, clear=False):
            import importlib
            import core.config as module
            importlib.reload(module)
            for variable, expected in env.items():
                value = getattr(module, {
                    'LARIO_PHOTO_LIB': 'PHOTO_LIB', 'LARIO_VIDEO_LIB': 'VIDEO_LIB',
                    'LARIO_MUSIC_LIB': 'MUSIC_LIB', 'LARIO_MUSIC_STAGE': 'MUSIC_STAGE',
                    'LARIO_MOVIES': 'MOVIES', 'LARIO_SERIES': 'SERIES',
                    'LARIO_AUDIOBOOKS': 'AUDIOBOOKS', 'LARIO_BOOKS': 'BOOKS',
                    'LARIO_PHOTO_STAGING': 'PHOTO_STAGING',
                    'LARIO_PHOTO_BACKUP': 'PHOTO_BACKUP', 'PLAN': 'PHOTO_PLAN',
                }[variable])
                self.assertEqual(value, expected, variable)
            importlib.reload(config)

    def test_a_domain_script_sees_the_configured_root(self):
        # the shim is how 60 scripts get their roots; it must resolve through config
        script = ("import sys; sys.path.insert(0, %r); import paths; "
                  "print(paths.LIB)" % str(MEDIA / 'photos'))
        for variable, value in (('LARIO_PHOTO_LIB', '/tmp/clone-lib'),
                                ('LARIO_MUSIC_LIB', '/tmp/clone-music')):
            with patch.dict(os.environ, {variable: value}):
                package = 'photos' if 'PHOTO' in variable else 'music'
                out = subprocess.run(
                    [sys.executable, '-c', script.replace(str(MEDIA / 'photos'),
                                                          str(MEDIA / package))],
                    capture_output=True, text=True, check=True)
                self.assertEqual(out.stdout.strip(), value)

    def test_no_script_spells_out_a_library_path(self):
        """The move's whole point: roots live in core/config.py and nowhere else.

        oneoff/ is exempt -- those scripts record what was actually done to the
        library, and rewriting their paths would falsify the record.
        """
        offenders = []
        for path in corpus():
            if 'oneoff' in path.parts:
                continue
            prose = prose_lines(path)
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if number in prose:
                    continue
                if '/mnt/' in line or '/home/lario/Pictures' in line \
                        or '/srv/navidrome' in line or '/home/lario/Documents' in line:
                    offenders.append(f'{path.relative_to(MEDIA)}:{number}: {line.strip()[:64]}')
        self.assertEqual(offenders, [], 'hard-coded roots outside core/config.py')


class TestImportCannotRunAPass(unittest.TestCase):
    """Importing a command script used to run the pass. It must never again."""

    def test_modules_either_refuse_import_or_only_call_inert_things(self):
        unsafe = []
        for path in corpus():
            if refuses_import(path):
                continue
            for offender in module_level_work(path):
                unsafe.append(f'{path.relative_to(MEDIA)}: {offender}')
        self.assertEqual(unsafe, [])

    def test_the_guard_is_code_not_docstring_prose(self):
        """An earlier pass inserted the guard after the shebang, which for most of
        these files is inside the module docstring: valid Python, and inert."""
        misplaced = [str(path.relative_to(MEDIA)) for path in corpus()
                     if 'is a command; run it' in path.read_text()
                     and not refuses_import(path)]
        self.assertEqual(misplaced, [])

    def test_every_file_compiles(self):
        for path in corpus():
            try:
                ast.parse(path.read_text())
            except SyntaxError as error:
                self.fail(f'{path.relative_to(MEDIA)}: {error}')


class TestPlanCannotBeWiped(unittest.TestCase):
    """A finished import drains the sources, so a re-run plans nothing and used to
    write that empty plan over the hand-edited one. Twice, on 2026-10-14."""

    def setUp(self):
        self.source = (MEDIA / 'photos' / 'plan_import.py').read_text()

    def test_arguments_parse_before_any_work(self):
        self.assertIn('parse_known_args', self.source)
        self.assertLess(self.source.index('parse_known_args'),
                        self.source.index('json.dump'),
                        '--help must exit at the parser, not run the pass')

    def test_a_shrink_needs_an_explicit_override(self):
        self.assertIn('PLAN_ALLOW_SHRINK', self.source)
        self.assertIn('.prev', self.source)
        self.assertNotIn("json.dump({k: v for k, v in plan.items()}, open(",
                         self.source)

    def test_a_zero_record_plan_cannot_replace_a_real_one(self):
        """Functional behaviour is asserted at source level on purpose: exercising
        the real guard means running a full re-plan over the live library, which is
        minutes of I/O for a unit test."""
        guard = self.source.split('# The plan file is hand-edited')[1]
        self.assertIn('raise SystemExit', guard)
        self.assertIn('PLAN_ALLOW_SHRINK', guard)
        self.assertIn('os.replace', guard)


class TestMCPServer(unittest.TestCase):
    def rpc(self, requests, allow_jobs=False):
        import json
        import os
        env = dict(os.environ, PYTHONPATH=str(MEDIA))
        if allow_jobs:
            env['LARIO_MEDIA_ALLOW_JOBS'] = '1'
        else:
            env.pop('LARIO_MEDIA_ALLOW_JOBS', None)
        stdin = ''.join(json.dumps(r) + '\n' for r in requests)
        done = subprocess.run([sys.executable, str(SERVER)], input=stdin, cwd=str(MEDIA),
                              capture_output=True, text=True, timeout=120, env=env)
        return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]

    def test_initialize_and_readonly_surface(self):
        answers = self.rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                             'params': {'protocolVersion': '2024-11-05'}},
                            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}])
        self.assertEqual(answers[0]['result']['serverInfo']['name'], 'lario-media')
        names = {tool['name'] for tool in answers[1]['result']['tools']}
        self.assertEqual(names, {'media_status', 'media_jobs'})

    def test_no_delete_verb_exists_at_all(self):
        """Naming matters here: the catalogue *mentions* the photo delete chain
        precisely so nobody runs it blind, but nothing here can be asked to do it."""
        answer = self.rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}],
                          allow_jobs=True)[0]
        tools = answer['result']['tools']
        names = {tool['name'] for tool in tools}
        self.assertEqual(names, {'media_status', 'media_jobs', 'media_run'})
        for tool in tools:
            self.assertNotIn('delete', tool['name'])
        status = payload(self.rpc([
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
             'params': {'name': 'media_status', 'arguments': {}}}])[0])
        self.assertIs(status['deletes_available'], False)
        self.assertIn('LARIO_MEDIA_ALLOW_JOBS', payload(self.rpc([
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
             'params': {'name': 'media_status', 'arguments': {}}}])[0])['gate'])
        listed = payload(self.rpc([
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
             'params': {'name': 'media_jobs', 'arguments': {}}}])[0])
        for job in listed['runnable']:
            self.assertNotIn('delete', ' '.join([job['name'], job['command'], job['touches']]))
        self.assertTrue(any('delete' in job['name'] for job in listed['manual']),
                        'the delete chain should be visible as manual-only, not hidden')

    def test_jobs_are_gated_off_by_default(self):
        """With no gate env, media_run is not even registered, so a caller cannot
        reach it -- it is not merely refused at call time."""
        answer = self.rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': 'media_run',
                                       'arguments': {'name': 'photos_plan'}}}])[0]
        self.assertTrue(answer['result']['isError'])
        self.assertIn('unknown tool', answer['result']['content'][0]['text'])

    def test_a_job_argument_cannot_become_a_command_line(self):
        answer = self.rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': 'media_run',
                                       'arguments': {'name': 'photos_plan',
                                                     'options': {'--;rm -rf /': 1}}}}],
                          allow_jobs=True)[0]
        self.assertTrue(answer['result']['isError'])
        text = answer['result']['content'][0]['text']
        self.assertIn('options not accepted by photos_plan', text)
        # the message names the offending key, but nothing was executed: a rejected
        # option never becomes argv, because the job's argv is fixed in the server.
        self.assertNotIn('returncode', text)


class TestNothingIsDeleted(unittest.TestCase):
    def test_no_untouched_copy_is_in_the_way_of_the_repo(self):
        """The repo copy is the one to run. The home directories still hold the
        originals; this asserts the repo has the whole corpus, so nothing is only
        in a home directory waiting to be lost."""
        for package, home in (('photos', Path.home() / 'photos-reorg-work'),
                              ('music', Path.home() / 'music-reorganize'),
                              ('video', Path.home() / 'video-reorganize')):
            if not home.is_dir():
                self.skipTest(f'{home} is gone -- the repo is all that is left')
            missing = {p.name for p in home.glob('*.py')} - {p.name for p in
                                                            (MEDIA / package).rglob('*.py')}
            self.assertEqual(missing, set(), f'{package}: not in the repo: {missing}')


class TestTidyPass(unittest.TestCase):
    """The tidy pass moves litter out of the movie library. The failure it has to
    survive is `movies/Pulp Fiction`: an unextracted 2-CD RAR set that *is* the
    only copy of that film, with nothing but a 10 MB sample beside it. A tidy that
    archived it would have looked exactly like a tidy that worked."""

    TIDY = MEDIA / 'tools' / 'tidy_library.py'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.lib = root / 'movies'
        self.preserved = root / 'preserved-video'
        # one title, filed properly, holding the bigger copy
        self.file(self.lib / 'Inglourious Basterds (2009)' / 'Inglourious Basterds (2009).mkv', 5000)
        # the same title as an unprocessed XVID release: spool, smaller, half-extracted
        self.file(self.lib / 'Inglourious Basterds' / 'CD1' / 'imbt-xvid-isbs-cd1' / 'imbt-cd1.avi', 200)
        self.file(self.lib / 'Inglourious Basterds' / 'CD1' / 'imbt-xvid-isbs-cd1' / 'imbt.sfv', 40)
        self.file(self.lib / 'Inglourious Basterds' / 'Sample' / 'ib-sample.avi', 60)
        # and a spool with nothing filed beside it, which is the one that must not move
        self.file(self.lib / 'Pulp Fiction' / 'CD1' / 'pulp-fiction.ptv-rar.r00', 300)
        self.file(self.lib / 'Pulp Fiction' / 'CD1' / 'pulp-fiction.ptv-rar.sfv', 40)
        self.env = dict(os.environ, PYTHONPATH=str(MEDIA),
                        LARIO_MOVIES=str(self.lib), LARIO_SERIES=str(root / 'no-series'),
                        LARIO_PRESERVED=str(self.preserved),
                        LARIO_TIDY_AUDIT=str(root / 'tidy.jsonl'))

    def file(self, path, size, sparse=False):
        """sparse: an apparent size without the bytes, so a gate that reads sizes
        can be tested without writing a feature-length file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if sparse:
            with open(path, 'wb') as fh:
                fh.truncate(size)
        else:
            path.write_bytes(b'x' * size)
        return path

    def tidy(self, *args):
        """Runs the pass as the command it is, against the temp tree only: every
        root it could touch comes from the environment, including its audit file --
        a test must not append to the record `--undo` replays in production."""
        return subprocess.run([sys.executable, str(self.TIDY), *args], env=self.env,
                              capture_output=True, text=True, timeout=120)

    def test_a_plan_run_moves_nothing(self):
        out = self.tidy('video-litter')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('plan only', out.stdout)
        self.assertTrue((self.lib / 'Inglourious Basterds' / 'CD1' / 'imbt-xvid-isbs-cd1'
                         / 'imbt-cd1.avi').is_file(), 'planning moved something')
        self.assertFalse(self.preserved.exists(), 'planning created the archive')

    def test_the_only_copy_of_a_film_is_left_alone(self):
        out = self.tidy('video-litter', '--apply', '--prune-empty')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('no filed twin', out.stdout)
        self.assertIn('Pulp Fiction', out.stdout)
        for name in ('pulp-fiction.ptv-rar.r00', 'pulp-fiction.ptv-rar.sfv'):
            self.assertTrue((self.lib / 'Pulp Fiction' / 'CD1' / name).is_file(),
                            f'the only copy of {name} was archived')

    def test_a_smaller_unprocessed_spool_is_archived_and_indexed(self):
        self.tidy('video-litter', '--apply', '--prune-empty')
        filed = self.lib / 'Inglourious Basterds (2009)' / 'Inglourious Basterds (2009).mkv'
        self.assertEqual(filed.stat().st_size, 5000, 'the filed copy is the one that moved')
        archived = self.preserved / 'Inglourious Basterds' / 'CD1' / 'imbt-xvid-isbs-cd1'
        self.assertTrue((archived / 'imbt-cd1.avi').is_file())
        self.assertTrue((archived / 'imbt.sfv').is_file())
        index = (self.preserved / 'INDEX.txt').read_text()
        self.assertIn(str(self.lib / 'Inglourious Basterds'), index,
                      'archived without naming where it came from')
        self.assertFalse((self.lib / 'Inglourious Basterds').exists(),
                         '--prune-empty left the husk behind')
        audit = [json.loads(line)
                 for line in Path(self.env['LARIO_TIDY_AUDIT']).read_text().splitlines()]
        self.assertEqual(sum(1 for r in audit if r['ev'] == 'move'), 3,
                         'a move without an audit line cannot be undone')
        self.assertEqual(sum(1 for r in audit if r['ev'] == 'rmdir'), 4,
                         'the pruning is audited too -- otherwise the empty dirs are lost')
        self.assertTrue(all(r['pass'] == 'video-litter' for r in audit if r['ev'] == 'move'))

    def test_undo_replays_the_archive_back(self):
        self.tidy('video-litter', '--apply', '--prune-empty')
        out = self.tidy('--undo', 'video-litter')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('restored 3 files', out.stdout)
        for path in ('Inglourious Basterds/CD1/imbt-xvid-isbs-cd1/imbt-cd1.avi',
                     'Inglourious Basterds/CD1/imbt-xvid-isbs-cd1/imbt.sfv',
                     'Inglourious Basterds/Sample/ib-sample.avi'):
            self.assertTrue((self.lib / path).is_file(), f'{path} did not come back')
        self.assertEqual([p.name for p in self.preserved.rglob('*.avi')], [],
                         'restored, and still archived too')

    def test_a_film_filed_inside_another_film_is_hoisted(self):
        """The `Pulp Fiction` case, which is how the guard earns its keep: one
        dragged folder, a scanner that still found the film, and a top level that
        lied about it -- hiding the filed copy from every top-level check."""
        self.file(self.lib / 'Inglourious Basterds (2009)' / 'Downfall (2004)'
                  / 'Downfall (2004).mkv', 300_000_000, sparse=True)
        # the same film in pieces, and supplementary material, are not second works
        self.file(self.lib / 'Inglourious Basterds (2009)' / 'CD1' / 'ib-cd1.mkv',
                  300_000_000, sparse=True)
        self.file(self.lib / 'Inglourious Basterds (2009)' / 'Extras'
                  / 'Featurette (2009).mkv', 300_000_000, sparse=True)
        out = self.tidy('nested-movies', '--apply')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((self.lib / 'Downfall (2004)' / 'Downfall (2004).mkv').is_file(),
                        'the nested film was not hoisted: %s' % out.stdout)
        self.assertFalse((self.lib / 'CD1').exists(), 'a multi-part layout was hoisted')
        self.assertFalse((self.lib / 'Extras').exists(), 'extras were hoisted to the library root')
        self.assertEqual(sorted(p.name for p in self.lib.iterdir()),
                         ['Downfall (2004)', 'Inglourious Basterds',
                          'Inglourious Basterds (2009)', 'Pulp Fiction'])

    def test_never_overwrites_at_the_destination(self):
        """Two entries can yield the same scene filename; both have to survive."""
        archive = self.preserved / 'Inglourious Basterds' / 'CD1' / 'imbt-xvid-isbs-cd1'
        self.file(archive / 'imbt.sfv', 7)
        self.tidy('video-litter', '--apply', '--prune-empty')
        sides = sorted(p.stat().st_size for p in archive.iterdir() if p.suffix == '.sfv')
        self.assertEqual(sides, [7, 40], f'a collision was clobbered or renamed away: {sides}')
        self.assertEqual((archive / 'imbt.sfv').stat().st_size, 7,
                         'the copy that was already there was overwritten')


if __name__ == '__main__':
    unittest.main()
