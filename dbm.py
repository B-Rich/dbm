#!/usr/bin/env python

#    dbm : A music library tool

#    Dan Davison davison@stats.ox.ac.uk
#
#   dbm does a variety of useful things with a library of music
#   files:
#   - It generates random similar-music playlists for every artist in
#     the library.
#   - It creates a system of links to music by similar
#     artists, thus providing suggestions when choosing music to listen
#     to.
#   - It can report on albums that have untagged files or missing tracks.
#   - It can create lists of recommended similar artists that are not in
#     your library.
#   - It creates an alphabetical index of links to artists in your
#     music library

#    Please contact me [davison at stats dot ox dot ac dot uk] with
#    any questions about this software.

#    ---------------------------------------------------------------------
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

#    You should have received a copy of the GNU General Public License
#    along with this program; if not, a copy is available at
#    http://www.gnu.org/licenses/gpl.txt
#    ---------------------------------------------------------------------

from __future__ import with_statement
import sys, os, re, time, urllib, codecs
import random, csv, math
import optparse, logging
from cmdline import CommandLineApp
import pylast
import track
from util import *
__version__ = '0.9.1'
__progname__ = 'dbm'

def elog(msg):
    # logfile is an object created by codecs.open(<path>, 'utf-8', <mode>)
    # under GUI, stdout is also an object created by codecs.open(<path>, 'utf-8', <mode>)
    try:
        settings.logfile.write(msg + '\n')
#        print(msg)
    except:
        settings.logfile.write('ERROR: Failed to write elog message\n')
#        print('ERROR: Failed to write elog message\n')

class Settings(object):
    various_artists_mbid = '89ad4ac3-39f7-470e-963a-56509c546377'
    lastfm = dict(api_key = 'a271d46d61c8e0960c50bec237c9941d',
                  api_secret = '680457c03625980f61e88c319c218d53',
#                  session_key = 'b9815e428303086842b14822296e5cff')
                  session_key = '')

    mbid_regexp = re.compile('[0-9a-fA-F]'*8 + '-' + \
                                 '[0-9a-fA-F]'*4 + '-' + \
                                 '[0-9a-fA-F]'*4 + '-' + \
                                 '[0-9a-fA-F]'*4 + '-' + \
                                 '[0-9a-fA-F]'*12)
    def __init__(self, options=None):
        self.gui = False
        if options:
            attributes = [a for a in dir(options) if a[0] != '_']
            for attr in attributes:
                setattr(self, attr, getattr(options, attr))

    def show(self):
        public = filter(lambda(x): x[0] != '_', dir(self))
        noshow = ['read_file', 'read_module', 'show', 'ensure_value', 'mbid_regexp']
        for attr_name in public:
            if attr_name in noshow: continue
            attr = getattr(self, attr_name)
            print('%s %s %s' % (repr(attr_name), type(attr), attr))

class Dbm(CommandLineApp):

    def __init__(self):
        CommandLineApp.__init__(self)

        op = self.option_parser
        usage = 'usage: [options] %s -i %s -o %s' % (
            __progname__,
            os.path.sep.join(['location','of','music', 'library']),
            os.path.sep.join(['folder','to','receive','output']))
        op.set_usage(usage)

        op.add_option('-i', '--library', dest='libdir', type='string', default=None,
                      help='Location of root of music library')

        op.add_option('-o', '--outdir', dest='outdir', type='string', default='.',
                      help='Folder to receive output, defaults to current folder.')

        # op.add_option('-u', '--update', dest='update', default=False, action='store_true',
        #               help='Don\'t re-scan whole library; instead update saved dbm data base.')

        op.add_option('-f', '--libfile', dest='savefile', type='string', default='library.dbm',
                      help="Saved library file, defaults to 'library.dbm'")

        op.add_option('-r', '--rockbox', dest='path_to_rockbox', type='string', default=None,
                      help='Location of rockbox digital audio player.')

        op.add_option('', '--mintracks', dest='minArtistTracks', default=0, type='int',
                      help='Playlists and linkfiles will only be generated for artists with' + \
                          ' more than this number of tracks in the library.')

        op.add_option('', '--numtries', dest='numtries', default=3, type='int',
                      help='Number of times to attempt web query for an artist before giving up.')

        op.add_option('', '--noweb', dest='query_lastfm', default=True, action='store_false',
                      help="Don't query last.fm similar artists.")

        op.add_option('-n', '', dest='create_files', default=True, action='store_false',
                      help='Don\'t create any playlists or link files')

        op.add_option('', '--version', dest='show_version', default=False, action='store_true',
                      help='Print out version information and exit')

        op.add_option('', '--show-library', dest='show_tree', default=False, action='store_true',
                      help='Print sparse representation of library, and exit')

        op.add_option('', '--show-tracks', dest='show_tracks', default=False, action='store_true',
                      help='Include track information when using --show')

        op.add_option('', '--show-artists', dest='show_artists', default=False, action='store_true',
                      help='Print information on artists in library, and exit')

        op.add_option('-s', '--musicspace', dest='music_space_file', type='string', default=None,
                      help='Music space file')

        op.add_option('', '--show-musicspace', dest='show_musicspace', default=False, action='store_true',
                      help="Print summary of neighbouring artists in musicspace, and exit")

        op.add_option('', '--dropoff', dest='musicspace_dropoff_param', type='float', default=3.0,
                      help="Parameter controlling rate at which probability of inclusion falls away with distance in music space. When generating playlists for artist X, a value of 0 means that all other artists will be included with equal probability; a value of more than 5 or so means that you'll rarely get anybody but X. Default is 3.0")
        op.add_option('', '--create-musicspace-skeleton', dest='write_music_space', default=False,
                      action='store_true',
                      help='create skeleton music space spreadsheet file and exit')

        op.add_option('-t', '--target', dest='target', default='rockbox', type='string',
                      help="Specify target platform: defaults to rockbox; " +\
                          "in the future you will be able to use --target=native " +\
                          "to create playlists and links for use on the local machine.")

        # self.log.setLevel(logging.DEBUG)

    def check_settings(self):
        if not settings.savefile and not settings.libdir:
            raise DbmError('Either -f LIBFILE, or -i LIBDIR, or both, must be given' % settings.libdir)

        if settings.libdir:
            if not (os.path.isdir(settings.libdir) or os.path.islink(settings.libdir)):
                raise DbmError('library folder %s is not a valid folder' % settings.libdir)

        if settings.savefile:
            if not (os.path.isfile(settings.savefile) or os.path.islink(settings.savefile)):
                raise DbmError('Saved library file %s is not valid' % settings.savefile)

    def main(self):
        global settings
        global root

        settings = Settings(dbm.options)
        decode_strings(settings)

        # dbm_dir = os.path.join(settings.outdir, '%s_files' % __progname__)
        for d in [settings.outdir]:
            if not os.path.exists(d): os.mkdir(d)
        # settings.savefile = os.path.join(dbm_dir, 'library.dbm')
        settings.logfile = codecs.open('dbmlog.txt', 'w', 'utf-8')
        settings.musicspace_ready = False
        settings.musicspace_dimension = None
        settings.albumartdir = '/tmp/albumart'

        if settings.show_version:
            log('dbm version %s' % __version__)
            self.exit(2)

        elog('dbm version %s' % __version__)
        elog(time.ctime())

        if settings.libdir:
            # settings.libdir = os.path.splitdrive(settings.libdir)[1]
            settings.libdir = os.path.abspath(settings.libdir) # also strips any trailing '/'

        if settings.path_to_rockbox:
            settings.path_to_rockbox = os.path.abspath(settings.path_to_rockbox) # also strips any trailing '/'

        self.check_settings()
        settings.show()

        if not settings.libdir:
            print 'loading saved library'
            log('Loading saved library file %s' % settings.savefile)
            try:
                root = load_pickled_object(settings.savefile)
                # Pickles made by previous versions may have stored
                # paths as strings a.o.t. unicode
                if isinstance(root.path, str):
                    root.decode_strings()
            except:
                raise DbmError('Could not load saved dbm library file %s' % settings.savefile)
            log('Loaded library with %d artists' % len(root.artists))
            if settings.libdir:
                log('Updating library subtree rooted at %s' % settings.libdir)
                new_subtree = Root(settings.libdir, None)
                root.graft_subtree(new_subtree)
            root.artists = {}
            root.artistids = {}
            root.artistnames = {}
        else:
            log('Scanning library rooted at %s' % settings.libdir)
            root = Root(settings.libdir, None)

        if settings.create_files and settings.libdir:
            # was and (settings.libdir or not settings.update):
            log('Saving library to %s' % settings.savefile)
            pickle_object(root, settings.savefile)

        settings.libdir = None # Not used subsequently! Use root.path instead.

        log('Constructing database of artists in library')
        root.create_artist_name_to_mbid_mapping()
        root.set_dbm_artistids()
        root.create_artists()

        if settings.show_tree or settings.show_tracks:
            root.show()
            self.exit(0)

        if settings.show_artists:
            root.show_artists()
            self.exit(0)

        if settings.write_music_space:
            with codecs.open('__musicspace.csv', 'w', 'utf-8') as f:
                root.write_musicspace_file(f)

        if settings.music_space_file:
            log('Populating musicspace')
