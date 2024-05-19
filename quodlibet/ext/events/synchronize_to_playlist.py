# Copyright 2024 Anna Derington
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import unicodedata

from gi.repository import Gtk

from quodlibet import _
from quodlibet import app
from quodlibet import config
from quodlibet import get_user_dir
from quodlibet import qltk
from quodlibet import util
from quodlibet.plugins import PM
from quodlibet.plugins import PluginConfigMixin
from quodlibet.plugins.events import EventPlugin
from quodlibet.qltk import Icons
from quodlibet.qltk.entry import ValidatingEntry
from quodlibet.query import Query
from quodlibet.util import print_d, print_e
from quodlibet.util.path import strip_win32_incompat_from_path

PLUGIN_CONFIG_SECTION = "synchronize_to_playlist"


class SyncToPlaylist(EventPlugin, PluginConfigMixin):
    PLUGIN_ICON = Icons.NETWORK_TRANSMIT
    PLUGIN_ID = PLUGIN_CONFIG_SECTION
    PLUGIN_NAME = _("Synchronize to Playlist")
    PLUGIN_DESC = _(
        "Synchronizes all songs from the selected saved searches "
        "and playlists as M3U playlists."
    )

    CONFIG_SECTION = PLUGIN_CONFIG_SECTION
    CONFIG_PATH_KEY = "{}_{}".format(PLUGIN_CONFIG_SECTION, "path")
    CONFIG_REMOVE_ROOT_KEY = "{}_{}".format(PLUGIN_CONFIG_SECTION, "remove_root")
    CONFIG_NEW_ROOT_KEY = "{}_{}".format(PLUGIN_CONFIG_SECTION, "new_root")

    path_query = os.path.join(get_user_dir(), "lists", "queries.saved")
    path_sync_query = os.path.join(get_user_dir(), "lists", "queries.sync")
    path_sync_playlists = os.path.join(get_user_dir(), "lists", "playlists.sync")

    default_remove_root = ""
    default_new_root = ""

    spacing_main = 20
    spacing_large = 6
    spacing_small = 3
    summary_sep = " " * 2
    summary_sep_list = "," + summary_sep

    def PluginPreferences(self, parent):
        pl_lib = app.library.playlists
        self.playlist_names = [pl.name for pl in pl_lib]

        main_vbox = Gtk.VBox(spacing=self.spacing_main)
        self.main_vbox = main_vbox

        # Read saved searches from file
        self.queries = self._get_queries()

        # Saved search selection frame
        saved_search_vbox = Gtk.VBox(spacing=self.spacing_large)
        self.saved_search_vbox = saved_search_vbox

        sync_queries = self.read_sync_queries()

        # Use intersection of existing queries in case some have been deleted
        sync_queries = list(set(self.queries.keys()).intersection(sync_queries))
        self.write_sync_queries(sync_queries)
        for query_name in self.queries.keys():
            check_button = Gtk.CheckButton(label=query_name)
            saved_search_vbox.pack_start(check_button, False, False, 0)
            if query_name in sync_queries:
                check_button.set_active(True)
            check_button.connect(
                "toggled", self._toggle_save_query, check_button, query_name
            )
        saved_search_scroll = self._expandable_scroll(min_h=0, max_h=300)
        saved_search_scroll.add(saved_search_vbox)
        frame = qltk.Frame(
            label=_("Synchronize the following saved searches:"),
            child=saved_search_scroll,
        )
        main_vbox.pack_start(frame, False, False, 0)

        # Saved playlist selection frame
        saved_playlist_vbox = Gtk.VBox(spacing=self.spacing_large)
        self.saved_playlist_vbox = saved_playlist_vbox
        sync_playlists = self.read_sync_playlists()

        # Use intersection of existing playlists in case some have been deleted
        sync_playlists = list(set(self.playlist_names).intersection(sync_playlists))
        self.write_sync_playlists(sync_playlists)
        for playlist_name in self.playlist_names:
            check_button = Gtk.CheckButton(label=playlist_name)
            saved_playlist_vbox.pack_start(check_button, False, False, 0)
            if playlist_name in sync_playlists:
                check_button.set_active(True)
            check_button.connect(
                "toggled", self._toggle_save_playlist, check_button, playlist_name
            )

        saved_playlist_scroll = self._expandable_scroll(min_h=0, max_h=300)
        saved_playlist_scroll.add(saved_playlist_vbox)
        frame = qltk.Frame(
            label=_("Synchronize the following saved playlists:"),
            child=saved_playlist_scroll,
        )
        main_vbox.pack_start(frame, False, False, 0)

        # Destination path entry field
        destination_entry = ValidatingEntry(
            validator=self._check_valid_destination_path,
        )
        destination_entry.connect("changed", self._destination_path_changed)
        self.destination_entry = destination_entry

        # Destination path selection button
        destination_button = qltk.Button(label="", icon_name=Icons.FOLDER_OPEN)
        destination_button.connect("clicked", self._select_destination_path)

        # Destination path hbox
        destination_path_hbox = Gtk.HBox(spacing=self.spacing_small)
        destination_path_hbox.pack_start(destination_entry, True, True, 0)
        destination_path_hbox.pack_start(destination_button, False, False, 0)

        # Destination path frame
        destination_vbox = Gtk.VBox(spacing=self.spacing_large)
        destination_vbox.pack_start(destination_path_hbox, False, False, 0)
        frame = qltk.Frame(label=_("Destination path:"), child=destination_vbox)
        main_vbox.pack_start(frame, False, False, 0)
        self.tmp_export_path = ""

        # Remove root frame
        remove_root_entry = ValidatingEntry(
            validator=self._check_valid_remove_root,
        )
        remove_root_entry.connect("changed", self._remove_root_changed)
        self.remove_root_entry = remove_root_entry
        frame = qltk.Frame(label=_("Remove path root:"), child=remove_root_entry)
        main_vbox.pack_start(frame, False, False, 0)
        self.tmp_remove_root = self.remove_root_entry.get_text()
        # New root frame
        new_root_entry = Gtk.Entry(
            text=config.get(
                PM.CONFIG_SECTION, self.CONFIG_NEW_ROOT_KEY, self.default_new_root
            ),
        )
        new_root_entry.connect("changed", self._new_root_changed)
        self.new_root_entry = new_root_entry
        frame = qltk.Frame(label=_("Replace path root with:"), child=new_root_entry)
        main_vbox.pack_start(frame, False, False, 0)
        self.tmp_new_root = self.new_root_entry.get_text()

        # Run export button
        run_export_button = qltk.Button(
            label=_("Run export of playlists"), icon_name=Icons.DOCUMENT_SAVE
        )
        run_export_button.set_visible(True)
        run_export_button.connect("clicked", self._run_export)
        self.run_export_button = run_export_button

        # Section for the sync buttons
        button_vbox = Gtk.VBox(spacing=self.spacing_large)
        button_vbox.pack_start(run_export_button, False, False, 0)
        main_vbox.pack_start(button_vbox, False, False, 0)

        destination_entry.set_text(
            config.get(PM.CONFIG_SECTION, self.CONFIG_PATH_KEY, ""),
        )
        remove_root_entry.set_text(
            config.get(
                PM.CONFIG_SECTION, self.CONFIG_REMOVE_ROOT_KEY, self.default_remove_root
            ),
        )

        return main_vbox
        pass

    def _toggle_save_query(self, check_button, gparam, name):
        save_queries = self.read_sync_queries()
        if check_button.get_active():
            save_queries.append(name)
        else:
            save_queries = list(set(save_queries).remove(name))
        self.write_sync_queries(query_names=save_queries)

    def _toggle_save_playlist(self, check_button, gparam, name):
        save_playlists = self.read_sync_playlists()
        if check_button.get_active():
            save_playlists.append(name)
        else:
            save_playlists = list(set(save_playlists).remove(name))
        self.write_sync_playlists(playlist_names=save_playlists)

    def _get_queries(self):
        queries = {}
        if not os.path.exists(self.path_query):
            return queries
        with open(self.path_query, encoding="utf-8") as query_file:
            for query_string in query_file:
                name = next(query_file).strip()
                queries[name] = Query(query_string.strip())
        return queries

    def _expandable_scroll(self, min_h=50, max_h=-1, expand=True):
        """
        Create a ScrolledWindow that expands as content is added.

        :param min_h: The minimum height of the window, in pixels.
        :param max_h: The maximum height of the window, in pixels. It will grow
                      up to this height before it starts scrolling the content.
        :param expand: Whether the window should expand.
        :return: A new ScrolledWindow.
        """
        return Gtk.ScrolledWindow(
            min_content_height=min_h,
            max_content_height=max_h,
            propagate_natural_height=expand,
        )

    def _label_with_icon(self, text, icon_name, visible=True):
        """
        Create a new label with an icon to the left of the text.

        :param text:      The new text to set for the label.
        :param icon_name: An icon name or None.
        :return: A HBox containing an icon followed by a label.
        """
        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        label = Gtk.Label(label=text, xalign=0.0, yalign=0.5, wrap=True)

        hbox = Gtk.HBox(spacing=self.spacing_large)
        if not visible:
            hbox.set_visible(False)
            hbox.set_no_show_all(True)
        hbox.pack_start(image, False, False, 0)
        hbox.pack_start(label, True, True, 0)

        return hbox

    def _destination_path_changed(self, entry):
        """
        Save the destination path to the global config when the path changes.

        :param entry: The destination path entry field.
        """
        self.tmp_export_path = entry.get_text()

    def _select_destination_path(self, button):
        """
        Show a folder selection dialog to select the destination path
        from the file system.

        :param button: The destination path selection button.
        """
        dialog = Gtk.FileChooserDialog(
            title=_("Choose destination path"),
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            select_multiple=False,
            create_folders=True,
            local_only=False,
            show_hidden=True,
        )
        dialog.add_buttons(
            _("_Cancel"), Gtk.ResponseType.CANCEL, _("_Save"), Gtk.ResponseType.OK
        )
        dialog.set_default_response(Gtk.ResponseType.OK)

        # If there is an existing path in the entry field,
        # make that path the default
        destination_entry_text = self.destination_entry.get_text()
        if destination_entry_text != "":
            dialog.set_current_folder(destination_entry_text)

        # Show the dialog and get the selected path
        response = dialog.run()
        response_path = dialog.get_filename()

        # Close the dialog and save the selected path
        dialog.destroy()
        if response == Gtk.ResponseType.OK and response_path != destination_entry_text:
            self.destination_entry.set_text(response_path)

    def _remove_root_changed(self, entry):
        """
        Save the remove root to the global config on change.

        :param entry: The export pattern entry field.
        """
        self.tmp_remove_root = entry.get_text()

    def _new_root_changed(self, entry):
        """
        Save the new root to the global config on changes.

        :param entry: The export pattern entry field.
        """
        self.tmp_new_root = entry.get_text()

    def _show_export_error(self, title, message):
        """
        Show an error message whenever an export error occurs.

        :param title:   The title of the message popup.
        :param message: The error message.
        """
        qltk.ErrorMessage(self.main_vbox, title, message).run()
        print_e(title)

    def _check_valid_destination_path(self, destination_path):
        """
        Ensure that the destination path is valid.

        :return: True if valid, else False
        """
        if not destination_path:
            return False
        if not os.path.isabs(destination_path):
            return False
        return True

    def _check_valid_remove_root(self, remove_root):
        """
        Ensure that the remove root entry is valid.

        :return: True if valid, else False
        """
        # Get text from the remove root entry
        if remove_root and len(remove_root) > 0:
            # TODO check that remove root is valid i.r.t. the library
            return True

        return True

    def _check_valid_inputs(self):
        """
        Ensure that all user inputs have been given. Shows a popup error message
        if values are not as expected.

        :return: True if valid, else False
        """
        # Get text from the destination path entry
        destination_path = self.destination_entry.get_text()
        if not destination_path:
            self._show_export_error(
                _("No destination path provided"),
                _("Please specify the directory where songs " "should be exported."),
            )
            return False

        # Get text from the remove root entry
        remove_root = self.remove_root_entry.get_text()
        if remove_root and len(remove_root) > 0:
            # TODO check that remove root is valid i.r.t. the library
            pass

        # Combine destination path and export pattern to form the full pattern
        if not os.path.isabs(destination_path):
            self._show_export_error(
                _("Export path is not absolute"),
                _("Please select an absolute export path"),
            )
            return False

        return True

    def _make_safe_name(self, input_path):
        """
        Make a file path safe by replacing unsafe characters.

        :param input_path: A relative Path.
        :return: The given path, with any unsafe characters replaced.
                 Returned as a string.
        """
        # Remove diacritics (accents)
        safe_filename = unicodedata.normalize("NFKD", str(input_path))
        safe_filename = "".join(
            c for c in safe_filename if not unicodedata.combining(c)
        )

        if os.name != "nt":
            # Ensure that Win32-incompatible chars are always removed.
            # On Windows, this is called during `FileFromPattern`.
            safe_filename = strip_win32_incompat_from_path(safe_filename)

        return safe_filename

    def _run_export(
        self,
        button,
    ):
        """
        Run the playlist export for all playlists/queries.

        :param button: The start export button.
        """
        config.set(PM.CONFIG_SECTION, self.CONFIG_PATH_KEY, self.tmp_export_path)
        config.set(PM.CONFIG_SECTION, self.CONFIG_REMOVE_ROOT_KEY, self.tmp_remove_root)
        config.set(PM.CONFIG_SECTION, self.CONFIG_NEW_ROOT_KEY, self.tmp_new_root)
        if not self._check_valid_inputs():
            return
        print_d(_("Running playlist export"))
        self.running = True

        # Change button visibility
        # self.sync_start_button.set_visible(False)
        # self.sync_stop_button.set_visible(True)

        self._export_all()

    def _export_all(self):
        pl_lib = app.library.playlists
        playlist_names = [pl.name for pl in pl_lib]
        sync_playlists = self.read_sync_playlists()
        # Playlists that have been set to be synced may not exist anymore,
        # so check for intersection between existing playlists and sync playlists
        enabled_playlists = list(set(playlist_names).intersection(sync_playlists))
        # Save playlists to M3U
        for playlist_name in enabled_playlists:
            self.save_playlist_to_m3u(playlist_name)

        queries = self._get_queries()
        sync_queries = self.read_sync_queries()
        # Queries that have been set to be synced may not exist anymore,
        # so check for intersection between existing queries and sync queries
        enabled_queries = list(set(queries).intersection(sync_queries))

        # Save queries to M3U
        for query_name in enabled_queries:
            self.save_query_to_m3u(query_name)

    def save_playlist_to_m3u(self, playlist_name):
        # get all songs of playlist
        songs = []
        pl_lib = app.library.playlists

        playlist = pl_lib[playlist_name]
        songs = list(playlist)

        # save all songs to m3u

        safe_name = self._make_safe_name(playlist_name)
        file_path = os.path.join(
            config.get(PM.CONFIG_SECTION, self.CONFIG_PATH_KEY, ""), safe_name + ".m3u"
        )
        files = self.__get_song_files(
            songs,
            remove_root=config.get(PM.CONFIG_SECTION, self.CONFIG_REMOVE_ROOT_KEY, ""),
            new_root=config.get(PM.CONFIG_SECTION, self.CONFIG_NEW_ROOT_KEY, ""),
        )
        self.__m3u_export(file_path, files)

    def save_query_to_m3u(self, query_name):
        # get all songs of query
        songs = []
        queries = self._get_queries()
        query = queries[query_name]
        for song in app.library.itervalues():
            if query.search(song):
                songs.append(song)

        # save all songs to m3u
        safe_query_name = self._make_safe_name(query_name)
        file_path = os.path.join(
            config.get(PM.CONFIG_SECTION, self.CONFIG_PATH_KEY, ""),
            safe_query_name + ".m3u",
        )
        files = self.__get_song_files(
            songs,
            remove_root=config.get(PM.CONFIG_SECTION, self.CONFIG_REMOVE_ROOT_KEY, ""),
            new_root=config.get(PM.CONFIG_SECTION, self.CONFIG_NEW_ROOT_KEY, ""),
        )
        self.__m3u_export(file_path, files)

    def __file_error(self, file_path):
        dialog = qltk.ErrorMessage(
            None,
            _("Unable to export playlist"),
            _("Writing to %s failed.") % util.bold(file_path),
            escape_desc=False,
        )
        dialog.run()

    def __m3u_export(self, file_path, files):
        try:
            fhandler = open(file_path, "wb")
        except OSError:
            self.__file_error(file_path)
        else:
            text = "#EXTM3U\n"

            for f in files:
                text += "#EXTINF:%d,%s\n" % (f["length"], f["title"])
                text += f["path"] + "\n"

            fhandler.write(text.encode("utf-8"))
            fhandler.close()

    def __get_song_files(self, songs, remove_root="", new_root=""):
        files = []
        for song in songs:
            f = {}
            if "~uri" in song:
                f["path"] = song("~filename")
                f["title"] = song("title")
                f["length"] = -1
            else:
                path = song("~filename")
                if len(remove_root) > 0:
                    path = os.path.relpath(path, remove_root)
                    if len(new_root) > 0:
                        path = os.path.join(new_root, path)

                    # TODO: is this required?
                    # if path.startswith("#"):
                    #     # avoid lines starting with '#' which don't work with M3U
                    #     path = os.path.join(new_root, path)
                f["path"] = path
                f["title"] = "{} - {}".format(
                    song("~people").replace("\n", ", "),
                    song("~title~version"),
                )
                f["length"] = song("~#length")
            files.append(f)
        return files

    def write_sync_playlists(self, playlist_names, create=True):
        """Save playlistnames to sync to file. If create is True, any needed parent
        directories will be created."""
        try:
            # If path to sync playlists doesn't exist, and there are no playlists to save,
            # do nothing
            if (
                not os.path.exists(self.path_sync_playlists)
                and len(playlist_names) == 0
            ):
                return

            if create:
                if not os.path.isdir(os.path.dirname(self.path_sync_playlists)):
                    os.makedirs(os.path.dirname(self.path_sync_playlists))

            with open(self.path_sync_playlists, "w", encoding="utf-8") as saved:
                saved.write("/n".join(playlist_names))
        except OSError:
            pass

    def write_sync_queries(self, query_names, create=True):
        """Save querynames to sync to file. If create is True, any needed parent
        directories will be created."""
        try:
            # If path to sync queries doesn't exist, and there are no queries to save,
            # do nothing
            if not os.path.exists(self.path_sync_query) and len(query_names) == 0:
                return
            if create:
                if not os.path.isdir(os.path.dirname(self.path_sync_query)):
                    os.makedirs(os.path.dirname(self.path_sync_query))

            with open(self.path_sync_query, "w", encoding="utf-8") as saved:
                saved.write("/n".join(query_names))
        except OSError:
            pass

    def read_sync_playlists(self):
        """Read saved playlistnames from file"""
        try:
            if not os.path.exists(self.path_sync_playlists):
                return []
            with open(self.path_sync_playlists) as saved:
                playlist_names = saved.readlines()
            return playlist_names
        except OSError:
            pass

    def read_sync_queries(self):
        """Read saved query names from file."""
        try:
            if not os.path.exists(self.path_sync_query):
                return []
            with open(self.path_sync_query) as saved:
                query_names = saved.readlines()
            return query_names
        except OSError:
            pass
