#!/usr/bin/env python3
"""The identify pass's matcher, tested on synthetic records (PLAN §13, §17 Open 5).

No library, no network, no writes: these are the four rules that decide whether a file
gets an album, and each one has a real wrong answer behind it.

    media/.venv/bin/python tests/test_identify_albums.py     (or plain python3: no mutagen here)
"""
import os
import sys
import unittest

MEDIA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MEDIA)
sys.path.insert(0, os.path.join(MEDIA, 'music'))

import identify_albums as ia  # noqa: E402


def rec(path, title=None, album=None, artist=None, albumartist=None, length=200.0):
    """A scanned record. Tags only -- the matcher never opens a file."""
    return {'path': path, 'title': title, 'album': album, 'artist': artist,
            'albumartist': albumartist,
            'info': {'length': length, 'bitrate': 320000, 'sample_rate': 44100, 'channels': 2}}


class Stub:
    """MusicBrainz, replaced by an answer, so the routes are testable offline."""

    def __init__(self, albums=()):
        self._albums = list(albums)
        self.requests = 0
        self.hits = 0

    def albums_for(self, title, artist):
        self.requests += 1
        return list(self._albums), None


def album_entry(title, artists, lengths=(200_000,), kind='Album'):
    return {'album': title, 'group': 'mbid-' + title.lower().replace(' ', '-'),
            'type': kind, 'artists': list(artists), 'lengths': list(lengths)}


def run_plan(routes=('twins',), records=None, budget=0, client=None, dest='/lib'):
    """Plan over synthetic records, with a canned MusicBrainz if the route is named.

    `records` defaults to the three-file fixture in TestDecide.records; callers that pass
    their own records must include the files that are supposed to be the evidence, not
    only the file being filled -- a matcher with nothing to match is a pass that fills
    nothing, which would make every test here vacuously green.
    """
    client = client or Stub([album_entry('All Eyez on Me', ['2Pac'], lengths=[167_000])])
    actions, decisions, counters, lookups = ia.decide(
        dest, records, list(routes), 2.5, client, budget)
    return actions, decisions, counters, lookups, client