#            with codecs.open(settings.music_space_file, 'r', 'utf-8') as f:
            with open(settings.music_space_file, 'r') as f:
                root.populate_musicspace(f, settings.musicspace_dropoff_param)
            settings.musicspace_ready = True

        if settings.show_musicspace:
            root.show_musicspace()
            self.exit(0)

        if settings.query_lastfm:
            log('Retrieving similar artist lists from last.fm')
        root.download_lastfm_data() # Call this even if not making web queries

        if settings.create_files:
            log('Saving library to %s' % settings.savefile)
            pickle_object(root, settings.savefile)

            log('Creating playlists and rockbox database')

            links_dir = os.path.join(settings.outdir, 'Links')
            lastfm_similar_links_dir = os.path.join(links_dir, 'Last.fm_Similar')
            musicspace_similar_links_dir = os.path.join(links_dir, 'Musicspace_Similar')
            az_links_dir = os.path.join(links_dir, 'A-Z')

            playlists_dir = os.path.join(settings.outdir, 'Playlists')
            single_artists_playlists_dir = os.path.join(playlists_dir, 'Single_Artists')
            all_artists_playlists_dir = os.path.join(playlists_dir, 'All_Artists')
            lastfm_similar_playlists_dir = os.path.join(playlists_dir, 'Last.fm_Similar')
            musicspace_similar_playlists_dir = os.path.join(playlists_dir, 'Musicspace_Similar')

            rec_dir = os.path.join(settings.outdir, 'Recommended')

            for d in [links_dir, rec_dir, playlists_dir,
                      az_links_dir, lastfm_similar_links_dir, musicspace_similar_links_dir,
                      single_artists_playlists_dir, all_artists_playlists_dir,
                      lastfm_similar_playlists_dir, musicspace_similar_playlists_dir]:
                if not os.path.exists(d):
                    os.mkdir(d)

            root.write_lastfm_similar_artists_linkfiles(lastfm_similar_links_dir)
            if settings.musicspace_ready:
                root.write_musicspace_similar_artists_linkfiles(musicspace_similar_links_dir)
            root.write_lastfm_recommended_linkfiles(rec_dir)
            root.write_a_to_z_linkfiles(az_links_dir)

            if settings.musicspace_ready:
                root.write_musicspace_similar_artists_playlists(musicspace_similar_playlists_dir)
            root.write_lastfm_similar_artists_playlists(lastfm_similar_playlists_dir)
            root.write_single_artists_playlists(single_artists_playlists_dir)
            root.write_all_artists_playlist(all_artists_playlists_dir)

            log('Done')
            self.exit(0)

    def usage(self):
        print('dbm version %s' % __version__)
        print('Use -i and -o options to specify location of music library and output folder. E.g.\n')

        if os.name == 'posix':
            print('./dbm.py -i /media/ipod/music -o ~/music/ipod-dbm-output')
        else:
            print('python dbm.py -i E:\Music -o dbm-output')

        print('If you want to re-use saved database files in an existing output')
        print('directory rather than scanning your music library again, use -u.')
        print('To see information on available options, use -h.')
        self.exit(2)

    def exit(self, code):
        settings.logfile.close()
        sys.exit(code)

