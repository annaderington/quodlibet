# Copyright 2024 Anna Derington
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
from pathlib import Path
from unittest.mock import ANY, patch

from gi.repository import Gtk

from quodlibet import app
from quodlibet import get_user_dir
from quodlibet.formats import AudioFile
from tests.plugin import PluginTestCase, init_fake_app, destroy_fake_app


QUERIES = {
    "Directory": {
        "query": '~dirname="/dev/null"',
        "terms": ("/dev/null",),
        "results": 5,
    },
    "2 artists": {
        "query": 'artist=|("Group1","Group2")',
        "terms": ("Group",),
        "results": 4,
    },
    "No songs": {"query": "#(length < 0)", "terms": (), "results": 0},
    "Symbols": {"query": '~dirname="/tmp/new"', "terms": ("/tmp/new",), "results": 1},
}


SONGS = [
    AudioFile(
        {
            "~filename": "/dev/null/Song1.mp3",
            "title": "Song1",
            "artist": "Artist1",
            "album": "Album1",
        }
    ),
    AudioFile(
        {
            "~filename": "/dev/null/Song2.mp3",
            "title": "Song2",
            "artist": "Artist1",
            "album": "Album1",
        }
    ),
    AudioFile(
        {
            "~filename": "/dev/null/Song3.mp3",
            "title": "Song3",
            "artist": "Artist1",
            "album": "Album2",
        }
    ),
    AudioFile(
        {
            "~filename": "/dev/null/Song4.mp3",
            "title": "Song4",
            "artist": "Artist2",
            "album": "Album2",
        }
    ),
    AudioFile(
        {
            "~filename": "/dev/null/Song5.mp3",
            "title": "Song5",
            "artist": "Artist2",
            "album": "Album2",
        }
    ),
    AudioFile(
        {
            "~filename": "/tmp/music/Song5.mp3",
            "title": "Song5",
            "artist": "Artist2",
            "album": "Album2",
        }
    ),
    AudioFile(
        {
            "~filename": "/tmp/music/Track1.mp3",
            "title": "Track1",
            "artist": "Group1",
            "album": "Album3",
        }
    ),
    AudioFile(
        {
            "~filename": "/tmp/music/Track2-1.mp3",
            "title": "Track2",
            "artist": "Group1",
            "album": "Album3",
        }
    ),
    AudioFile(
        {
            "~filename": "/tmp/music/Track2-2.mp3",
            "title": "Track2",
            "artist": "Group2",
            "album": "Album4",
        }
    ),
    AudioFile(
        {
            "~filename": "/tmp/music/Track3.mp3",
            "title": "Track3",
            "artist": "Group2",
            "album": "Album4",
        }
    ),
    AudioFile(
        {
            "~filename": "/tmp/new/",
            "title": "Abc123 (~!@#$%^&*|:'\",.\\/?+=;)",
            "artist": r"[ÆÁàçÈéöø] <αΔλΛ> Привет こんにちわ مرحبا",
            "album": r"{‰} → A∩B≥3 ⎈Ⓐ ░ ☔☃☂ ♂♀🤴 😀🎧 🪐👽🖖",
        }
    ),
]

PLAYLISTS = {
    "No songs": [],
    "3 songs": [SONGS[i] for i in range(3)],
    "All songs": SONGS,
    "All songs twice": SONGS * 2,
}


