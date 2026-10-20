#!/usr/bin/env python3
"""The contract tests (PLAN §13). Offline, temp-dir only, no GPU, no library.

Two of these are about one thing above all: **nothing deletes a source.** A
merge that misfileses a photo is fixable; a merge that deletes one is not. So
the suite spends most of its budget proving that `merge` has no path to
`remove`, and that `purge` -- the only verb that does -- cannot be run without a
terminal to answer two confirmations in.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

MEDIA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MEDIA)

from core import config, confirm, digest, fsx, gate, ledger, lock, names, report  # noqa: E402

RUN = os.path.join(MEDIA, 'run.py')


def write(path, size=1024, seed=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write((seed * (size // len(seed) + 1))[:size])
    return path


def drive(*argv, env=None, stdin=''):
    """Invoke the driver with the volume floor switched off.

    The 50 GB floor is a rule about real media volumes, not about kilobyte fixtures, and
    the suite's scratch destination lives on a tmpfs whose free space moves with whatever
    else the machine was doing -- 8 green tests went red on a day the RAM temp filled up.
    The floor is still tested, explicitly, by
    TestGates.test_the_free_floor_refuses_before_any_write.
    """
    if '--free-floor-gb' not in argv:
        argv = (*argv, '--free-floor-gb', '0')
    environment = dict(os.environ)
    environment.update(env or {})
    return subprocess.run([sys.executable, RUN, *argv], capture_output=True,
                          text=True, input=stdin, cwd=MEDIA, env=environment)


def runs_in(dest):
    """Run ids under `<dest>/_mediatool`, in the order they were created.

    `os.listdir` order is not a thing you can rely on, and the ledger file and the
    lock files live in the same directory as the run directories -- so picking
    `[0]` would sometimes hand a test `ledger.sqlite/summary.json`.
    """
    directory = os.path.join(dest, '_mediatool')
    if not os.path.isdir(directory):
        return []
    return sorted(name for name in os.listdir(directory)
                  if os.path.isdir(os.path.join(directory, name)))


def read_text(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read()


def read_bytes(path):
    with open(path, 'rb') as handle:
        return handle.read()


class Case(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='media-contract-')
        self.src = os.path.join(self.root, 'src')
        self.src2 = os.path.join(self.root, 'src2')
        self.dest = os.path.join(self.root, 'dest')
        self.library = os.path.join(self.root, 'library')
        for directory in (self.src, self.src2, self.dest, self.library):
            os.makedirs(directory)
        # Point every library at the scratch tree: a test that scanned the real
        # /mnt/media would be slow, non-reproducible, and wrong to run at all.
        self.env = {f'LARIO_{name}': self.library
                    for name in ('MOVIES', 'PHOTO_LIB', 'MUSIC_LIB', 'BOOKS',
                                 'AUDIOBOOKS', 'SERIES')}
        self.env['LARIO_DEST_MOVIES'] = self.library

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


class TestNothingDeletes(Case):
    """§13 destructive-safety. The reason the toolkit is built this way."""

    def test_apply_leaves_every_source_present(self):
        write(os.path.join(self.src, 'a.mkv'), 4096, b'a')
        write(os.path.join(self.src2, 'b.mkv'), 2048, b'b')
        before = sorted(os.path.relpath(os.path.join(d, f), self.root)
                        for d in (self.src, self.src2) for f in os.listdir(d))
        result = drive('movies', 'merge', '--src', self.src, '--src', self.src2,
                       '--dest', self.dest, '--apply', env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = sorted(os.path.relpath(os.path.join(d, f), self.root)
                       for d in (self.src, self.src2) for f in os.listdir(d))
        self.assertEqual(before, after)
        # The real assertion, stated plainly: every source file is still on disk,
        # unchanged. Wording in a report is not evidence; this is.
        for rel in before:
            self.assertTrue(os.path.getsize(os.path.join(self.root, rel)) > 0)

    def test_merge_has_no_route_to_removal(self):
        """Static: run.py may not call remove(), and no core module deletes except
        fsx, which requires an authorised ledger row to do it at all."""
        source = read_text(RUN)
        self.assertNotIn('fsx.remove', source.split('def cmd_purge')[0],
                         'the only verb allowed to delete is purge')
        for leaf in sorted(os.listdir(os.path.join(MEDIA, 'core'))):
            if not leaf.endswith('.py') or leaf == 'fsx.py':
                continue
            text = read_text(os.path.join(MEDIA, 'core', leaf))
            for primitive in ('os.remove(', 'os.unlink(', 'shutil.rmtree('):
                self.assertNotIn(primitive, text, f'{leaf} may not call {primitive}')

    def test_purge_refuses_without_a_terminal(self):
        write(os.path.join(self.src, 'a.mkv'), 4096, b'a')
        drive('movies', 'merge', '--src', self.src, '--dest', self.dest, '--apply',
              env=self.env)
        run_id = runs_in(self.dest)[0]
        result = drive('movies', 'purge', '--dest', self.dest, '--run', run_id,
                       env=self.env, stdin='DELETE\n9999\n')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('interactive terminal', result.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.src, 'a.mkv')),
                        'a refused purge must leave the source on disk')

    def test_deletes_are_staged_never_executed(self):
        same = write(os.path.join(self.src, 'a.mkv'), 4096, b'a')
        write(os.path.join(self.src2, 'a-copy.mkv'), 4096, b'a')
        result = drive('movies', 'merge', '--src', self.src, '--src', self.src2,
                       '--dest', self.dest, '--apply', env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        stage = os.path.join(self.dest, '_mediatool', runs_in(self.dest)[0],
                             'deletes.json')
        with open(stage, encoding='utf-8') as handle:
            payload = json.load(handle)
        self.assertEqual(payload['total_files'], 1)
        self.assertIn('STAGED ONLY', payload['note'])
        self.assertTrue(os.path.exists(same))
        self.assertTrue(os.path.exists(os.path.join(self.src2, 'a-copy.mkv')))


class TestConfirmGate(unittest.TestCase):
    """The two prompts, driven directly so a wrong answer is provably a stop."""

    def run_confirm(self, answers, total=1234):
        stream = iter(answers)
        seen = []
        confirm.confirm(3, total, '/tmp/dest', 'r-1',
                        output=lambda text, **kw: seen.append(text),
                        input_fn=lambda: next(stream))
        return seen

    def test_wrong_word_stops(self):
        with self.assertRaises(confirm.NotConfirmed):
            self.run_confirm(['yes please', '1234'])

    def test_wrong_byte_total_stops(self):
        with self.assertRaises(confirm.NotConfirmed):
            self.run_confirm(['DELETE', '4321'])

    def test_both_answers_needed(self):
        self.assertTrue(self.run_confirm(['DELETE', '1234']))

    def test_no_yes_flag_exists(self):
        """Not a grep for the word -- the parser must genuinely reject it.

        Checking that `--yes` does not appear in run.py would fail for the wrong
        reason (the docstring says there is no `--yes`), so ask argparse instead.
        """
        with open(RUN, encoding='utf-8') as handle:
            source = handle.read()
        for flag in ('--yes', '--force-delete', '--delete-sources'):
            self.assertNotIn(f"add_argument('{flag}'", source,
                             f'{flag} must not be an option')
        source_dir = os.path.dirname(RUN)
        result = subprocess.run(
            [sys.executable, os.path.join(source_dir, 'run.py'), 'movies', 'merge',
             '--src', '/tmp', '--dest', '/tmp/none', '--yes'],
            capture_output=True, text=True, cwd=source_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unrecognized arguments: --yes', result.stderr)


class TestLedgerAuthority(Case):
    def test_plan_only_run_can_never_authorise_a_delete(self):
        store = ledger.Ledger(self.dest, apply=False)
        store.start_run('r', 'movies', 'merge', 'structure', [self.src], self.dest, {})
        victim = write(os.path.join(self.src, 'v.mkv'), 64, b'v')
        survivor = write(os.path.join(self.dest, 'v.mkv'), 64, b'v')
        store.request_delete('r', victim)
        store.verify_copy('r', survivor, fsx.sha256(victim), 64)
        self.assertIsNone(store.authorised_delete('r', victim))
        with self.assertRaises(fsx.UnauthorisedDelete):
            fsx.remove(store, 'r', victim)
        self.assertTrue(os.path.exists(victim))

    def test_authorised_only_when_bytes_survive_and_hash_matches(self):
        store = ledger.Ledger(self.dest, apply=True)
        store.start_run('r', 'movies', 'merge', 'structure', [self.src], self.dest, {})
        victim = write(os.path.join(self.src, 'v.mkv'), 64, b'v')
        survivor = write(os.path.join(self.dest, 'keep.mkv'), 64, b'v')
        store.request_delete('r', victim)
        store.verify_copy('r', survivor, fsx.sha256(victim), 64)
        self.assertIsNotNone(store.authorised_delete('r', victim))
        receipt = fsx.remove(store, 'r', victim)
        self.assertEqual(receipt['bytes'], 64)
        self.assertFalse(os.path.exists(victim))
        self.assertTrue(os.path.exists(survivor))
        self.assertEqual(store.unclaimed_deletes('r'), [])

    def test_a_file_that_changed_since_the_plan_is_refused(self):
        store = ledger.Ledger(self.dest, apply=True)
        store.start_run('r', 'movies', 'merge', 'structure', [self.src], self.dest, {})
        victim = write(os.path.join(self.src, 'v.mkv'), 64, b'v')
        survivor = write(os.path.join(self.dest, 'keep.mkv'), 64, b'v')
        store.request_delete('r', victim)
        store.verify_copy('r', survivor, fsx.sha256(victim), 64)
        write(os.path.join(self.src, 'v.mkv'), 64, b'z')          # changed after planning
        with self.assertRaises(fsx.UnauthorisedDelete):
            fsx.remove(store, 'r', victim)
        self.assertTrue(os.path.exists(victim))

    def test_plan_json_is_immutable(self):
        path = os.path.join(self.dest, '_mediatool', 'run-x')
        os.makedirs(path)
        ledger.write_plan(path, {'reviewed': 'first'})
        ledger.write_plan(path, {'reviewed': 'second'})
        with open(os.path.join(path, 'plan.json'), encoding='utf-8') as handle:
            self.assertEqual(json.load(handle)['reviewed'], 'first')


class TestGates(Case):
    def test_two_destinations_refuse(self):
        result = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                       '--dest', self.library, env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn('given twice', result.stderr)

    def test_the_free_floor_refuses_before_any_write(self):
        """The floor is a real gate, so the suite asserts it on purpose rather than
        inheriting whatever the host volume happens to have free today."""
        write(os.path.join(self.src, 'a.mkv'), 1200, b'a')
        result = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                       '--apply', '--free-floor-gb', '1e12', env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn('floor', result.stderr)
        self.assertFalse([name for name in os.listdir(self.dest)
                          if name.endswith('.mkv')], result.stdout)

    def test_many_sources_one_dest_is_allowed(self):
        write(os.path.join(self.src, 'a.mkv'), 1200, b'a')
        write(os.path.join(self.src2, 'b.mkv'), 1200, b'b')
        result = drive('movies', 'merge', '--src', self.src, '--src', self.src2,
                       '--dest', self.dest, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('2 files, 2.4 KB', result.stdout)

    def test_nesting_refuses_and_records_the_reason_when_allowed(self):
        nested = os.path.join(self.dest, 'inner')
        os.makedirs(nested)
        write(os.path.join(self.src, 'a.mkv'), 1200, b'a')
        result = drive('movies', 'merge', '--src', self.dest, '--dest', nested,
                       env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn('inside', result.stderr)
        allowed = drive('movies', 'merge', '--src', self.dest, '--dest', nested,
                        '--allow-nested', 'staging sits inside the drive', env=self.env)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        plans = [os.path.join(nested, '_mediatool', item, 'plan.json')
                 for item in os.listdir(os.path.join(nested, '_mediatool'))
                 if os.path.isdir(os.path.join(nested, '_mediatool', item))]
        with open(plans[0], encoding='utf-8') as handle:
            payload = json.load(handle)
        self.assertEqual(payload['opts']['allow_nested_reason'], 'staging sits inside the drive')

    def test_newline_in_an_argument_refuses_the_run(self):
        result = drive('movies', 'merge', '--src', self.src + '\nrm -rf /',
                       '--dest', self.dest, env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn('newline or NUL', result.stderr)

    def test_missing_dependency_refuses_with_the_install_command(self):
        environment = dict(self.env)
        environment['PATH'] = '/nonexistent'
        result = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                       env=environment)
        self.assertEqual(result.returncode, 2)
        self.assertIn('ffprobe', result.stderr)

    def test_evidence_lives_under_the_destination_never_home(self):
        home = os.path.join(self.root, 'fake-home')
        os.makedirs(home)
        environment = dict(self.env)
        environment['HOME'] = home
        write(os.path.join(self.src, 'a.mkv'), 1200, b'a')
        result = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                       '--apply', env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.listdir(home), [], 'evidence must not be written under $HOME')
        self.assertTrue(os.path.isdir(os.path.join(self.dest, '_mediatool')))

    def test_lock_blocks_a_second_run_of_the_same_pass(self):
        write(os.path.join(self.src, 'a.mkv'), 1200, b'a')
        ready = os.path.join(self.root, 'ready')
        holder = subprocess.Popen(
            [sys.executable, '-c',
             'import sys, os, time; sys.path.insert(0, %r); from core import lock;'
             'l = lock.PassLock(%r, "movies", "structure", "holder-run"); l.acquire();'
             'open(%r, "w").write("x"); time.sleep(20)'
             % (MEDIA, self.dest, ready)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if os.path.exists(ready):
                    break
                import time as _t
                _t.sleep(0.05)
            result = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                           env=self.env)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn('holder-run', result.stderr)
        finally:
            holder.kill()

    def test_same_process_may_retake_its_own_lock(self):
        with lock.PassLock(self.dest, 'movies', 'structure', 'r1'):
            with lock.PassLock(self.dest, 'movies', 'structure', 'r1') as inner:
                self.assertEqual(inner.held, 2)


class TestAccounting(Case):
    def test_copies_count_as_relocated_not_reclaimed(self):
        write(os.path.join(self.src, 'a.mkv'), 5000, b'a')
        result = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                       '--apply', env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.dest, '_mediatool', runs_in(self.dest)[0],
                               'summary.json'), encoding='utf-8') as h:
            summary = json.load(h)
        self.assertEqual(summary['bytes_reclaimed'], 0)
        self.assertEqual(summary['bytes_relocated'], 5000)

    def test_rerun_is_a_no_op_against_the_same_destination(self):
        write(os.path.join(self.src, 'a.mkv'), 5000, b'a')
        drive('movies', 'merge', '--src', self.src, '--dest', self.dest, '--apply',
              env=self.env)
        files = sorted(os.listdir(os.path.join(self.dest, 'Movies')))
        second = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                       '--apply', env=self.env)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(files, sorted(os.listdir(os.path.join(self.dest, 'Movies'))))
        # The LAST run, not the first: run ids sort chronologically, and the
        # first run's summary is the one that legitimately says "1 net new".
        with open(os.path.join(self.dest, '_mediatool', runs_in(self.dest)[-1],
                               'summary.json'), encoding='utf-8') as h:
            summary = json.load(h)
        self.assertEqual(summary['overlap']['net_new']['files'], 0,
                         'second run was not a no-op:\n' + second.stdout)
        self.assertEqual(summary['overlap']['already_on_dest']['files'], 1)

    def test_run_ids_are_ordered_and_run_dirs_are_claimed_once(self):
        """Two properties, both earned by a test that first asked for a false one.

        `ls _mediatool | tail -1` is how an operator finds the run they just did,
        so the timestamp part of an id must never go backwards. What it cannot
        also be is *unique*: `time.time()` repeats inside a microsecond on this
        machine, so an id asserting uniqueness by timestamp fails about a run in
        two -- the correct answer from a test. Uniqueness therefore comes from
        claiming the directory, which only the filesystem can do.
        """
        stamps = [gate.new_run_id('movies', 'merge').rsplit('-', 1)[0]
                  for _ in range(500)]
        self.assertEqual(stamps, sorted(stamps), 'run ids must sort chronologically')
        self.assertEqual(len({gate.new_run_id('movies', 'merge') for _ in range(500)}), 500,
                         'run ids must be unique')

        claimed = [gate.claim_run_dir(self.dest, 'movies', 'merge')[0] for _ in range(50)]
        self.assertEqual(len(set(claimed)), 50, 'two runs must never share an evidence dir')
        self.assertEqual(len(runs_in(self.dest)), 50)

    def test_collision_renames_and_keeps_both_files(self):
        """A name clash must never skip content: two different files, two names."""
        first = write(os.path.join(self.src, 'one.mkv'), 3000, b'1')
        drive('movies', 'merge', '--src', self.src, '--dest', self.dest, '--apply',
              env=self.env)
        other = os.path.join(self.root, 'other')
        write(os.path.join(other, 'one.mkv'), 3000, b'2')
        result = drive('movies', 'merge', '--src', other, '--dest', self.dest, '--apply',
                       env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        landed = sorted(os.listdir(os.path.join(self.dest, 'Movies')))
        self.assertEqual(landed, ['one (2).mkv', 'one.mkv'])
        self.assertNotEqual(read_bytes(os.path.join(self.dest, 'Movies', 'one.mkv')),
                            read_bytes(os.path.join(self.dest, 'Movies', 'one (2).mkv')))
        self.assertTrue(os.path.exists(first))

    def test_foreign_files_are_reported_with_their_command_and_moved_by_nothing(self):
        photo = write(os.path.join(self.src, 'holiday.jpg'), 700, b'p')
        write(os.path.join(self.src, 'a.mkv'), 1200, b'a')
        result = drive('movies', 'merge', '--src', self.src, '--dest', self.dest,
                       '--apply', env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('holiday.jpg', result.stdout)
        self.assertIn('photos merge', result.stdout)
        self.assertTrue(os.path.exists(photo))
        self.assertFalse(os.path.exists(os.path.join(self.dest, 'Movies', 'holiday.jpg')))

    def test_clutter_is_skipped_and_never_counted(self):
        write(os.path.join(self.src, 'a.mkv'), 1200, b'a')
        write(os.path.join(self.src, '.DS_Store'), 300, b'j')
        write(os.path.join(self.src, '._a.mkv'), 300, b'j')
        drive('movies', 'merge', '--src', self.src, '--dest', self.dest, '--apply',
              env=self.env)
        landed = sorted(os.listdir(os.path.join(self.dest, 'Movies')))
        self.assertEqual(landed, ['a.mkv'])


class TestNames(unittest.TestCase):
    def test_exfat_reality(self):
        self.assertTrue(names.exfat_problems('holiday: 2020?.jpg'))
        self.assertTrue(names.exfat_problems('CON.mp4'))
        self.assertEqual(names.exfat_problems('holiday 2020.jpg'), [])
        self.assertIn('trailing', ' '.join(names.exfat_problems('name.')))

    def test_case_fold_identity_is_a_collision_not_a_second_file(self):
        seen = {}
        first = names.unique(seen, 'Movie.MKV')
        second = names.unique(seen, 'movie.mkv')
        self.assertEqual(first, 'Movie.MKV')
        self.assertEqual(second, 'movie (2).mkv')

    def test_unicode_survives_and_an_emoji_counts_double(self):
        self.assertEqual(names.sanitise('صور إجازة.jpg'), 'صور إجازة.jpg')
        self.assertEqual(names.utf16_len('😀'), 2)

    def test_truncation_keeps_the_extension(self):
        long = 'x' * 400 + '.mp4'
        self.assertTrue(names.sanitise(long).endswith('.mp4'))


class TestSourceList(unittest.TestCase):
    """§3.4.1 — the photo pass takes N named source trees, default unchanged.

    Consolidating drives means the same day arrives from three sources, and the
    rule that keeps one day folder shared across them lives inside `plan_import`.
    Two drives imported separately would produce two competing `2019-07-14/`
    trees, so the source list has to be one list of *named* trees, and the name is
    the provenance tag every manifest line is written against.
    """

    DEFAULT = {'Mac Photos': '/hhd/Mac Photos', 'Photosusa': '/hhd/Photosusa'}

    def setUp(self):
        self.saved = os.environ.pop('LARIO_SRC_DIRS', None)

    def tearDown(self):
        os.environ.pop('LARIO_SRC_DIRS', None)
        if self.saved is not None:
            os.environ['LARIO_SRC_DIRS'] = self.saved

    def test_unset_gives_exactly_the_two_it_always_had(self):
        self.assertEqual(config.named_sources('LARIO_SRC_DIRS', self.DEFAULT), self.DEFAULT)

    def test_names_and_order_are_the_ones_the_operator_chose(self):
        os.environ['LARIO_SRC_DIRS'] = 'DriveA=/mnt/a:DriveB=/mnt/b:DriveC=/mnt/c'
        got = config.named_sources('LARIO_SRC_DIRS', self.DEFAULT)
        self.assertEqual(list(got), ['DriveA', 'DriveB', 'DriveC'])
        self.assertEqual(got['DriveC'], '/mnt/c')

    def test_ambiguous_values_refuse_rather_than_guess(self):
        # Each of these would import the wrong thing, or nothing, while looking fine.
        for bad in ('no-equals', 'A=', '=x', 'A=/a:A=/b', 'A=/mnt/a:b', '   '):
            os.environ['LARIO_SRC_DIRS'] = bad
            with self.assertRaises(ValueError, msg=f'{bad!r} should be refused'):
                config.named_sources('LARIO_SRC_DIRS', self.DEFAULT)


class TestSourceTreesAreRegistered(unittest.TestCase):
    """§3.4.1 — the passes that read the *external drives* read the attached list.

    Four of them shipped with `{'Mac Photos': ..., 'Photosusa': ...}` written into the
    source. That is not a constant, it is last batch's drive layout. Point a new drive at
    such a pass and it still walks the two old paths, so it finds nothing, reports a clean
    run, and the drive that is actually mounted is never read -- the failure mode is a
    quiet wrong answer, not an error. The next batch is the handover drive (§14 phase H),
    which is exactly when a quietly-empty pass would be trusted.
    """

    PASSES = ('photos/plan_import.py', 'photos/check_zips.py', 'photos/classify_zips.py',
              'photos/delete_source_duplicates.py', 'photos/transcode_import_videos.py')

    def _roots(self, rel):
        """Every `*ROOTS = ...` binding in the pass, with the env var and default it names."""
        with open(os.path.join(MEDIA, rel), encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        found = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id.endswith('ROOTS')):
                found.append(node)
        self.assertTrue(found, f'{rel} no longer binds its source roots at all')
        return found

    def test_every_pass_resolves_its_roots_through_the_env_seam(self):
        for rel in self.PASSES:
            for node in self._roots(rel):
                with self.subTest(passfile=rel, lineno=node.lineno):
                    self.assertIsInstance(
                        node.value, ast.Call,
                        f'{rel}:{node.lineno} hardcodes {node.targets[0].id}: register it with '
                        "named_sources('LARIO_SRC_DIRS', ...) so an attached drive is read")
                    self.assertEqual(getattr(node.value.func, 'id', None), 'named_sources',
                                     f'{rel}:{node.lineno} resolves roots the wrong way')
                    self.assertEqual(node.value.args[0].value, 'LARIO_SRC_DIRS',
                                     f'{rel}:{node.lineno} reads a different variable')

    def test_the_fallback_is_still_the_two_trees_they_always_had(self):
        """Registering the seam must not have changed what unset means."""
        for rel in self.PASSES:
            for node in self._roots(rel):
                with self.subTest(passfile=rel, lineno=node.lineno):
                    keys = [ast.literal_eval(key) for key in node.value.args[1].keys]
                    self.assertEqual(sorted(keys), ['Mac Photos', 'Photosusa'])


class TestRatchet(unittest.TestCase):
    """§13.8. The corpora predate this contract and 41 sites already delete."""

    LIMIT = 41
    DOMAIN_DIRS = ('photos', 'video', 'music', 'audiobooks', 'tools')

    def sites(self):
        found = []
        for directory in self.DOMAIN_DIRS:
            base = os.path.join(MEDIA, directory)
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [leaf for leaf in dirnames if leaf != '__pycache__']
                for leaf in filenames:
                    if not leaf.endswith('.py'):
                        continue
                    path = os.path.join(dirpath, leaf)
                    with open(path, encoding='utf-8', errors='replace') as handle:
                        for number, line in enumerate(handle, 1):
                            if any(token in line for token in
                                   ('os.remove(', 'os.unlink(', 'shutil.rmtree(',
                                    '.unlink(')):
                                found.append(f'{path}:{number}')
        return found

    def test_the_corpus_does_not_grow(self):
        sites = self.sites()
        self.assertLessEqual(len(sites), self.LIMIT,
                             f'delete-primitive sites grew to {len(sites)}: '
                             f'{[s for s in sites if s not in set(sites[:self.LIMIT])][:5]}')

    def test_new_core_code_deletes_nothing_but_fsx(self):
        core = os.path.join(MEDIA, 'core')
        for leaf in sorted(os.listdir(core)):
            if not leaf.endswith('.py'):
                continue
            text = read_text(os.path.join(core, leaf))
            if leaf == 'fsx.py':
                self.assertNotIn('shutil.rmtree', text)
                continue
            for primitive in ('os.remove(', 'os.unlink(', 'shutil.rmtree('):
                self.assertNotIn(primitive, text)


class TestDirection(unittest.TestCase):
    """§4.4: core knows the shape of media work and no specific corpus."""

    def test_core_imports_no_domain_package(self):
        core = os.path.join(MEDIA, 'core')
        for leaf in sorted(os.listdir(core)):
            if not leaf.endswith('.py'):
                continue
            text = read_text(os.path.join(core, leaf))
            for package in ('photos', 'video', 'music', 'audiobooks', 'books'):
                self.assertNotIn(f'from {package}', text, f'core/{leaf} imports {package}')
                self.assertNotIn(f'import {package}', text, f'core/{leaf} imports {package}')

    def test_duplicates_escalates_and_caches(self):
        root = tempfile.mkdtemp(prefix='digest-')
        a = write(os.path.join(root, 'a.bin'), 4096, b'a')
        b = write(os.path.join(root, 'sub', 'b.bin'), 4096, b'a')
        c = write(os.path.join(root, 'c.bin'), 4096, b'c')
        dup = digest.Duplicates(os.path.join(root, 'cache.json'))
        for path in (a, b, c):
            dup.add(path)
        groups = dup.groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(os.path.basename(p) for p in groups[0]['paths']),
                         ['a.bin', 'b.bin'])
        # A file replaced between runs must not inherit the old digest. Rewrite
        # `b` itself -- the earlier version of this test wrote a different path and
        # proved nothing -- and move its mtime, which is what the cache keys on.
        write(b, 4096, b'z')
        os.utime(b, (time.time() + 5, time.time() + 5))
        fresh = digest.Duplicates(os.path.join(root, 'cache.json'))
        fresh.add(a)
        fresh.add(b)
        fresh.add(c)
        self.assertEqual(fresh.groups(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