class Node(object):
    """A tree representation of a music library."""
    def __init__(self, path, parent):
        self.path = path
        self.parent = parent
        self.subtrees = set([])
        self.tracks = []
        self.dbm_artistids = {}
        self.grow()

    def grow(self):
        # contents = [x.decode('utf-8') for x in os.listdir(self.path)]

        # print 'self.path %s unicode' % isinstance(self.path, unicode)
        # x = filter(lambda(xi): not isinstance(xi, unicode), os.listdir(self.path))
        # print 'not unicode:'
        # print x

        paths = os.listdir(self.path)
        # Bjork and Sigur Ros are not unicode despite self.path being unicode: ???
        paths = filter(lambda(x): isinstance(x, unicode), paths)

        paths = [os.path.join(self.path, x) for x in paths]

        if not os.path.exists(os.path.join(self.path, '.ignore')):
            if not settings.quiet: log(self.path)
            musicpaths = filter(track.is_music, paths)
            self.tracks = filter(lambda(t): t.valid, [track.Track(p) for p in musicpaths])
        for d in filter(os.path.isdir, paths):
            self.subtrees.add(Node(d, self))

    def is_pure_subtree(self):
        return len(self.dbm_artistids) == 1

    def show(self):
        print('%s %d %s' % (self.path.ljust(75), len(self.dbm_artistids), self.dbm_artistids))
        if settings.show_tracks:
            for t in self.tracks:
                t.show()
        for subtree in self.subtrees:
            subtree.show()

    def create_artist_name_to_mbid_mapping(self):
        """artistids is a dict of artistids keyed by artistnames, that
        is maintained at the root of the tree in an attempt to
        synonymise artists when some of their music lacks musicbrainz
        artistid tags."""
        for t in self.tracks:
            for aid, aname in [(t.artistid,     t.artistname),
                               (t.albumartistid, t.albumartistname)]:
                if aid and aname:
                    dbm_aname = canonicalise_name(aname)
                    if not root.artistids.has_key(dbm_aname):
                        root.artistids[dbm_aname] = aid
                    elif root.artistids[dbm_aname] != aid:
                        elog('artistname "%s" associated with multiple artist IDs: "%s" "%s"\n' %
                            (aname, aid, root.artistids[dbm_aname]))

        for subtree in self.subtrees:
            subtree.create_artist_name_to_mbid_mapping()

    def set_dbm_artistids(self):
        """Each node has a dict node.dbm_artistids containing the counts of
        tracks by each artist in that subtree. This function traverses the
        tree to set those dicts. The dicts are keyed by dbm_artistids,
        which are MBIDs where available and otherwise artist names. This
        function also sets the dbm_artistid of the music."""

        # The design of this function is key to the behaviour of dbm

        # Set dbm_artistid and dbm_albumartistid of tracks
        for t in self.tracks:
            for aid, aname, attr in [(t.artistid, t.artistname, 'dbm_artistid'),
                                     (t.albumartistid, t.albumartistname, 'dbm_albumartistid')]:
                dbm_aid = root.make_dbm_artistid(aid, aname)
                # If MBID and name tags are lacking, this track does
                # not contribute an artist
                if dbm_aid:
                    setattr(t, attr, dbm_aid)
                    if not root.artistnames.has_key(dbm_aid):
                        root.artistnames[dbm_aid] = []
                    if aname:
                        root.artistnames[dbm_aid].append(aname)

        # Determine if we are in a pure directory
        # FIXME this is strange
        dbm_aids = unique(filter(None, [t.dbm_artistid for t in self.tracks]))
        if len(dbm_aids) == 1: self.dbm_artistids = {dbm_aids[0]:1}

        for subtree in self.subtrees:
            subtree.set_dbm_artistids()
            self.dbm_artistids = table_union(self.dbm_artistids, subtree.dbm_artistids)

    def set_track_artists(self):
        for t in self.tracks:
            # All tracks are 'valid', i.e. have artist MBID or artist
            # name, hence must have dbm_artistid
            t.artist = root.artists[t.dbm_artistid]
            if t.dbm_albumartistid:
                t.albumartist = root.artists[t.dbm_albumartistid]
        for subtree in self.subtrees:
            subtree.set_track_artists()

    def download_albumart(self):
        def isok(track):
            if not track.artistname or not track.releasename:
                return False
            aaid = track.dbm_albumartistid
            if aaid:
                if aaid != track.dbm_artistid:
                    return False
                if aaid == settings.various_artists_mbid:
                    return False
            return True

        tracks = filter(isok, self.tracks)
        art_rel = set([(t.artistname, t.releasename) for t in tracks])
        # FIXME: should check if any of those tuples have different
        # artist but same releasename.

        # art_rel = filter(lambda(ar): ar[0] and ar[1], art_rel)
        for ar in art_rel:
            dest = os.path.join(settings.albumartdir,
                                rockbox_clean_name('-'.join(ar)) + '.jpg')
            if os.path.exists(dest):
                continue
            url = None
            gotit = False
            album = pylast.Album(ar[0], ar[1], **settings.lastfm)
            try:
                url = album.get_image_url() # it's unicode
            except pylast.ServiceException, e:
                msg = 'Error obtaining album art URL for %s: %s' % (unicode(ar), e)
                elog(msg)
            except:
                msg = 'Error obtaining album art URL for %s' % unicode(ar)
                elog(msg)
            if url:
                try:
                    urllib.urlretrieve(url, dest)
                    gotit = True
                except:
                    msg = 'Error downloading album art from %s' % url
                    elog(msg)
            log("%s: %s %s" % (ar[0], ar[1], '' if gotit else '     Failed'))

        for subtree in self.subtrees:
            subtree.download_albumart()

    def set_artist_subtrees_and_tracks(self):
        if self.is_pure_subtree():
            if not self.parent or not self.parent.is_pure_subtree(): # At root of a maximal pure subtree
                dbm_aid = self.dbm_artistids.keys()[0]
                artist = root.artists[dbm_aid]
                artist.subtrees.add(ArtistNode(self, artist, artist, None))
        for t in self.tracks:
            if not self.dbm_artistids: # FIXME: this means non-pure folder, but is not clear
                if self not in [anode.node for anode in t.artist.subtrees]:
                    t.artist.subtrees.add(ArtistNode(self, t.artist, t.albumartist, t.releasename))
            t.artist.tracks.append(t)
            if t.albumartist:
                t.albumartist.tracks_as_albumartist.append(t)
        for subtree in self.subtrees:
            subtree.set_artist_subtrees_and_tracks()

    def gather_subtree_tracks(self, node):
        """Add all tracks in subtree to self.tracks"""
        node.subtree_tracks.extend(self.tracks)
        for subtree in self.subtrees:
            subtree.gather_subtree_tracks(node)

    def decode_strings(self):
        self.path = self.path.decode('utf-8')
        for t in self.tracks:
            decode_strings(t)
        for s in self.subtrees:
            s.decode_strings()

    def delete_attributes(self, attr_names):
        for attr_name in attr_names:
            if (hasattr(self, attr_name)):
                setattr(self, attr_name, None)
        for subtree in self.subtrees:
            subtree.delete_attributes(attr_names)

    def __cmp__(self, other):
        return cmp(self.path, other.path)

