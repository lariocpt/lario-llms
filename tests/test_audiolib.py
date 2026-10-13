"""Offline tests for the audiobook fetcher: layout, path safety, resume, refusal.

No network and no writes outside a temp directory: pCloud access and sleep are
patched, and the controller's state directory is redirected.
"""
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1] / 'media/audiolib'
sys.path.insert(0, str(DIRECTORY))
import catalog
import controller
import runner


def scrape_fixture():
    """A miniature of the source: one collection tree and one uncovered item."""
    def node(name, folder, fileid, size=None, contents=None):
        entry = {'name': name, 'isfolder': folder, 'fileid': fileid}
        if size is not None:
            entry['size'] = size
        if contents is not None:
            entry['contents'] = contents
        return entry

    return {
        'items': [{'category': 'Hamd & Naat', 'title': 'Mix Collection',
                   'mp3': None, 'm4b': 'ITEMCODE'}],
        'collections': [['Tafseer (Arabic)', 'COLCODE']],
        'fetched': {
            # the first node with a file must survive: a slice once dropped it
            'COLCODE': {'root': 'Tafseer', 'files': [
                {'path': ('Tafseer', 'Maarif-ul-Quran Vol 1', '001 Al-Fatiha.m4b'),
                 'size': 1000, 'fileid': 11},
                {'path': ('Tafseer', 'Maarif-ul-Quran Vol 1', '.DS_Store'),
                 'size': 6, 'fileid': 12},
                {'path': ('Tafseer', 'Maarif-ul-Quran Vol 1', '002 Al-Baqarah\u00a0.m4b'),
                 'size': 2000, 'fileid': 13},
                {'path': ('Tafseer', 'Tafheem-ul-Quran', '01-Faraz.m4b'),
                 'size': 3000, 'fileid': 14},
                {'path': ('Tafseer', 'Tafheem-ul-Quran', '01-Faraz'),      # stray copy
                 'size': 3002, 'fileid': 15},
                {'path': ('Tafseer', 'Tafheem-ul-Quran', '01-Faraz.m4b'),  # dup of 14
                 'size': 3000, 'fileid': 16}]},
            'ITEMCODE': {'root': 'Volume-4', 'files': [
                {'path': ('Volume-4', 'Ae Zaaire Taiba.mp3'), 'size': 500, 'fileid': 21}]},
        },
    }


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.entries, self.dropped = catalog.layout(scrape_fixture())
        self.reasons = sorted(item['reason'] for item in self.dropped)

    def test_every_source_file_is_accounted_for(self):
        # '002 Al-Baqarah .m4b' keeps its stray pre-extension space on purpose: the
        # published library contains exactly that shape (Wadee Hammadi Al Yamani's
        # 016-An-Nahl and 042-Ash-Shura), and clean() normalises only what a
        # filesystem needs, not what would look prettier.  Renaming past that would
        # break the one guarantee that matters here -- a path that still reads
        # against the source listing.
        self.assertEqual([entry['rel'] for entry in self.entries], [
            'Hamd & Naat/Mix Collection/Volume-4/Ae Zaaire Taiba.mp3',
            'Quran/Tafseer/Maarif-ul-Quran Vol 1/001 Al-Fatiha.m4b',
            'Quran/Tafseer/Maarif-ul-Quran Vol 1/002 Al-Baqarah .m4b',
            'Quran/Tafseer/Tafheem-ul-Quran/01-Faraz.m4b'])

    def test_junk_duplicate_and_extensionless_strays_are_dropped(self):
        self.assertEqual(self.reasons, ['duplicate', 'extensionless-duplicate', 'junk'])

    def test_source_path_is_kept_for_traceability(self):
        entry = next(item for item in self.entries if item['size'] == 2000)
        self.assertEqual(entry['source'], 'Tafseer / Maarif-ul-Quran Vol 1 / 002 Al-Baqarah\u00a0.m4b')
        self.assertNotIn('\u00a0', entry['rel'])

    def test_select_filters_by_prefix_and_names_the_alternatives(self):
        data = catalog.document(self.entries)
        self.assertEqual(len(catalog.select(data)), 4)
        self.assertEqual(len(catalog.select(data, ['Quran/Tafseer'])), 3)
        with self.assertRaises(ValueError) as error:
            catalog.select(data, ['Quran/Nope'])
        self.assertIn('Quran/Tafseer', str(error.exception))