class TestTwins(unittest.TestCase):
    """The offline route: the library's own tagged copy answers for its untitled twin."""

    def setUp(self):
        self.target = rec('/lib/Beastie Boys/[Unknown Album]/body movin\u0027.mp3',
                          title="body movin'", artist='Beastie Boys')

    def test_a_twin_by_the_same_artist_fills(self):
        index = ia.build_twins([self.target,
                                rec('/lib/Beastie Boys/Hello Nasty/05.mp3',
                                    title="Body Movin'", artist='Beastie Boys',
                                    album='Hello Nasty')])
        album, reason, _ = ia.twin_answer(index, self.target, 'Beastie Boys', 2.5)
        self.assertEqual(album, 'Hello Nasty')
        self.assertEqual(reason, 'twin')

    def test_a_twin_by_another_artist_is_refused(self):
        """The case that makes the artist test load-bearing.

        'Stuck In The Middle With You' under Bob Dylan is not the Folk Implosion track,
        whatever its title and length say. Title plus duration is a weak pairing on its
        own, and a wrong album is invisible: it does not look like damage in the player.
        """
        index = ia.build_twins([self.target,
                                rec('/lib/Folk Implosion/70\u0027S COLLECTION/03.mp3',
                                    title='Stuck In The Middle With You',
                                    artist='Folk Implosion', album="70'S COLLECTION")])
        bob = rec('/lib/Bob Dylan/[Unknown Album]/Stuck In The Middle With You.mp3',
                  title='Stuck In The Middle With You', artist='Bob Dylan')
        album, reason, _ = ia.twin_answer(index, bob, 'Bob Dylan', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'no-twin')

    def test_a_duration_difference_is_a_different_recording(self):
        index = ia.build_twins([rec('/lib/Beastie Boys/Hello Nasty/05.mp3',
                                    title="Body Movin'", artist='Beastie Boys',
                                    album='Hello Nasty', length=300.0)])
        album, reason, _ = ia.twin_answer(index, self.target, 'Beastie Boys', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'no-twin')

    def test_twins_that_name_different_albums_are_refused(self):
        index = ia.build_twins([
            rec('/lib/a/1.mp3', title='Loser', artist='Beastie Boys', album='Licensed to Ill'),
            rec('/lib/b/2.mp3', title='Loser', artist='Beastie Boys', album='Solid Gold Hits')])
        target = rec('/lib/Beastie Boys/[Unknown Album]/Loser.mp3', title='Loser',
                     artist='Beastie Boys')
        album, reason, seen = ia.twin_answer(index, target, 'Beastie Boys', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'twins-disagree')
        self.assertEqual(len(seen), 2)

    def test_the_fill_is_the_twin_s_exact_string_not_a_normalised_one(self):
        """Whatever the library's own file says is written verbatim, deluxe and all.

        §7.1 makes identity the exact string as tagged. So the pass neither strips
        '(Deluxe Edition)' off the answer nor refuses to use a deluxe twin: it copies the
        string. The case that must refuse is two twins naming *different* albums, which
        `test_twins_that_name_different_albums_are_refused` covers -- one twin has nothing
        to disagree with, and inventing a refusal there would leave a gap to no purpose.
        """
        index = ia.build_twins([rec('/lib/a/1.mp3', title='Hello Nasty', artist='Beastie Boys',
                                    album='Hello Nasty (Deluxe Edition)')])
        album, reason, _ = ia.twin_answer(
            index, rec('/lib/Beastie Boys/[Unknown Album]/x.mp3', title='Hello Nasty',
                       artist='Beastie Boys'), 'Beastie Boys', 2.5)
        self.assertEqual(album, 'Hello Nasty (Deluxe Edition)')
        self.assertEqual(reason, 'twin')

    def test_an_album_artist_twin_counts_when_the_track_artist_does_not(self):
        """A compilation track's twin names the artist only in the album-artist tag."""
        index = ia.build_twins([rec('/lib/a/1.mp3', title='Tomorrow',
                                    artist='Various', albumartist='Beastie Boys',
                                    album='To the 5 Boroughs')])
        target = rec('/lib/Beastie Boys/[Unknown Album]/02 Tomorrow.mp3', title='Tomorrow',
                     artist='Beastie Boys')
        album, _reason, _ = ia.twin_answer(index, target, 'Beastie Boys', 2.5)
        self.assertEqual(album, 'To the 5 Boroughs')