class Root(Node):
    """The root node has and does certain things that the internal
    nodes don't."""
    def __init__(self, path, parent):
        Node.__init__(self, path, parent)
        # artistids is a dict of artist MBIDs, keyed by dbm_artistid
        self.artistids = {}
        # artistnames is a dict of artist names, keyed by dbm_artistid
        self.artistnames = {}
        # artists is a dict of Artist instances, keyed by dbm_artistid
        self.artists = {}
        self.simartists = {}
        self.subtree_tracks = []
        self.tags = {}

    def make_dbm_artistid(self, mbid, name):
        """Construct the dbm artist id for this (mbid, name) pair. If
        the mbid is present, then it is used as the dbm id. Otherwise,
        a look-up is performed to see if an mbid has been encountered
        associated with the name, elsewhere in the library. If not,
        then the name is used as the dbm id."""
        if mbid: return mbid
        dbm_name = canonicalise_name(name)
        if self.artistids.has_key(dbm_name):
            return self.artistids[dbm_name]
        return dbm_name

    def lookup_dbm_artistid(self, (mbid, name)):
        """Return the dbm artist id, if any, that is currently in use
        for this (mbid, name) pair."""
        if mbid and self.artists.has_key(mbid): # ! added mbid 090512
            return mbid
        dbm_name = canonicalise_name(name)
        if self.artists.has_key(dbm_name):
            return dbm_name
        return None

    def lookup_dbm_artist(self, (mbid, name)):
        """Return the dbm artist, if any, that is currently in use for
        this (mbid, name) pair. I think this should be altered to use
        tuple indexing somehow, but it's not totally trivial."""
        if mbid and self.artists.has_key(mbid): # ! added mbid 090512
            return self.artists[mbid]
        dbm_name = canonicalise_name(name)
        if self.artists.has_key(dbm_name):
            return self.artists[dbm_name]
        return None

    def create_artists(self):
        dbm_artistids = self.artistnames.keys()
        self.artists = dict(zip(dbm_artistids,
                                map(Artist, dbm_artistids)))
        self.set_track_artists()
        self.set_artist_subtrees_and_tracks()
        self.sanitise_artists()

    def sanitise_artists(self):
        bad = []

        for dbm_aid in self.artists:
            a = self.artists[dbm_aid]
            if not a.id:
                elog('Artist %s has no id: deleting\n' % \
                         a.name if a.name else '?')
                bad.append(dbm_aid)
                continue
            if not a.name:
                elog('Artist %s has no name: deleting\n' % a.id)
                bad.append(dbm_aid)
                continue
            if not a.tracks and not a.tracks_as_albumartist:
                msg = "Artist %s has no tracks: deleting\n" % a.name
                msg += "This shouldn't happen, please email the saved library file %s " % settings.savefile
                msg += "to davison@stats.ox.ac.uk\n"
                elog(msg)
                bad.append(dbm_aid)
                continue