class TSyncToPlaylist(PluginTestCase):
    QUERIES_SAVED = "\n".join(
        [details["query"] + "\n" + name for name, details in QUERIES.items()]
    )

    @classmethod
    def setUpClass(cls):
        plugin_id = "synchronize_to_playlist"
        cls.module = cls.modules[plugin_id]
        cls.plugin = cls.module.SyncToPlaylist()
        cls.gtk_window = Gtk.Window()
        init_fake_app()

    @classmethod
    def tearDownClass(cls):
        cls.gtk_window.destroy()
        del cls.plugin
        del cls.module
        destroy_fake_app()

    def setUp(self):
        path_query = Path(self.plugin.path_query)
        path_query.parent.mkdir(parents=True, exist_ok=True)
        with open(self.plugin.path_query, "w") as f:
            f.write(self.QUERIES_SAVED)

        path_dest = Path(get_user_dir(), "export")
        path_dest.mkdir(parents=True, exist_ok=True)
        self.path_dest = str(path_dest)

    def tearDown(self):
        if os.path.exists(self.plugin.path_query):
            os.remove(self.plugin.path_query)

    def _start_plugin(self):
        return self.plugin.PluginPreferences(self.gtk_window)

    def _select_searches(self, *labels):
        for button in self.plugin.saved_search_vbox.get_children():
            if button.get_label() in labels:
                button.set_active(True)

    def _select_playlists(self, *labels):
        for button in self.plugin.saved_playlist_vbox.get_children():
            if button.get_label() in labels:
                button.set_active(True)

    def _fill_library(self, add_playlists=True):
        app.library.add(SONGS)
        if add_playlists:
            for playlist_name, playlist_songs in PLAYLISTS.items():
                app.library.playlists.create_from_songs(playlist_songs, playlist_name)

    def _reset_library(self):
        destroy_fake_app()
        init_fake_app()

    def test_pluginpreferences_success(self):
        self._fill_library()
        main_vbox = self._start_plugin()

        self.assertEqual(type(main_vbox), Gtk.VBox)

        self.assertEqual(len(self.plugin.queries), len(QUERIES))
        self.assertTrue(
            all(
                isinstance(button, Gtk.CheckButton)
                for button in self.plugin.saved_search_vbox.get_children()
            )
        )
        self.assertFalse(
            any(
                button.get_active()
                for button in self.plugin.saved_search_vbox.get_children()
            )
        )
        self.assertEqual(len(self.plugin.playlist_names), len(PLAYLISTS))
        self.assertTrue(
            all(
                isinstance(button, Gtk.CheckButton)
                for button in self.plugin.saved_playlist_vbox.get_children()
            )
        )
        self.assertFalse(
            any(
                button.get_active()
                for button in self.plugin.saved_playlist_vbox.get_children()
            )
        )
        self.assertNotEqual(self.plugin.destination_entry.get_placeholder_text(), "")
        self.assertEqual(self.plugin.destination_entry.get_text(), "")

        self.assertNotEqual(self.plugin.remove_root_entry.get_placeholder_text(), "")
        self.assertEqual(self.plugin.remove_root_entry.get_text(), "")

        self.assertNotEqual(self.plugin.new_root_entry.get_placeholder_text(), "")
        self.assertEqual(self.plugin.new_root_entry.get_text(), "")

        self.assertTrue(self.plugin.run_export_button.get_visible())
        self._reset_library()

    def test_select_saved_search(self):
        button = self.plugin.saved_search_vbox.get_children()[0]

        button.set_active(True)
        self.assertTrue(button.get_active())
        saved_queries = self.plugin.read_sync_queries()
        self.assertTrue(button.get_label() in saved_queries)

    def test_select_saved_playlist(self):
        button = self.plugin.saved_playlist_vbox.get_children()[0]

        button.set_active(True)
        self.assertTrue(button.get_active())
        saved_playlists = self.plugin.read_sync_playlists()
        self.assertTrue(button.get_label() in saved_playlists)

    def test_destination_path_changed(self):
        self._start_plugin()
        self.plugin.destination_entry.set_text(self.path_dest)
        self.assertEqual(self.plugin.destination_entry.get_text(), self.path_dest)

    @patch("quodlibet.qltk.ErrorMessage")
    def test_run_export_no_destination_path(self, mock_message):
        main_vbox = self._start_plugin()
        self._select_searches("Directory")

        self.plugin._run_export(self.plugin.run_export_button)
        mock_message.assert_called_once_with(
            main_vbox, "No destination path provided", ANY
        )

    @patch("quodlibet.qltk.ErrorMessage")
    def test_run_export_path_not_absolute(self, mock_message):
        main_vbox = self._start_plugin()
        self._select_searches("Directory")
        self.plugin.destination_entry.set_text("./path")

        self.plugin._run_export(self.plugin.run_export_button)
        mock_message.assert_called_once_with(
            main_vbox, "Export path is not absolute", ANY
        )