class TestMusicBrainz(unittest.TestCase):
    """The online route, tested against canned WS/2 answers -- no network in a test."""

    def setUp(self):
        self.record = rec('/lib/2Pac/[Unknown Album]/Changes.mp3', title='Changes',
                          artist='2Pac', length=167.0)

    def test_a_single_album_survives(self):
        client = Stub([album_entry('All Eyez on Me', ['2Pac'], lengths=[167_000])])
        album, reason, _ = ia.musicbrainz_answer(client, self.record, '2Pac', 2.5)
        self.assertEqual(album, 'All Eyez on Me')
        self.assertEqual(reason, 'musicbrainz')

    def test_bootleg_durations_are_refused(self):
        """Measured, not imagined: the real search returns fan sets at 177 s and 229 s.

        Neither is the recording, and the duration test is the only thing in the route that
        knows that. Removing it would fill this file with "Grandmaster: DJ Set, Issue 3".
        """
        client = Stub([album_entry('Grandmaster: DJ Set, Issue 3', ['2Pac'], lengths=[177_000]),
                       album_entry('Live at the Roxy', ['2Pac'], lengths=[229_000])])
        album, reason, seen = ia.musicbrainz_answer(client, self.record, '2Pac', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'mb-duration')
        self.assertEqual(len(seen), 2)

    def test_two_surviving_albums_are_refused(self):
        client = Stub([album_entry('All Eyez on Me', ['2Pac'], lengths=[167_000]),
                       album_entry('Greatest Hits', ['2Pac'], lengths=[167_000])])
        album, reason, _ = ia.musicbrainz_answer(client, self.record, '2Pac', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'mb-multiple-albums')

    def test_editions_of_one_release_are_one_album(self):
        """The same title twice is not two winners -- that is one album and two discs."""
        client = Stub([album_entry('All Eyez on Me', ['2Pac'], lengths=[167_000]),
                       album_entry('All Eyez on Me', ['2Pac'], lengths=[167_000])])
        album, reason, _ = ia.musicbrainz_answer(client, self.record, '2Pac', 2.5)
        self.assertEqual((album, reason), ('All Eyez on Me', 'musicbrainz'))

    def test_a_non_album_release_is_refused(self):
        client = Stub([album_entry('Changes (Single)', ['2Pac'], kind='Single')])
        album, reason, _ = ia.musicbrainz_answer(client, self.record, '2Pac', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'mb-no-album-release')

    def test_a_release_by_another_artist_is_refused(self):
        client = Stub([album_entry('Changes', ['Aaliyah'], lengths=[167_000])])
        album, reason, _ = ia.musicbrainz_answer(client, self.record, '2Pac', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'mb-artist-mismatch')

    def test_nothing_found_is_refused_not_guessed(self):
        album, reason, _ = ia.musicbrainz_answer(Stub([]), self.record, '2Pac', 2.5)
        self.assertIsNone(album)
        self.assertEqual(reason, 'mb-no-match')


class TestArtistAgreement(unittest.TestCase):
    def test_credit_forms_agree(self):
        for left, right in (('Beastie Boys', 'beastie boys'),
                            ('Barrington Levy', 'Barrington Levy feat. Black Uhuru'),
                            ('Outkast', 'OutKast & André 3000')):
            self.assertTrue(ia.artists_agree(left, right), f'{left!r} vs {right!r}')

    def test_different_artists_do_not(self):
        for left, right in (('Bob Dylan', 'Folk Implosion'), ('2Pac', 'Aaliyah')):
            self.assertFalse(ia.artists_agree(left, right), f'{left!r} vs {right!r}')

    def test_an_empty_artist_agrees_with_nothing(self):
        """An empty string must not match the empty reading of some other string, or every
        untagged file would pair with every other one."""
        self.assertFalse(ia.artists_agree('', ''))
        self.assertFalse(ia.artists_agree(None, 'Beastie Boys'))


class TestWinner(unittest.TestCase):
    def test_one_identity_spelled_two_ways_picks_the_common_spelling(self):
        album, _ = ia._winner(['Hello Nasty', 'Hello Nasty', 'hello nasty'])
        self.assertEqual(album, 'Hello Nasty')

    def test_two_identities_have_no_winner(self):
        album, distinct = ia._winner(['Hello Nasty', 'Solid Gold Hits'])
        self.assertIsNone(album)
        self.assertEqual(len(distinct), 2)


class TestPartialUndo(unittest.TestCase):
    """`--undo --route` takes one route back and leaves the rest of the run in place.

    Needed because routes are trusted unequally: a run that mixed a good route with a bad
    one must not have to be undone all-or-nothing, which is how badly a wrong route can be
    limited after it has already written.
    """

    rows = [{'path': '/a', 'route': 'twins'}, {'path': '/b', 'route': 'folder'},
            {'path': '/c'}]

    def test_narrowing_keeps_only_the_named_route(self):
        self.assertEqual([row['path'] for row in ia.select_route(self.rows, 'folder')], ['/b'])

    def test_no_named_route_is_the_whole_run(self):
        self.assertEqual(ia.select_route(self.rows, None), self.rows)

    def test_a_row_with_no_route_stamped_is_never_swept_in(self):
        """/c was written by something that did not say what: a narrowed undo must skip it."""
        self.assertNotIn('/c', [row['path'] for row in ia.select_route(self.rows, 'twins')])

    def test_an_empty_narrowing_is_visible_to_the_caller(self):
        """Returning [] is what lets do_undo refuse instead of 'restored 0 files' happily."""
        self.assertEqual(ia.select_route(self.rows, 'musicbrainz'), [])