#             if not a.subtrees:
#                 print('Artist %s has no subtrees.' % a.name.encode('utf-8'))
            a.unite_spuriously_separated_subtrees()

        for dbm_aid in bad:
            # Deleting artist but not subtree here may be a bug
            self.artists.pop(dbm_aid)

    def download_lastfm_data(self):
        for artist in sorted(self.artists.values()):
            if artist.subtrees:
                artist.download_lastfm_data()
        self.tabulate_tags()
        
    def tabulate_tags(self):
        self.tags = {}
        if self.tags:
            elog('root.tags should have been empty')
            self.tags = {}
        for artist in self.artists.values():
            tags = artist.tags[0:4]
            for tagname in [t.name for t in tags]:
                if not root.tags.has_key(tagname.lower()):
                    root.tags[tagname.lower()] = Tag(tagname)
                root.tags[tagname.lower()].artists.append(artist)

    def write_lastfm_similar_artists_playlists(self, direc):
        ok = lambda(a): len(a.tracks) >= settings.minArtistTracks
        artists = filter(ok, sorted(self.artists.values()))
        nok = len(artists)
        i = 1
        for artist in artists:
            if i % 10 == 0 or i == nok:
                log('Last.fm similar artists playlists: \t%d / %d' % (i, nok))
            tracks = artist.lastfm_similar_artists_playlist()
            try:
                write_playlist(tracks,
                               os.path.join(direc, artist.clean_name() + '.m3u'))
            except:
                elog('Failed to create last.fm similar playlist for artist %s' % artist.name)
            i += 1

    def write_musicspace_similar_artists_playlists(self, direc):
        def ok(a):
            return hasattr(a, 'artists_weights') and \
                len(a.tracks) >= settings.minArtistTracks
        artists = filter(ok, sorted(self.artists.values()))
        nok = len(artists)
        i = 1
        for artist in artists:
            if i % 10 == 0 or i == nok:
                log('Musicspace similar artists playlists \t%d / %d' % (i, nok))
            tracks = artist.musicspace_similar_artists_playlist()
            if tracks:
                write_playlist(tracks, os.path.join(direc, artist.clean_name() + '.m3u'))
            i += 1

    def write_single_artists_playlists(self, direc):
        ok = lambda(a): len(a.tracks) >= settings.minArtistTracks
        artists = filter(ok, sorted(self.artists.values()))
        nok = len(artists)
        i = 1
        for artist in artists:
            if i % 10 == 0 or i == nok:
                log('Single artist playlists: \t%d / %d' % (i, nok))
            tracks = random.sample(artist.tracks, len(artist.tracks))
            write_playlist(tracks, os.path.join(direc, artist.clean_name() + '.m3u'))
            i += 1

    def write_all_artists_playlist(self, direc, chunk_size=1000):
        self.gather_subtree_tracks(self)
        random.shuffle(self.subtree_tracks)
        num_tracks = len(self.subtree_tracks)
        chunk_end = 0
        plist = 1
        while chunk_end < num_tracks:
            log('All artists playlists: \t%d' % plist)
            chunk_start = chunk_end
            chunk_end = min(chunk_start + chunk_size, num_tracks)
            tracks = self.subtree_tracks[chunk_start:chunk_end]
            filepath = os.path.join(direc, ('0' if plist < 10 else '') + str(plist) + '.m3u')
            write_playlist(tracks, filepath)
            plist += 1

    def write_lastfm_similar_artists_linkfiles(self, direc):
        ok = lambda(a): len(a.tracks) >= settings.minArtistTracks
        artists = filter(ok, sorted(self.artists.values()))
        nok = len(artists)
        i = 1
        for artist in artists:
            if i % 10 == 0 or i == nok:
                log('Last.fm similar artists link files: \t%d / %d' % (i, nok))
            artist_nodes = artist.lastfm_similar_artists_nodes()
            try:
                write_linkfile(artist_nodes,
                               os.path.join(direc, artist.clean_name() + '.link'))
            except:
                elog('Failed to create last.fm similar link file for artist %s' % artist.name)
            i += 1

    def write_lastfm_tag_linkfiles(self, direc):
        ok = lambda(tag): len(tag.artists) >= settings.minTagArtists
        tags = filter(ok, self.tags.values())
        n = len(tags)
        i = 1
        for tag in tags:
            if i % 10 == 0 or i == n:
                log('Last.fm tag link files: \t%d / %d' % (i, n))
            artist_nodes = flatten(list(a.subtrees) for a in tag.artists)
            try:
                write_linkfile(artist_nodes,
                               os.path.join(direc, tag.name + '.link'))
            except:
                elog('Failed to create link file for tag %s' % tag.name)
            i += 1

    def write_lastfm_tag_playlists(self, direc):
        ok = lambda(tag): len(tag.artists) >= settings.minTagArtists
        tags = filter(ok, self.tags.values())
        n = len(tags)
        i = 1
        for tag in tags:
            if i % 10 == 0 or i == n:
                log('Last.fm tag playlists: \t%d / %d' % (i, n))
            try:
                write_playlist(tag.playlist(),
                               os.path.join(direc, tag.name + '.m3u'))
            except:
                elog('Failed to create tag playlist for tag %s' % tag.name)
            i += 1
    def write_lastfm_artist_biographies(self, direc):
        artists = (a for a in self.artists.values() if a.bio_content)
        for artist in artists:
            path = os.path.join(direc, artist.clean_name() + '.txt')
            try:
                with codecs.open(path, 'w', 'utf-8') as lfile:
                    lfile.write(strip_html_tags(artist.bio_content))
            except:
                elog('Error writing bio for artist %s' % artist.name)

    def write_musicspace_similar_artists_linkfiles(self, direc):
        def ok(a):
            return hasattr(a, 'artists_weights') and \
                len(a.tracks) >= settings.minArtistTracks
        artists = filter(ok, sorted(self.artists.values()))
        nok = len(artists)
        i = 1
        for artist in artists:
            if i % 10 == 0 or i == nok:
                log('Musicspace similar artists link files: \t%d / %d' % (i, nok))
            artist_nodes = artist.musicspace_similar_artists_nodes()
            write_linkfile(artist_nodes,
                           os.path.join(direc, artist.clean_name() + '.link'))
            i += 1

    def write_lastfm_recommended_linkfiles(self, direc):
        ok = lambda(a): len(a.tracks) >= settings.minArtistTracks
        artists = filter(ok, sorted(self.artists.values()))
        nok = len(artists)
        i = 1
        for artist in artists:
            if i % 10 == 0 or i == nok:
                log('Recommended artists files: \t%d / %d' % (i, nok))
            recommended = artist.lastfm_recommended()
            path = os.path.join(direc, artist.clean_name() + '.link')
            with codecs.open(path, 'w', 'utf-8') as lfile:
                lfile.write('\n'.join(recommended) + '\n')
            i += 1

    def write_a_to_z_linkfiles(self, direc):
        """Create alphabetical directory of music folders. For each
        character (?) create a rockbox link file containing links to music
        folders of all artists whose name starts with that character."""
        index = unique([a.name[0].upper() for a in self.artists.values()])
        index.sort()
        for i in range(len(index)):
            c = index[i]
            log('Artist index link files: \t%s' % ' '.join(index[0:i]))
            artists = [a for a in self.artists.values() if a.name[0].upper() == c]
            # Only link to artists with pure subtrees; not individual tracks in compilations
            anodes = flatten([list(a.subtrees) for a in artists])
            # anodes = [v for v in anodes if v.artist is v.albumartist]
            anodes.sort()
            try:
                write_linkfile(anodes, os.path.join(direc, c + '.link'))
            except:
                elog('Failed to create linkfile for index letter %s' % c)

    def show_artists(self):
        for a in self.artists.values():
            print('%s\t%s' % (
                    a.name,
                    a.id if settings.mbid_regexp.match(a.id) else ''))

    def show_musicspace(self):
        for a in sorted(self.artists.values()):
            print(a.name)
            if hasattr(a, 'artists_weights'):
                a.show_musicspace_neighbours()

    def populate_musicspace(self, fileobj, a=3.0):
        location = {}
        dimensions = set([])
        # dialect = csv.Sniffer().sniff(path)
        # csv.delimiter = '\t'
        reader = csv.reader(fileobj)
        for row in reader:
            row = [cell.decode('utf-8') for cell in row]
            dbm_aid = self.make_dbm_artistid(row[1], row[0])
            if self.artists.has_key(dbm_aid):
                loc = map(float, row[2:])
                if all(loc):
                    self.artists[dbm_aid].musicspace_location = loc
                    location[dbm_aid] = loc
                    dimensions.add(len(loc))

        settings.musicspace_dimension = max(dimensions) if dimensions else 0

        for this_id in location.keys():
            # TMP while having pickling problems
            #            self.artists[this_id].artists_weights =
            #            [(self.artists[other_id],
            self.artists[this_id].artists_weights = \
                [(other_id,
                  pow(1 + distance(location[this_id], location[other_id]), -a)) for
                 other_id in location.keys()]
            self.artists[this_id].artists_weights.sort(key=lambda(x): -x[1])

    def write_musicspace_file(self, fileobj):
        for a in self.artists.values():
            a.write_music_space_entry(fileobj)

    def graft_subtree(self, subtree):
        '''Use path of new subtree to find graft point, and graft.'''
        # All paths are absolute, so root_path and path are identical
        # up to the length of root path.
        if not subtree.path.startswith(self.path):
            raise DbmError("new subtree %s must lie within the tree rooted at %s" %
                           (path, self.path))
        path = self.path
        subdirs = subtree.path.replace(self.path, '', 1)#.split(os.path.sep)
        next_node = [self]
        for d in subdirs:
            path += os.path.sep + d
            node = next_node
            next_node = [s for s in node[0].subtrees if s.path == path]
            if len(next_node) == 0:
                # Subtree did not previously exist in the tree
                node[0].subtrees.add(subtree)
                break
            elif len(node) > 1:
                raise DbmError('More than one subtree with path %s' % p)
        subtree.parent = node[0]