class PathSafetyTests(unittest.TestCase):
    def test_escaping_paths_are_refused(self):
        for rel in ('../outside.m4b', '/etc/passwd', 'a/../../b.m4b', 'a//b.m4b\x00', ''):
            with self.assertRaises(ValueError, msg=rel):
                catalog.destination(rel, '/tmp/library')
        # an embedded empty component is a sloppy source path, not an escape
        self.assertEqual(catalog.destination('a//b.m4b', '/tmp/library'), '/tmp/library/a/b.m4b')
        self.assertEqual(catalog.destination('Quran/Tafseer/x.m4b', '/tmp/library'),
                         '/tmp/library/Quran/Tafseer/x.m4b')


class FetchTests(unittest.TestCase):
    """Resume, size verification and cancel behaviour of a single-file fetch."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.entry = {'rel': 'Quran/Tafseer/Set/001.m4b', 'size': 10, 'code': 'C', 'fileid': 1}
        runner.stop.clear()
        self.sleeper = patch.object(runner.time, 'sleep')
        self.sleeper.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.sleeper.stop)

    def run_fetch(self, body):
        def transfer(url, part, resume=True):
            Path(part).write_bytes(body)
            return len(body)
        with patch.object(runner.pcloud, 'download_url', return_value='https://x/y'), \
                patch.object(runner.pcloud, 'transfer', side_effect=transfer):
            return runner.fetch(self.entry, self.root)

    def test_complete_file_is_skipped_without_network(self):
        destination = Path(catalog.destination(self.entry['rel'], self.root))
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'0123456789')
        with patch.object(runner.pcloud, 'download_url') as lookup:
            state, size, _ = runner.fetch(self.entry, self.root)
        self.assertEqual((state, size), ('SKIP', 0))
        lookup.assert_not_called()

    def test_short_transfer_never_becomes_a_library_file(self):
        state, size, note = self.run_fetch(b'01234')
        self.assertEqual(state, 'FAIL')
        self.assertIn('size 5 != expected 10', note)
        destination = Path(catalog.destination(self.entry['rel'], self.root))
        self.assertFalse(destination.exists())
        self.assertTrue(destination.with_name('001.m4b.part').exists())

    def test_verified_transfer_is_published_atomically(self):
        state, size, _ = self.run_fetch(b'0123456789')
        self.assertEqual((state, size), ('OK', 10))
        self.assertEqual(Path(catalog.destination(self.entry['rel'], self.root)).read_bytes(),
                         b'0123456789')
        self.assertFalse(Path(catalog.destination(self.entry['rel'], self.root) + '.part').exists())

    def test_cancel_before_attempt_is_a_stop_not_a_failure(self):
        runner.stop.set()
        state, _, note = self.run_fetch(b'0123456789')
        self.assertEqual(state, 'STOP')
        self.assertIn('nothing was fetched', note)


class ControllerTests(unittest.TestCase):
    """``Popen`` is patched for the whole class, and nothing here may spawn.

    An earlier version of this file redirected only ``STATE_DIR``.  When the
    active-job assertion below failed instead of raising, ``start_op`` fell
    straight through and started a real full-library download: three of them,
    one per test run.  The jobs shared ``<name>.part`` paths, so one renamed a
    size-verified file into the library while another still had that path open
    and kept appending to it -- four finished files came back oversized.  A
    test that mutates the media disk before it asserts is not a test.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state'
        self.log_root = Path(self.tmp.name) / 'jobs'
        patch.object(controller, 'STATE_DIR', self.state).start()
        self.spawned = []
        patch.object(controller.subprocess, 'Popen',
                     side_effect=lambda *args, **kwargs: self.spawned.append(args)).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.assertEqual(self.spawned, [], 'a controller test must never spawn a runner')

    def test_start_refuses_bad_arguments_before_touching_the_network(self):
        cases = ({'root': '/tmp/elsewhere'}, {'log_root': '/tmp/logs'}, {'workers': 0},
                 {'workers': 99}, {'limit': -1}, {'min_free_gb': 0}, {'nonsense': 1},
                 {'include': 'Quran/Tafseer'})
        with patch.object(controller.socket, 'gethostname', return_value='bigcachy'):
            for request in cases:
                with self.assertRaises((ValueError, TypeError), msg=request):
                    controller.start_op(request)

    def test_start_refuses_an_active_job(self):
        # our own process group: signal 0 is a probe only, it delivers nothing
        controller.write_state({'job_id': 'running-1', 'state': 'running', 'started_mono': 1,
                                'pgid': os.getpgid(0)})
        with patch.object(controller.socket, 'gethostname', return_value='bigcachy'):
            with self.assertRaises(RuntimeError) as error:
                controller.start_op({})
        self.assertIn('already running', str(error.exception))

    def test_start_refuses_a_held_writer_lock(self):
        """The lock, not the state file: it also stops a job nobody registered."""
        self.log_root.mkdir(parents=True, exist_ok=True)
        handle = open(self.log_root / '.lock', 'a+')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write('4242\n')
        handle.flush()
        self.addCleanup(handle.close)
        with patch.object(controller.socket, 'gethostname', return_value='bigcachy'), \
                patch.object(controller, 'MEDIA_ANCHOR', self.tmp.name):
            with self.assertRaises(RuntimeError) as error:
                controller.start_op({'root': str(Path(self.tmp.name) / 'lib'),
                                     'log_root': str(self.log_root)})
        self.assertIn('writer lock', str(error.exception))
        self.assertIn('4242', str(error.exception))
        self.assertEqual(self.spawned, [])

    def test_a_second_runner_refuses_the_same_library(self):
        spec = {'lock_file': str(self.log_root / '.lock'), 'log_dir': str(self.log_root / 'j-1')}
        runner.acquire_writer_lock(spec)
        with self.assertRaises(RuntimeError) as error:
            runner.acquire_writer_lock(spec)
        self.assertIn('writer lock', str(error.exception))

    def test_cancel_without_a_job_is_not_an_error(self):
        self.assertIsNone(controller.cancel_op({})['cancelled'])

    def test_status_settles_a_runner_that_died_without_a_result(self):
        job_dir = Path(self.tmp.name) / 'job'
        job_dir.mkdir()
        controller.write_state({'job_id': 'dead-1', 'state': 'running', 'started_mono': 1,
                                'pgid': 999999, 'log_dir': str(job_dir), 'root': self.tmp.name})
        entries = [{'rel': 'Quran/Tafseer/Set/001.m4b', 'size': 4}]
        with patch.object(catalog, 'load', return_value={'entries': entries, 'collections': [],
                                                         'root': self.tmp.name}), \
                patch.object(controller, 'disk_free', return_value=10 * 2 ** 30):
            status = controller.status_op({})
        self.assertEqual(status['state'], 'interrupted')
        self.assertEqual(status['library']['missing'], 1)
        self.assertIn('resume', status['note'])

    def test_inventory_counts_exact_sizes_only(self):
        entries = [{'rel': 'a/ok.m4b', 'size': 4}, {'rel': 'a/short.m4b', 'size': 4}]
        root = Path(self.tmp.name) / 'lib'
        (root / 'a').mkdir(parents=True)
        (root / 'a/ok.m4b').write_bytes(b'abcd')
        (root / 'a/short.m4b').write_bytes(b'abc')
        (root / 'a/trailing.part').write_bytes(b'zz')
        summary = controller.inventory(entries, str(root))
        self.assertEqual((summary['present'], summary['missing']), (1, 1))
        self.assertEqual(summary['partial_parts'], 1)


class SerializationTests(unittest.TestCase):
    def test_catalog_round_trips_and_keeps_one_entry_per_line(self):
        entries = [{'rel': 'Quran/Tafseer/x.m4b', 'size': 1, 'code': 'C', 'fileid': 2,
                    'source': 'Tafseer / x.m4b'}]
        data = catalog.document(entries)
        text = catalog.serialize(data)
        self.assertEqual(json.loads(text), data)
        self.assertEqual(text.count('\n{"rel"'), 1)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'catalog.json'
            catalog.write(data, path)
            self.assertEqual(catalog.load(path), data)


if __name__ == '__main__':
    unittest.main()