class TestFolderRoute(unittest.TestCase):
    """The route that reads the room, with the two guards this library taught it.

    ``Artist/[Unknown Album]/`` is a junk drawer and not an album folder, so a folder needs
    two tagged files before it may speak, and may not claim an album smaller than itself.
    Both guards are answers to a weld that happened on the live library.
    """

    def setUp(self):
        self.folder = '/lib/Dillinja/[Unknown Album]'
        self.tagged = [rec(f'{self.folder}/01 - So Damn Tuff.mp3', title='So Damn Tuff',
                           artist='Dillinja', album='171.4'),
                       rec(f'{self.folder}/02 - Twit Two.mp3', title='Twit Two',
                           artist='Dillinja', album='171.4')]

    def plan(self, targets, copies=8):
        """Plan with ``171.4`` also holding ``copies`` files in its own album folder.

        Sized on purpose: the folder-size guard has its own test below, and a fixture that
        tripped it by accident would pass for the wrong reason.
        """
        context = self.tagged + [
            rec(f'/lib/Dillinja/171.4/{n:02} - track.mp3', title=f'Track {n}',
                artist='Dillinja', album='171.4') for n in range(copies)]
        return run_plan(routes=('folder',), records=context + list(targets))

    def test_tagged_siblings_name_the_rest_of_the_folder(self):
        """The case twins cannot answer: unique tracks, no copy anywhere else."""
        targets = [rec(f'{self.folder}/Live or Die.mp3', title='Live or Die', artist='Dillinja'),
                   rec(f'{self.folder}/Love is Not a Game.mp3', title='Love is Not a Game',
                       artist='Dillinja')]
        actions, _d, counters, _l, _c = self.plan(targets)
        self.assertEqual(len(actions), 2)
        self.assertEqual({a['album'] for a in actions.values()}, {'171.4'})
        self.assertEqual(counters['fill: folder'], 2)

    def test_one_tagged_sibling_is_not_enough(self):
        """``Liquido/[Unknown Album]/``: one tagged file named all 23 of them ``LIQUIDO``,
        and four of those files are each numbered 01 -- four singles, not one album."""
        lonely = self.tagged[:1]
        targets = [rec(f'{self.folder}/Swing It.mp3', title='Swing It', artist='Liquido'),
                   rec(f'{self.folder}/The Joke Is On You.mp3', title='The Joke Is On You',
                       artist='Liquido')]
        actions, _d, counters, _l, _c = run_plan(routes=('folder',), records=lonely + targets)
        self.assertEqual(actions, {})
        self.assertEqual(counters['refuse: one-tagged-sibling'], 2)

    def test_a_folder_bigger_than_the_album_it_claims_refuses(self):
        """``Canibus/[Unknown Album]/`` wanted to add 39 files to a 17-track album: an album
        does not grow by more than itself. Same records, one padding file set each way."""
        targets = [rec(f'{self.folder}/Drawer {n}.mp3', title=f'Drawer {n}', artist='Canibus')
                   for n in range(3)]
        crowded, _d, counters, _l, _c = self.plan(targets, copies=0)    # album = 2 files
        self.assertEqual(crowded, {})
        self.assertEqual(counters['refuse: folder-bigger-than-the-album'], 3)
        roomy, _d, counters, _l, _c = self.plan(targets, copies=4)      # album = 10 files
        self.assertEqual(len(roomy), 3)
        self.assertEqual(counters['fill: folder'], 3)

    def test_a_folder_naming_two_albums_refuses(self):
        """Two albums in one folder is the owner's filing, not this pass's to decide."""
        second_album = rec(f'{self.folder}/00 - intro.mp3', title='Intro', artist='Dillinja',
                           album='Diecast')
        targets = [rec(f'{self.folder}/Twist Em Out.mp3', title='Twist Em Out',
                       artist='Dillinja'),
                   rec(f'{self.folder}/Weapon Of Choice.mp3', title='Weapon Of Choice',
                       artist='Dillinja')]
        actions, decisions, counters, _l, _c = run_plan(
            routes=('folder',), records=self.tagged + [second_album] + targets)
        self.assertEqual(actions, {})
        self.assertEqual(counters['refuse: siblings-disagree'], 2)
        self.assertTrue(all(row['candidates'] for row in decisions),
                        'a refusal must say which two albums it could not choose between')

    def test_an_album_less_sibling_is_not_counted_against_the_folder(self):
        """Untagged files do not vote: they are the ones being filled."""
        targets = [rec(f'{self.folder}/Live or Die.mp3', title='Live or Die', artist='Dillinja'),
                   rec(f'{self.folder}/Weapon Of Choice.mp3', title='Weapon Of Choice',
                       artist='Dillinja'),
                   rec(f'{self.folder}/Unknown.mp3', title='Unknown Thing', artist='Dillinja')]
        actions, _d, _c, _l, _c2 = self.plan(targets)
        self.assertEqual(len(actions), 3)

    def test_the_folder_route_is_not_consulted_when_not_named(self):
        """--routes twins means twins: no silent fallback into a weaker route."""
        target = rec(f'{self.folder}/Live or Die.mp3', title='Live or Die', artist='Dillinja')
        actions, _d, counters, _l, _c = run_plan(routes=('twins',), records=[*self.tagged,
                                                                            target])
        self.assertEqual(actions, {})
        self.assertEqual(counters['refuse: no-twin'], 1)