class ArtistNode(object):
    """A node may be associated with an artist for a variety of
    reasons. E.g.
    1. It's a folder containing several albums by that artist
    2. It's an album by that artist
    3. It's a compilation album containing a track by that album
    """
    def __init__(self, node, artist, albumartist, album):
        self.node = node
        self.artist = artist
        self.albumartist = albumartist
        self.album = album

    def make_rockbox_link(self):
        """Construct rockbox format link to this node"""
        link = make_rockbox_path(self.node.path)
        link += '/\t' + self.artist.name
        if self.albumartist and self.albumartist is not self.artist:
            link += ' in '
            if self.album:
                link += self.album + ' by '
            link += self.albumartist.name or '' # TMP see traceback below
        return link
#             Traceback (most recent call last):
#   File "/home/dan/bin/dbm", line 1329, in run
#     self.dbm.root.write_lastfm_similar_artists_linkfiles(self.dirs['lastfm_similar'])
#   File "/home/dan/src/dbm/dbm.py", line 643, in write_lastfm_similar_artists_linkfiles
#     os.path.join(direc, artist.clean_name() + '.link'))
#   File "/home/dan/src/dbm/dbm.py", line 1006, in write_linkfile
#     lfile.write('\n'.join([v.make_rockbox_link() for v in anodes]) + '\n')
#   File "/home/dan/src/dbm/dbm.py", line 782, in make_rockbox_link
#     link += self.albumartist.name
# TypeError: coercing to Unicode: need string or buffer, NoneType found



    def show(self):
        print('ArtistNode: %s, %s, %s' %
              ('no node!' if not self.node else self.node.path, self.artist.name, self.albumartist.name))

    def __cmp__(self, other):
        ans = cmp(self.artist, other.artist)
        if ans == 0:
            if self.albumartist:
                if other.albumartist:
                    ans = cmp(self.albumartist, other.albumartist)
                else:
                    ans = -1
            elif other.albumartist:
                ans = 1
            if ans == 0:
                ans = cmp(self.album, other.album)
        return ans

class Artist(object):
    def __init__(self, dbm_aid):
        self.id = dbm_aid
        self.name = most_frequent_element(root.artistnames[dbm_aid])
        self.subtrees = set([])
        self.simartists = []
        self.tracks = []
        self.tracks_as_albumartist = []
        self.lastfm_name = ''
        self.musicspace_location = []
        self.tags = []
        self.bio_content = ''

    def download_lastfm_data(self):
        if root.simartists.has_key(self.id):
            self.simartists = root.simartists[self.id]
            return
        if not settings.query_lastfm:
            return

        waiting = True
        i = 0
        while waiting and i < settings.numtries:
            try:
                if not self.lastfm_name:
                    self.set_lastfm_name()
                self.simartists = self.query_lastfm_similar()
                root.simartists[self.id] = self.simartists

                self.pylast = pylast.Artist(self.lastfm_name or self.name, **settings.lastfm)
                self.tags = self.pylast.get_top_tags()
                self.bio_content = self.pylast.get_bio_content()

                waiting = False
                name = self.lastfm_name or self.name
                log('%s last.fm query: %s name %s (%s) got %d artists' %
                    (timenow(),
                     'validated' if self.lastfm_name else 'unvalidated',
                     name,
                     self.id if settings.mbid_regexp.match(self.id) else 'no MusicBrainz ID',
                     len(self.simartists)))
            # except pylast.ServiceException:
            except:
                name = self.lastfm_name or self.name
                if not isinstance(name, basestring):
                    elog('self.lastfm_name = %s, self.name = %s' %
                         (repr(dir(self.lastfm_name)), repr(dir(self.name))))
                log('%s last.fm query: %s name %s (%s) FAILED' %
                    (timenow(),
                     'validated' if self.lastfm_name else 'unvalidated',
                     name,
                     self.id if settings.mbid_regexp.match(self.id) else 'no MusicBrainz ID'))
                i = i+1
                time.sleep(.1)

    def set_lastfm_name(self):
        if settings.mbid_regexp.match(self.id):
            try:
                self.lastfm_name = \
                    pylast.get_artist_by_mbid(self.id, **settings.lastfm).get_name()
            except pylast.ServiceException:
                elog('pylast.ServiceException occurred with artist %s' % self.id)
        else:
            self.lastfm_name = self.name

    def query_lastfm_similar(self):
        """Return list of similar artist (id, name) tuples. Since
        pylast doesn't currently include mbids in Artist objects, it's a
        bit convoluted to do this with pylast."""

        params = {'artist': self.lastfm_name or self.name}
        doc = pylast._Request("artist.getSimilar", params, **settings.lastfm).execute(True)
        simids = pylast._extract_all(doc, 'mbid')
        simnames = pylast._extract_all(doc, 'name')
        retval = zip(simids, simnames)
        return [(x[0] or None, x[1]) for x in retval]

    def musicspace_similar_artists_playlist(self, n=1000):
        artists = sample(n, self.artists_weights)
