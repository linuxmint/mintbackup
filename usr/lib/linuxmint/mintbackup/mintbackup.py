#!/usr/bin/python3
import apt
import gettext
import gi
import hashlib
import os
import stat
import subprocess
import sys
import tarfile
import threading
import time
gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import Gtk, GdkPixbuf, Gio, GLib, XApp

import aptdaemon.client
from aptdaemon.enums import *
from aptdaemon.gtk3widgets import AptErrorDialog, AptConfirmDialog, AptProgressDialog, AptStatusIcon
import aptdaemon.errors

import setproctitle
setproctitle.setproctitle("mintbackup")

# i18n
gettext.install("mintbackup", "/usr/share/linuxmint/locale")

HOME = os.path.expanduser("~")
UI_FILE = '/usr/share/linuxmint/mintbackup/mintbackup.ui'
META_FILE = ".meta.mint"

BACKUP_DIR = os.path.join(GLib.get_user_special_dir(GLib.USER_DIRECTORY_DOCUMENTS), _("Backups"))
if not os.path.exists(BACKUP_DIR):
    print("Creating backup directory in %s" % BACKUP_DIR)
    os.makedirs(BACKUP_DIR)

(TAB_START, TAB_FILE_BACKUP_1, TAB_FILE_BACKUP_2, TAB_FILE_BACKUP_3, TAB_FILE_BACKUP_4, TAB_FILE_BACKUP_5, TAB_FILE_RESTORE_1, TAB_FILE_RESTORE_3, TAB_FILE_RESTORE_4,
TAB_PKG_BACKUP_1, TAB_PKG_BACKUP_2, TAB_PKG_RESTORE_1, TAB_PKG_RESTORE_2, TAB_PKG_RESTORE_3) = range(14)

def print_timing(func):
    def wrapper(*arg):
        t1 = time.time()
        res = func(*arg)
        t2 = time.time()
        print('%s took %0.3f ms' % (func.__name__, (t2 - t1) * 1000.0))
        return res
    return wrapper