class TestRoutesDisagree(unittest.TestCase):
    """Two routes naming different albums is no winner, not a tie to break by precedence."""

    def build(self, twin_album, folder_album):
        folder = '/lib/Dillinja/[Unknown Album]'
        return [
            rec(f'{folder}/Live or Die.mp3', title='Live or Die', artist='Dillinja'),
            rec(f'{folder}/00 - catalogue.mp3', title='Catalogue', artist='Dillinja',
                album=folder_album),
            rec(f'{folder}/09 - sleeve.mp3', title='Sleeve', artist='Dillinja',
                album=folder_album),
            rec('/lib/Dillinja/Other/01 Live or Die.mp3', title='Live or Die',
                artist='Dillinja', album=twin_album),
        ]

    def test_a_conflict_is_refused_and_both_answers_are_kept(self):
        actions, decisions, counters, _l, _c = run_plan(
            routes=('twins', 'folder'), records=self.build('171.4', 'Diecast'))
        self.assertEqual(actions, {})
        self.assertEqual(counters['refuse: routes-disagree'], 1)
        self.assertEqual(sorted(decisions[0]['candidates']),
                         ['folder:Diecast', 'twins:171.4'])

    def test_two_routes_agreeing_fill_once_and_keep_the_stronger_spelling(self):
        """Corroboration is recorded, and the stronger route's spelling wins -- the exact
        string is the identity, so whose spelling it is matters (§7.1)."""
        records = self.build('Load', 'LOAD')
        actions, decisions, counters, _l, _c = run_plan(
            routes=('twins', 'folder'), records=records)
        self.assertEqual(counters['fill: twins'], 1)
        self.assertEqual(counters['would fill: folder'], 1)
        filled = [row for row in decisions if row['verdict'] == 'fill']
        self.assertEqual(filled[0]['album'], 'Load', 'the twins route spells it, not the folder')
        self.assertEqual(filled[0]['also'], ['folder'], 'and the run says which routes agreed')