# TMP while pickling problems, otherwise I would use artist instance
# referencves rather than dbm_aids
        artists = [root.artists[aid] for aid in artists]
        artists = filter(lambda(a): a.tracks, artists)
        try:
            return [random.sample(artist.tracks, 1)[0] for artist in artists]
        except:
            log('Error creating musicspace playlist for %s' % self.name)
            return []

    def musicspace_similar_artists_nodes(self):
# TMP As noted elsewhere, artists_weights is a list of tuples the
# first elements of which hold a dbm_aid, rather than a reference to
# an Artist instance. I would do the latter, except the circular
# references seemed to fuck up on pickling somehow.
        artists = [root.artists[x[0]] for x in self.artists_weights]
        return flatten([sorted(list(artist.subtrees)) for artist in artists])

    def lastfm_similar_artists_playlist(self, n=1000):
        # FIXME: code seems a bit ugly in this function; why using
        # dbm_aids instead of artist references?
        dbm_aids = [aid for aid in map(root.lookup_dbm_artistid, self.simartists)
                    if aid and root.artists[aid].tracks]
        dbm_aids.append(self.id)
        # draw sample with replacement (sample size larger than population)
        dbm_aids = [random.sample(dbm_aids, 1)[0] for i in range(n)]
        return [random.sample(root.artists[dbm_aid].tracks, 1)[0] for dbm_aid in dbm_aids]

    def lastfm_similar_artists_nodes(self):
        artists = [artist for artist in map(root.lookup_dbm_artist, self.simartists)
                   if artist and artist.tracks]
        artists = [self] + artists
        return flatten([sorted(list(artist.subtrees)) for artist in artists])

    def lastfm_recommended(self):
        return [x[1] for x in self.simartists \
                    if not root.lookup_dbm_artistid(x)]

    def unite_spuriously_separated_subtrees(self):
        """This is a bit of a hack / heuristic. If an artist has a
        number of supposedly pure subtrees that all share the same
        parent node (which may also be in the list of pure subtrees),
        then we set the parent node to be the single pure subtree for
        this artist."""
        pure_anodes = [v for v in self.subtrees if v.albumartist is self]
        if len(pure_anodes) > 1:
            # If a single one of the parents is itself in pure_anodes,
            # then we use that as the pure_anode
            parents = [v.node.parent for v in pure_anodes]
            parent = None
            if len(set(parents)) == 1: # collection of siblings without parent
                parent = parents[0]
            else:
                pure_nodes = [v.node for v in pure_anodes]
                parents = [p for p in parents if p in pure_nodes]
                if len(set(parents)) == 1: # collection of siblings with parent
                    parent = parents[0]
            if parent:
                if not settings.quiet:
                    elog('uniting %d subtrees for %s' % (len(pure_anodes), self.name))
                anodes = [v for v in self.subtrees if v not in pure_anodes]
                anodes.append(ArtistNode(parent, self, self, None))
                self.subtrees = set(anodes)

    def show(self):
        print('%s %s %d tracks %d albumartist tracks' %
              (self.id.ljust(25), self.name,
               len(self.tracks), len(self.tracks_as_albumartist)))

    def show_musicspace_neighbours(self):
        i = 1
        for w in self.artists_weights:
            print('\t%s%f' % (root.artists[w[0]].name.ljust(30), w[1]))
            i += 1
            if i > 30: break

    def write_music_space_entry(self, fileobj):
        fileobj.write(
            '"%s",%s,' % (self.name,
                          self.id if settings.mbid_regexp.match(self.id) else ''))

        # TMP: library may have been pickled prior to addition of musicspace_location
        # to Artist.__init__
        if not hasattr(self, 'musicspace_location'):
            self.musicspace_location = []

        fileobj.write(
            ','.join(map(str, self.musicspace_location)) + \
                ',' * (settings.musicspace_dimension - len(self.musicspace_location)) + '\n')


    def clean_name(self):
        name = self.name
        name = name.replace('"','').replace('\'','') ## "Weird Al" Yankovic, Guns 'N' Roses
        name = name.replace('/', '').replace('?', '').replace(':','') ## DJ /rupture, Therapy?, :wumpscut: ??!!
        return name

    def __eq__(self, other):
        return self.id == other.id

    def __cmp__(self, other):
        return cmp(self.name, other.name)



class Tag(object):
    def __init__(self, name):
        self.name = name
        self.artists = []
    def playlist(self, n=1000):
        # Draw sample of artists with replacement
        artists = [random.sample(self.artists, 1)[0] for i in range(n)]
        # Pick one track from each
        tracks = [random.sample(artist.tracks, 1)[0] for artist in artists]
        return unique(tracks)
        
    def __cmp__(self, other):
        return cmp(self.name, other.name)