class MintBackup:

    def __init__(self):
        self.builder = Gtk.Builder()
        self.builder.add_from_file(UI_FILE)

        self.settings = Gio.Settings("com.linuxmint.backup")
        self.follow_links = self.settings.get_boolean("backup-follow-symlink")

        self.notebook = self.builder.get_object("notebook1")
        self.progressbar = self.builder.get_object("progressbar1")
        self.restore_progressbar = self.builder.get_object("progressbar2")

        self.notebook.set_current_page(TAB_START)

        # inidicates whether an operation is taking place.
        self.operating = False

        # tarfile
        self.tar_archive = None
        self.home_directory = os.path.expanduser("~")
        self.backup_dest = None

        # page 0
        self.builder.get_object("button_backup_files").connect("clicked", self.go_to_tab, TAB_FILE_BACKUP_1)
        self.builder.get_object("button_restore_files").connect("clicked", self.go_to_tab, TAB_FILE_RESTORE_1)
        self.builder.get_object("button_backup_packages").connect("clicked", self.backup_pkg_load_from_mintinstall)
        self.builder.get_object("button_restore_packages").connect("clicked", self.go_to_tab, TAB_PKG_RESTORE_1)

        # set up exclusions page
        self.iconTheme = Gtk.IconTheme.get_default()
        self.dir_icon = self.iconTheme.load_icon("folder-symbolic", 16, 0)
        self.file_icon = self.iconTheme.load_icon("folder-documents-symbolic", 16, 0)
        treeview = self.builder.get_object("treeview_excludes")
        renderer = Gtk.CellRendererPixbuf()
        column = Gtk.TreeViewColumn("", renderer)
        column.add_attribute(renderer, "pixbuf", 1)
        treeview.append_column(column)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("", renderer)
        column.add_attribute(renderer, "text", 0)
        treeview.append_column(column)
        self.excludes_model = Gtk.ListStore(str, GdkPixbuf.Pixbuf, str)
        self.excludes_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        treeview.set_model(self.excludes_model)
        self.excludes_model.append([BACKUP_DIR[len(self.home_directory) + 1:], self.dir_icon, BACKUP_DIR])
        for item in self.settings.get_strv("excluded-paths"):
            item = os.path.expanduser(item)
            if os.path.exists(item):
                if os.path.isdir(item):
                    self.excludes_model.append([item[len(self.home_directory) + 1:], self.dir_icon, item])
                else:
                    self.excludes_model.append([item[len(self.home_directory) + 1:], self.file_icon, item])
        self.builder.get_object("button_add_file").connect("clicked", self.add_item_to_treeview, treeview, self.file_icon, Gtk.FileChooserAction.OPEN, False)
        self.builder.get_object("button_add_folder").connect("clicked", self.add_item_to_treeview, treeview, self.dir_icon, Gtk.FileChooserAction.SELECT_FOLDER, False)
        self.builder.get_object("button_remove_exclude").connect("clicked", self.remove_item_from_treeview, treeview)

        # set up inclusions page
        treeview = self.builder.get_object("treeview_includes")
        renderer = Gtk.CellRendererPixbuf()
        column = Gtk.TreeViewColumn("", renderer)
        column.add_attribute(renderer, "pixbuf", 1)
        treeview.append_column(column)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn('', renderer)
        column.add_attribute(renderer, "text", 0)
        treeview.append_column(column)
        self.includes_model = Gtk.ListStore(str, GdkPixbuf.Pixbuf, str)
        self.includes_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        treeview.set_model(self.includes_model)
        for item in self.settings.get_strv("included-hidden-paths"):
            item = os.path.expanduser(item)
            if os.path.exists(item):
                if os.path.isdir(item):
                    self.includes_model.append([item[len(self.home_directory) + 1:], self.dir_icon, item])
                else:
                    self.includes_model.append([item[len(self.home_directory) + 1:], self.file_icon, item])
        self.builder.get_object("button_include_hidden_files").connect("clicked", self.add_item_to_treeview, treeview, self.file_icon, Gtk.FileChooserAction.OPEN, True)
        self.builder.get_object("button_include_hidden_dirs").connect("clicked", self.add_item_to_treeview, treeview, self.dir_icon, Gtk.FileChooserAction.SELECT_FOLDER, True)
        self.builder.get_object("button_remove_include").connect("clicked", self.remove_item_from_treeview, treeview)

        # Errors treeview for backup
        ren = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "text", 0)
        self.builder.get_object("treeview_backup_errors").append_column(column)
        column = Gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "text", 1)
        self.builder.get_object("treeview_backup_errors").append_column(column)

        # Errors treeview for restore. yeh.
        ren = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "text", 0)
        self.builder.get_object("treeview_restore_errors").append_column(column)
        column = Gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "text", 1)
        self.builder.get_object("treeview_restore_errors").append_column(column)
        # model.
        self.errors = Gtk.ListStore(str, str)

        # nav buttons
        self.builder.get_object("button_back").connect("clicked", self.back_callback)
        self.builder.get_object("button_forward").connect("clicked", self.forward_callback)
        self.builder.get_object("button_apply").connect("clicked", self.forward_callback)

        self.builder.get_object("button_back").hide()
        self.builder.get_object("button_forward").hide()
        self.main_window = self.builder.get_object("main_window")
        self.main_window.connect("destroy", self.on_close)
        self.main_window.set_title(_("Backup Tool"))
        self.main_window.show()

        # packages list
        t = self.builder.get_object("treeview_packages")
        self.builder.get_object("button_select").connect("clicked", self.set_selection, t, True, False)
        self.builder.get_object("button_deselect").connect("clicked", self.set_selection, t, False, False)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.toggled_cb, t)
        c1 = Gtk.TreeViewColumn("", tog, active=0)
        c1.set_cell_data_func(tog, self.celldatamethod_checkbox)
        t.append_column(c1)
        c2 = Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=2)
        t.append_column(c2)

        # choose a package list
        t = self.builder.get_object("treeview_package_list")
        self.builder.get_object("button_select_list").connect("clicked", self.set_selection, t, True, True)
        self.builder.get_object("button_deselect_list").connect("clicked", self.set_selection, t, False, True)
        self.builder.get_object("button_refresh").connect("clicked", self.restore_pkg_load_from_file)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.toggled_cb, t)
        c1 = Gtk.TreeViewColumn("", tog, active=0, activatable=2)
        c1.set_cell_data_func(tog, self.celldatamethod_checkbox)
        t.append_column(c1)
        c2 = Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=1)
        t.append_column(c2)

        file_filter = Gtk.FileFilter()
        file_filter.add_pattern ("*.list");
        filechooser = self.builder.get_object("filechooserbutton_package_source")
        filechooser.connect("file-set", self.restore_pkg_validate_file)
        filechooser.set_filter(file_filter)

        self.builder.get_object("filechooserbutton_restore_source").set_current_folder(BACKUP_DIR)
        self.builder.get_object("filechooserbutton_backup_dest").set_current_folder(BACKUP_DIR)
        self.builder.get_object("filechooserbutton_package_source").set_current_folder(BACKUP_DIR)

    def show_message(self, message, message_type=Gtk.MessageType.WARNING):
        dialog = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT, message_type, Gtk.ButtonsType.OK, message)
        dialog.set_title(_("Backup Tool"))
        dialog.set_position(Gtk.WindowPosition.CENTER)
        dialog.run()
        dialog.destroy()

    def add_item_to_treeview(self, widget, treeview, icon, mode, show_hidden=False):
        # Add a file or directory to treeview
        dialog = Gtk.FileChooserDialog(_("Backup Tool"), None, mode, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        dialog.set_current_folder(self.home_directory)
        dialog.set_select_multiple(True)
        dialog.set_show_hidden(show_hidden)
        if dialog.run() == Gtk.ResponseType.OK:
            filenames = dialog.get_filenames()
            for filename in filenames:
                if not filename.find(self.home_directory):
                    found = False
                    model = treeview.get_model()
                    for row in model:
                        if row[2] == filename:
                            found = True
                    if not found:
                        treeview.get_model().append([filename[len(self.home_directory) + 1:], icon, filename])
                else:
                    self.show_message(_("%s is not located in your home directory.") % filename)
        dialog.destroy()

    def remove_item_from_treeview(self, button, treeview):
        # Remove the item from the treeview
        model = treeview.get_model()
        selection = treeview.get_selection()
        selected_rows = selection.get_selected_rows()[1]
        args = [(model.get_iter(path)) for path in selected_rows]
        for iter in args:
            model.remove(iter)

    def on_close(self, widget):
        # Window destroyed
        if self.tar_archive is not None:
            self.tar_archive.close()
            self.tar_archive = None
        if self.operating:
            self.operating = False
        else:
            sys.exit(0)

    def go_to_tab(self, widget, tab):
        self.notebook.set_current_page(tab)
        self.builder.get_object("button_back").show()
        self.builder.get_object("button_back").set_sensitive(True)
        self.builder.get_object("button_forward").show()
        if tab == TAB_PKG_RESTORE_1:
            self.builder.get_object("button_forward").set_sensitive(False)
        else:
            self.builder.get_object("button_forward").set_sensitive(True)

    def forward_callback(self, widget):
        # Go forward
        self.backup_dest = self.builder.get_object("filechooserbutton_backup_dest").get_filename()
        sel = self.notebook.get_current_page()
        self.builder.get_object("button_back").set_sensitive(True)
        if sel == TAB_FILE_BACKUP_1:
            # Choose the destination for the backup
            if self.backup_dest is None:
                self.show_message(_("Please choose a directory."))
                return
            if not (os.path.exists(self.backup_dest) and os.access(self.backup_dest, os.W_OK)):
                self.show_message(_("You do not have the permission to write in the selected directory."))
                return
            self.notebook.set_current_page(TAB_FILE_BACKUP_2)
        elif sel == TAB_FILE_BACKUP_2:
            # Excludes page: Show includes page
            self.notebook.set_current_page(TAB_FILE_BACKUP_3)
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_apply").show()
        elif sel == TAB_FILE_BACKUP_3:
            # Includes page: Show progress page and start the backup
            self.notebook.set_current_page(TAB_FILE_BACKUP_4)
            self.builder.get_object("button_apply").set_sensitive(False)
            self.builder.get_object("button_back").set_sensitive(False)
            # Calculate excludes
            self.excluded_dirs = []
            self.excluded_files = []
            for row in self.excludes_model:
                item = row[2]
                if os.path.exists(item):
                    if os.path.isdir(item):
                        self.excluded_dirs.append(item)
                    else:
                        self.excluded_files.append(item)
            # Save excludes in GSettings
            excludes = []
            for row in self.excludes_model:
                path = row[2]
                path = path.replace(self.home_directory, "~")
                excludes.append(path)
            self.settings.set_strv("excluded-paths", excludes)
            # Calculate includes
            self.included_dirs = []
            self.included_files = []
            for row in self.includes_model:
                item = row[2]
                if os.path.exists(item):
                    if os.path.isdir(item):
                        self.included_dirs.append(item)
                    else:
                        self.included_files.append(item)
            # Save includes in GSettings
            includes = []
            for row in self.includes_model:
                path = row[2]
                path = path.replace(self.home_directory, "~")
                includes.append(path)
            self.settings.set_strv("included-hidden-paths", includes)
            thread = threading.Thread(target=self.backup)
            thread.daemon = True
            thread.start()
        elif sel == TAB_FILE_BACKUP_4:
            # show info page.
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_back").hide()
            self.notebook.set_current_page(TAB_FILE_BACKUP_5)
        elif sel == TAB_FILE_RESTORE_1:
            # sanity check the files (file --mimetype)
            self.restore_source = self.builder.get_object("filechooserbutton_restore_source").get_filename()
            self.overwrite_existing_files = self.builder.get_object("radiobutton_restore_all").get_active()
            if not self.restore_source or self.restore_source == "":
                self.show_message(_("Please choose a backup file."))
                return
            try:
                self.tar_archive = tarfile.open(self.restore_source, "r")
                try:
                    # We don't need META INFO but we want to make sure the backup was made with mintbackup (i.e. from and to a home dir, not some random archive.)
                    self.tar_archive.getmember(META_FILE)
                except Exception as e:
                    self.show_message(_("This backup file is either too old or it was created with a different tool. Please extract it manually."))
                    return
                self.builder.get_object("button_apply").hide()
                self.builder.get_object("button_back").hide()
                self.notebook.set_current_page(TAB_FILE_RESTORE_3)
                thread = threading.Thread(target=self.restore)
                thread.daemon = True
                thread.start()
            except Exception as detail:
                self.show_message(_("An error occurred while opening the backup file: %s."))
                return
        elif sel == TAB_PKG_BACKUP_1:
            # show progress of packages page
            self.builder.get_object("button_forward").set_sensitive(False)
            self.builder.get_object("button_back").set_sensitive(False)
            self.notebook.set_current_page(TAB_PKG_BACKUP_2)
            self.backup_pkg_save_to_file()
        elif sel == TAB_PKG_RESTORE_1:
            self.restore_pkg_load_from_file()
        elif sel == TAB_PKG_RESTORE_2:
            inst = False
            model = self.builder.get_object("treeview_package_list").get_model()
            if len(model) == 0:
                self.show_message(_("No packages need to be installed."))
                return
            for row in model:
                if row[0]:
                    inst = True
                    break
            if not inst:
                self.show_message(_("Please select packages to install."))
                return
            else:
                self.restore_pkg_install_packages()

    def back_callback(self, widget):
        # Back button
        sel = self.notebook.get_current_page()
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_forward").show()
        if sel in [TAB_FILE_BACKUP_1, TAB_FILE_RESTORE_1, TAB_PKG_BACKUP_1, TAB_PKG_RESTORE_1]:
            self.notebook.set_current_page(TAB_START)
            self.builder.get_object("button_back").set_sensitive(False)
            self.builder.get_object("button_back").hide()
            self.builder.get_object("button_forward").hide()
            if self.tar_archive is not None:
                self.tar_archive.close()
                self.tar_archive = None
        else:
            sel = sel - 1
            if sel == 0:
                self.builder.get_object("button_back").hide()
                self.builder.get_object("button_forward").hide()
            self.notebook.set_current_page(sel)

    # FILE BACKUP FUNCTIONS
    #############################################################################################################################

    def scan_dirs(self, callback):
        for top, dirs, files in os.walk(top=self.home_directory, onerror=None, followlinks=self.follow_links):
            if not self.operating:
                break
            if top == self.home_directory:
                # Remove hidden dirs in the root of the home directory
                dirs[:] = [d for d in dirs if (not d.startswith(".") or os.path.join(top, d) in self.included_dirs)]

            # Remove excluded dirs in the home directory
            dirs[:] = [d for d in dirs if (not os.path.join(top, d) in self.excluded_dirs)]

            for f in files:
                if not self.operating:
                    break
                if top == self.home_directory:
                    # Skip hidden files in the root of the home directory, unless included
                    if f.startswith(".") and os.path.join(top, f) not in self.included_files:
                        continue
                path = os.path.join(top, f)
                rel_path = os.path.relpath(path)
                if os.path.exists(path):
                    if os.path.islink(path) and not self.follow_links:
                        # Skip links if appropriate
                        continue
                    if stat.S_ISFIFO(os.stat(path).st_mode):  # If file is a named pipe
                        # Skip named pipes, they can cause program to hang.
                        self.errors.append([_("Skipping %s because named pipes are not supported.") % path, None])
                        continue
                    if path not in self.excluded_files:
                        callback(path)

    def callback_count(self, path):
        self.num_files += 1
        if (self.num_files % 10000 == 0):
            GLib.idle_add(self.progressbar.pulse)

    def callback_add_to_tar(self, path):
        try:
            rel_path = os.path.relpath(path)
            GLib.idle_add(self.set_progress, rel_path)
            self.tar_archive.add(path, arcname=rel_path, recursive=False, exclude=None)
            self.archived_files += 1
        except Exception as detail:
            print(detail)
            self.errors.append([path, str(detail)])

    def set_progress(self, path):
        fraction = float(self.archived_files) / float(self.num_files)
        int_fraction = int(fraction * 100)
        self.progressbar.set_fraction(fraction)
        self.progressbar.set_text(str(int_fraction) + "%")
        self.builder.get_object("label_current_file").set_label(_("Backing up:"))
        self.builder.get_object("label_current_file_value").set_label(path)
        XApp.set_window_progress(self.main_window, int_fraction)

    def set_widgets_before_backup(self):
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_forward").hide()
        self.builder.get_object("button_back").hide()
        self.progressbar.set_text(_("Calculating..."))

    def set_widgets_after_backup(self):
        if len(self.errors) > 0:
            self.builder.get_object("label_finished_status").set_markup(_("The following errors occurred:"))
            self.builder.get_object("image_finished").set_from_icon_name("dialog-error-symbolic", Gtk.IconSize.DIALOG)
            self.builder.get_object("treeview_backup_errors").set_model(self.errors)
            self.builder.get_object("win_errors").show_all()
        else:
            if not self.operating:
                self.builder.get_object("label_finished_status").set_markup(_("The backup was aborted."))
                self.builder.get_object("image_finished").set_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.DIALOG)
            else:
                self.builder.get_object("image_finished").set_from_icon_name("mintbackup-success-symbolic", Gtk.IconSize.DIALOG)
                self.builder.get_object("label_finished_status").set_markup(_("Your files were successfully saved in %s.") % self.filename)
        self.notebook.next_page()
        self.operating = False
        XApp.set_window_progress(self.main_window, 0)

    @print_timing
    def backup(self):
        # Does the actual copying
        try:
            self.operating = True

            backup_format = self.settings.get_string("backup-format")
            if backup_format == "tar":
                backup_mode = "w"
            elif backup_format == "tar.gz":
                backup_mode = "w:gz"
            elif backup_format == "tar.bz2":
                backup_mode = "w:bz2"
            elif backup_format == "tar.xz":
                backup_mode = "w:xz"
            else:
                print("Invalid format %s. Please choose between tar, tar.gz, tar.bz2 or tar.xz." % backup_format)
                self.operating = False
                sys.exit(1)

            GLib.idle_add(self.set_widgets_before_backup)

            os.chdir(self.home_directory)

            # get a count of all the files
            self.num_files = 0
            self.scan_dirs(self.callback_count)

            # Create META file
            try:
                of = os.path.join(self.backup_dest, META_FILE)
                lines = ["num_files: %s\n" % (self.num_files)]
                with open(of, "w") as out:
                    out.writelines(lines)
            except Exception as detail:
                print(detail)
                self.errors.append([_("Warning: The meta file could not be saved. This backup will not be accepted for restoration."), None])

            self.tar_archive = None
            timestamp = time.strftime("%Y-%m-%d-%H%M-backup", time.localtime())
            self.temp_filename = os.path.join(self.backup_dest, "%s.%s.part" % (timestamp, backup_format))
            self.filename = os.path.join(self.backup_dest, "%s.%s" % (timestamp, backup_format))

            try:
                self.tar_archive = tarfile.open(name=self.temp_filename, dereference=self.follow_links, mode=backup_mode, bufsize=1024)
                mintfile = os.path.join(self.backup_dest, META_FILE)
                self.tar_archive.add(mintfile, arcname=META_FILE, recursive=False, exclude=None)
            except Exception as detail:
                print(detail)
                self.errors.append([str(detail), None])

            self.archived_files = 0
            self.scan_dirs(self.callback_add_to_tar)

            try:
                self.tar_archive.close()
                os.remove(mintfile)
                os.rename(self.temp_filename, self.filename)
            except Exception as detail:
                print(detail)
                self.errors.append([str(detail), None])

            if self.archived_files < self.num_files:
                self.errors.append([_("Warning: Some files were not saved. Only %(archived)d files were backed up out of %(total)d.") % {'archived': self.archived_files, 'total': self.num_files}, None])

            GLib.idle_add(self.set_widgets_after_backup)

        except Exception as e:
            print(e)

    # FILE RESTORE FUNCTIONS
    #############################################################################################################################

    def set_restore_progress(self, path):
        fraction = float(self.restored_files) / float(self.num_files)
        int_fraction = int(fraction * 100)
        self.restore_progressbar.set_fraction(fraction)
        self.restore_progressbar.set_text(str(int_fraction) + "%")
        self.builder.get_object("label_current_file1").set_label(_("Restoring:"))
        self.builder.get_object("label_current_file_value1").set_label(path)
        XApp.set_window_progress(self.main_window, int_fraction)

    def set_widgets_before_restore(self):
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_forward").hide()
        self.builder.get_object("button_back").hide()

    def set_widgets_after_restore(self):
        if len(self.errors) > 0:
            self.builder.get_object("label_finished_status1").set_markup(_("The following errors occurred:"))
            self.builder.get_object("image_finished1").set_from_icon_name("dialog-error-symbolic", Gtk.IconSize.DIALOG)
            self.builder.get_object("treeview_restore_errors").set_model(self.errors)
            self.builder.get_object("win_errors1").show_all()
        else:
            if not self.operating:
                self.builder.get_object("label_finished_status1").set_markup(_("The restoration was aborted."))
                self.builder.get_object("image_finished1").set_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.DIALOG)
            else:
                self.builder.get_object("image_finished1").set_from_icon_name("mintbackup-success-symbolic", Gtk.IconSize.DIALOG)
                self.builder.get_object("label_finished_status1").set_markup(_("Your files were successfully restored."))
        self.notebook.next_page()
        self.operating = False
        XApp.set_window_progress(self.main_window, 0)

    def get_checksum_for_path(self, path):
        # Return the checksum of the file
        with open(path, 'rb') as f:
            return self.get_checksum_for_file(f)

    def get_checksum_for_file(self, file):
        # Return the checksum of the file
        BUF_SIZE = 65536
        sha1 = hashlib.sha1()
        while True:
            data = file.read(BUF_SIZE)
            if not data:
                break
            sha1.update(data)
        return sha1.hexdigest()

    def restore(self):
        try:
            # Restore from archive
            self.operating = True

            GLib.idle_add(self.set_widgets_before_restore)

            # restore from archive
            self.restored_files = 0
            members = self.tar_archive.getmembers()
            self.num_files = len(members) - 1 # Don't count the META file
            for member in self.tar_archive.getmembers():
                if not self.operating:
                    break
                if member.name == META_FILE:
                    # skip mintbackup file
                    continue
                target = os.path.join(self.home_directory, member.name)
                if member.isdir():
                    if not os.path.exists(target):
                        try:
                            os.mkdir(target)
                            os.chown(target, member.uid, member.gid)
                            os.chmod(target, member.mode)
                            os.utime(target, (member.mtime, member.mtime))
                        except Exception as detail:
                            print(detail)
                            self.errors.append([target, str(detail)])
                if member.isreg():
                    dir = os.path.split(target)
                    if not os.path.exists(dir[0]):
                        try:
                            os.makedirs(dir[0])
                        except Exception as detail:
                            print(detail)
                            self.errors.append([dir[0], str(detail)])

                    try:
                        GLib.idle_add(self.set_restore_progress, member.name)
                        if os.path.exists(target):
                            # Skip unless we're overwriting existing files
                            if not self.overwrite_existing_files:
                                self.restored_files += 1
                                print("Skipping existing file: %s" % target)
                                continue

                            # Skip if the files are identical
                            if member.size == os.path.getsize(target) and member.mtime == os.path.getmtime(target):
                                gz = self.tar_archive.extractfile(member)
                                if self.get_checksum_for_file(gz) in self.get_checksum_for_path(target):
                                    gz.close()
                                    self.restored_files += 1
                                    print("Skipping identical file: %s" % target)
                                    continue
                                os.remove(target)
                        self.tar_archive.extract(member, self.home_directory)
                        self.restored_files += 1
                    except Exception as detail:
                        print(detail)
                        self.errors.append([member.name, str(detail)])

            try:
                self.tar_archive.close()
            except:
                pass

            if self.restored_files <  self.num_files:
                self.errors.append([_("Warning: Only %(number)d files were restored out of %(total)d.") % {'number': self.restored_files, 'total':  self.num_files}, None])

            GLib.idle_add(self.set_widgets_after_restore)
        except Exception as e:
            print(e)

    #############################################################################################################################

    @print_timing
    def backup_pkg_load_from_mintinstall(self, button):
        # Load the package list into the treeview
        self.builder.get_object("button_back").show()
        self.builder.get_object("button_back").set_sensitive(True)
        self.builder.get_object("button_forward").show()
        self.notebook.set_current_page(TAB_PKG_BACKUP_1)

        model = Gtk.ListStore(bool, str, str)
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)

        cache = apt.Cache()
        settings = Gio.Settings("com.linuxmint.install")
        for name in settings.get_strv("installed-apps"):
            try:
                if name in cache:
                    pkg = cache[name]
                    if pkg.is_installed:
                        desc = pkg.name + "\n<small>" + pkg.installed.summary.replace("&", "&amp;") + "</small>"
                    elif pkg.candidate is not None:
                        desc = pkg.name + "\n<small>" + pkg.candidate.summary.replace("&", "&amp;") + "</small>"
                    model.append([True, pkg.name, desc])
            except Exception as e:
                print(e)
        self.builder.get_object("treeview_packages").set_model(model)

    def toggled_cb(self, ren, path, treeview):
        model = treeview.get_model()
        iter = model.get_iter(path)
        if iter != None:
            checked = model.get_value(iter, 0)
            model.set_value(iter, 0, (not checked))

    def celldatamethod_checkbox(self, column, cell, model, iter, user_data):
        checked = model.get_value(iter, 0)
        cell.set_property("active", checked)

    def backup_pkg_save_to_file(self):
        # Save the package selection
        filename = time.strftime("%Y-%m-%d-%H%M-packages.list", time.localtime())
        file_path = os.path.join(BACKUP_DIR, filename)
        with open(file_path, "w") as f:
            for row in self.builder.get_object("treeview_packages").get_model():
                if row[0]:
                    f.write("%s\t%s\n" % (row[1], "install"))

        self.builder.get_object("label_packages_done_value").set_label(_("Your software selection was saved in %s") % file_path)
        self.notebook.set_current_page(TAB_PKG_BACKUP_2)
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_back").hide()
        self.builder.get_object("button_forward").hide()

    def restore_pkg_validate_file(self, filechooser):
        # Check the file validity
        self.package_source = filechooser.get_filename()
        try:
            with open(self.package_source, "r") as source:
                error = False
                for line in source:
                    line = line.rstrip("\r\n")
                    if line != "":
                        if not line.endswith("\tinstall"):
                            self.show_message(_("The selected file is not a valid software selection."))
                            self.builder.get_object("button_forward").set_sensitive(False)
                            return
            self.builder.get_object("button_forward").set_sensitive(True)
        except Exception as detail:
            self.show_message(_("An error occurred while reading the file."))

    def restore_pkg_load_from_file(self, widget=None):
        # Load package list into treeview
        self.builder.get_object("button_forward").hide()
        self.builder.get_object("button_apply").show()
        self.builder.get_object("button_apply").set_sensitive(True)
        model = Gtk.ListStore(bool, str, bool, str)
        self.builder.get_object("treeview_package_list").set_model(model)
        try:
            with open(self.package_source, "r") as source:
                cache = apt.Cache()
                for line in source:
                    line = line.rstrip("\r\n")
                    if line.startswith("#") or line == "":
                        continue
                    name = line.split("\t")[0]
                    error = "%s\n<small>%s</small>" % (name, _("Could not locate the package."))
                    if name in cache:
                        pkg = cache[name]
                        if not pkg.is_installed:
                            if pkg.candidate is not None:
                                status = "%s\n<small>%s</small>" % (name, pkg.candidate.summary.replace("&", "&amp;"))
                                model.append([True, status, True, pkg.name])
                            else:
                                model.append([False, error, False, pkg.name])
                    else:
                        model.append([False, error, False, error])
        except Exception as detail:
            self.show_message(_("An error occurred while reading the file."))
        if len(model) == 0:
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_back").hide()
            self.builder.get_object("button_apply").hide()
            self.notebook.set_current_page(TAB_PKG_RESTORE_3)
        else:
            self.notebook.set_current_page(TAB_PKG_RESTORE_2)
            self.builder.get_object("button_forward").set_sensitive(True)

    def apt_run_transaction(self, transaction):
        transaction.connect("finished", self.on_transaction_finish)
        dia = AptProgressDialog(transaction, parent=self.main_window)
        dia.run(close_on_finished=True, show_error=True, reply_handler=lambda: True, error_handler=self.apt_on_error)

    def apt_simulate_trans(self, trans):
        trans.simulate(reply_handler=lambda: self.apt_confirm_deps(trans), error_handler=self.apt_on_error)

    def apt_confirm_deps(self, trans):
        try:
            if [pkgs for pkgs in trans.dependencies if pkgs]:
                dia = AptConfirmDialog(trans, parent=self.main_window)
                res = dia.run()
                dia.hide()
                if res != Gtk.ResponseType.OK:
                    return
            self.apt_run_transaction(trans)
        except Exception as e:
            print(e)

    def apt_on_error(self, error):
        if isinstance(error, aptdaemon.errors.NotAuthorizedError):
            # Silently ignore auth failures
            return
        elif not isinstance(error, aptdaemon.errors.TransactionFailed):
            # Catch internal errors of the client
            error = aptdaemon.errors.TransactionFailed(ERROR_UNKNOWN, str(error))
        dia = AptErrorDialog(error)
        dia.run()
        dia.hide()

    def on_transaction_finish(self, transaction, exit_state):
        # Refresh
        self.restore_pkg_load_from_file()

    def restore_pkg_install_packages(self):
        packages = []
        model = self.builder.get_object("treeview_package_list").get_model()
        for row in model:
            if row[3]:
                packages.append(row[3])
        ac = aptdaemon.client.AptClient()
        ac.install_packages(packages, reply_handler=self.apt_simulate_trans, error_handler=self.apt_on_error)

    def set_selection(self, w, treeview, selection, check):
        # Select / deselect all
        model = treeview.get_model()
        for row in model:
            if check:
                if row[2]:
                    row[0] = selection
            else:
                row[0] = selection

if __name__ == "__main__":
    MintBackup()
    Gtk.main()