class TestDecide(unittest.TestCase):
    """End-to-end plan over synthetic records: who is eligible, and who is left alone."""

    def setUp(self):
        self.records = [
            rec('/lib/Beastie Boys/[Unknown Album]/body movin\u0027.mp3',
                title="body movin'", artist='Beastie Boys'),
            rec('/lib/Beastie Boys/Hello Nasty/05.mp3', title="Body Movin'",
                artist='Beastie Boys', album='Hello Nasty'),
            rec('/lib/2Pac/[Unknown Album]/Changes.mp3', title='Changes', artist='2Pac',
                length=167.0),
        ]

    def test_the_offline_route_fills_and_asks_the_network_nothing(self):
        actions, _d, _c, lookups, client = run_plan(records=self.records)
        self.assertEqual(lookups, 0)
        self.assertEqual(client.requests, 0)
        self.assertEqual(sorted(os.path.basename(path) for path in actions),
                         ["body movin'.mp3"])

    def test_a_placeholder_album_counts_as_absent(self):
        """A timestamped placeholder is still no album: matching on it welds artists."""
        records = [rec('/lib/Black Keys/[Unknown Album 01 27 06 27 53 pm]/01.mp3',
                       title='Lonely Boy', artist='Black Keys', length=200.0),
                   rec('/lib/a/1.mp3', title='Lonely Boy', artist='Black Keys',
                       album='Brothers', length=200.0)]
        actions, _d, _c, _l, _cl = run_plan(records=records)
        self.assertEqual(list(actions.values())[0]['album'], 'Brothers')

    def test_a_real_album_is_never_overwritten(self):
        records = [rec('/lib/Beastie Boys/Hello Nasty/05.mp3', title="Body Movin'",
                       artist='Beastie Boys', album='Hello Nasty', length=200.0)]
        actions, _d, counters, _l, _cl = run_plan(records=records)
        self.assertEqual(actions, {})
        self.assertEqual(counters['skipped: album already tagged'], 1)

    def test_a_file_under_an_untrusted_top_is_left_alone(self):
        """`_Unsorted/whatever/x.mp3` has no artist identity to key a lookup on."""
        records = [rec('/lib/_Unsorted/Junk/01.mp3', title='Lonely Boy', length=200.0),
                   rec('/lib/a/1.mp3', title='Lonely Boy', artist='Black Keys',
                       album='Brothers', length=200.0)]
        actions, _d, counters, _l, _cl = run_plan(records=records)
        self.assertEqual(actions, {})
        self.assertEqual(counters['skipped: no artist directory'], 1)

    def test_a_title_that_is_a_placeholder_is_not_a_title(self):
        records = [rec('/lib/Black Keys/[Unknown Album]/01.mp3', title='Unknown Title',
                       artist='Black Keys', length=200.0)]
        actions, _d, counters, _l, _cl = run_plan(records=records)
        self.assertEqual(actions, {})
        self.assertEqual(counters['skipped: no title'], 1)

    def test_the_lookup_budget_is_honoured(self):
        """--limit is what makes the pilot honest: it caps questions, not answers."""
        actions, _d, _c, lookups, client = run_plan(routes=('twins', 'musicbrainz'),
                                                    records=self.records, budget=1)
        self.assertEqual(lookups, 1)
        self.assertEqual(client.requests, 1)
        self.assertIn('All Eyez on Me', [action['album'] for action in actions.values()])

    def test_both_routes_and_every_refusal_is_recorded(self):
        actions, decisions, _c, _l, _cl = run_plan(routes=('twins', 'musicbrainz'),
                                                   records=[
                                                            self.records[0],
                                                            self.records[1],
                                                            rec('/lib/Nobody At All/[Unknown '
                                                                'Album]/unique.mp3',
                                                                title='Zzqq Xyyy', length=200.0)])
        self.assertEqual(len(actions), 1)
        verdicts = {row['verdict'] for row in decisions}
        self.assertEqual(verdicts, {'fill', 'refuse'})
        refused = [row for row in decisions if row['verdict'] == 'refuse']
        self.assertTrue(refused[0]['reason'], 'a refusal without a reason is a silent gap')


if __name__ == '__main__':
    unittest.main()