class LastFmUser(pylast.User):
    def __init__(self, name, lastfm_auth_info):
        pylast.User.__init__(self, name, **lastfm_auth_info)
        self.artist_counts = {}

    def get_weekly_artist_charts_as_dict(self, from_date = None, to_date = None):
        """A modified version of
        pylast.User.get_weekly_artist_charts. Changed to include mbids
        in return data."""

        params = self._get_params()
        if from_date and to_date:
            params["from"] = from_date
            params["to"] = to_date

            doc = self._request("user.getWeeklyArtistChart", True, params)

            mbids = []
            names = []
            counts = []
            for node in doc.getElementsByTagName("artist"):
                mbids.append(pylast._extract(node, "mbid"))
                names.append(pylast._extract(node, "name"))
                counts.append(int(pylast._extract(node, "playcount")))
            return dict(zip(zip(mbids, names), counts))

    def get_artist_counts(self):
        dates = self.get_weekly_chart_dates()
        log('Collecting listening data from %d weekly charts' % len(dates))
        progress = ''
        for i in range(len(dates)):
            log("%d/%d" % (i, len(dates)))
            try:
                chart = self.get_weekly_artist_charts_as_dict(*dates[i])
            except:
                log('Failed to download chart %d' % (i+1))
                continue
            for key in chart:
                artist = root.lookup_dbm_artist(key) or key
                if not self.artist_counts.has_key(artist):
                    self.artist_counts[artist] = 0
                self.artist_counts[artist] += chart[key]

    def write_unlistened_artists_linkfile(self, direc):
        listened_artists = filter(lambda(a): isinstance(a, Artist),
                                  self.artist_counts.keys())
        unlistened_artists = list(set(root.artists.values()).difference(listened_artists))
        for artist in unlistened_artists:
            write_linkfile(sorted(list(artist.subtrees)),
                           os.path.join(direc, artist.clean_name() + '.link'))

    def write_listened_artists_linkfile(self, direc):
        listened_artists = filter(lambda(a): isinstance(a, Artist),
                                  self.artist_counts.keys())
        for artist in listened_artists:
            write_linkfile(sorted(list(artist.subtrees)),
                           os.path.join(direc, artist.clean_name() + '.link'))

    def write_absent_artists_linkfile(self, path):
        absent_artists = filter(lambda(a): not isinstance(a, Artist),
                                self.artist_counts.keys())
        absent_artist_names = [a[1] for a in absent_artists]
        with codecs.open(path, 'w', 'utf-8') as lfile:
            lfile.write('\n'.join(absent_artist_names))

class DbmError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

def canonicalise_name(name):
    r1 = re.compile('^the +')
    r2 = re.compile(' +')
    return r2.sub('_', r1.sub('', name.lower()))

def write_playlist(tracks, filepath):
    paths = unique([t.path for t in tracks])
    if settings.target == 'rockbox':
        paths = map(make_rockbox_path, paths)
    try:
        with codecs.open(filepath, 'w', 'utf-8') as plfile:
            plfile.write('\n'.join(paths) + '\n')
    except:
        elog('write_playlist: write to file failed')
        log('Character encoding problem while writing playlist, destination file is %s.'
            'Please report to Dan: davison@stats.ox.ac.uk.' % filepath)

def write_linkfile(anodes, filepath):
    with codecs.open(filepath, 'w', 'utf-8') as lfile:
#        lfile.write('#Display last path segments=1\n')
        lfile.write('\n'.join([v.make_rockbox_link() for v in anodes]) + '\n')

def make_rockbox_path(path):
    """Form path to music on rockboxed player from path on computer.

    If we have

    rootpath = '/media/rockbox/dir/music'
    track = '/media/rockbox/dir/music/artist/album/track.ogg'

    then what we want is '/dir/music/artist/album/track.ogg''
    which is given by

    path_to_rockbox = '/media/rockbox'
    path = track.replace(path_to_rockbox, '', 1)

    under Windows

    rootpath = 'E:\dir\music'
    track = 'E:\dir\music\artist\album\track.ogg'
    path_to_rockbox = 'E:'

    so we should treat os.path.dirname(rootpath) as a guess at path_to_rockbox
    """
    if settings.path_to_rockbox is None:
        settings.path_to_rockbox = os.path.dirname(root.path)

    path = path.replace(settings.path_to_rockbox, '', 1)

    if os.name == 'posix':
        return path
    else:
        # TMP hack: path_to_rockbox is something like 'E:\\' which
        # ends up replacing the directory separator required for
        # absolute pathname
        if path[0] != os.path.sep:
            path = os.path.sep + path
        path = path.replace('\\', '/') ## rockbox uses linux-style path separators
        return path

#     path = path.replace(settings.libdir, '')
#     path = path.replace('\\', '/') ## rockbox uses linux style path separators
#     return '/' + os.path.split(settings.libdir)[1] + path

def rockbox_clean_name(s):
    bad = '\/:<>?*|'
    for c in bad:
        s = s.replace(c, '_')
    s = s.replace('"', "'")
    return s

if __name__ == '__main__':
    def log(msg, dummy_arg=None):
        try:
            sys.stdout.write(msg.encode('utf-8') + '\n')
        except:
            sys.stdout.write('ERROR: Failed to encode log message\n')
    dbm = Dbm()
    dbm.run()

def recommend_new_artists(scrobble_archive='', q=.8):
    """List artists that occur most frequently in similar artists but
    are absent from the library"""
    if scrobble_archive:
        scrobbled = read_scrobble_archive(scrobble_archive)
        recent = [s['artistname'] for s in scrobbled]
        artists = filter(lambda(art): art['names'][0] in recent, artists)
    simartnames = flatten([a['simartists'][1] for a in artists.values()])
    libartnames = [a['names'][0] for a in artists.values()]
    simartnames = filter(lambda(a): not a in libartnames, simartnames)
    usimartnames = unique(simartnames)
    simartcounts = dict.fromkeys(usimartnames, 0)
    for name in simartnames:
        simartcounts[name] = simartcounts[name] + 1
    counts = simartcounts.values()
    counts.sort()
    cutoff = counts[int(round(q * len(usimartnames)))]
    topsimartcounts = {}
    for name, count in simartcounts.items():
        if count >= cutoff:
            topsimartcounts[name] = count
    referers = {}
    for libart in artists.values():
        for simart in topsimartcounts.keys():
            if simart in libart['simartnames']:
                if not simart in referers.keys(): referers[simart] = []
                referers[simart].append(libart['names'][0])
    for simart, count in topsimartcounts.items():
        try:
            print simart.ljust(30), str(count).ljust(10)
            for artname in referers[simart]:
                print artname.rjust(55)
        except:
            None


def read_scrobble_archive(f):
    f = open(f, 'r')
    entries = ('artistname', 'releasename', 'trackname', 'something',
               'length', 'listened', 'playtime')
    return [dict(entries, l.split('\t')) for l in f.readlines()]
