#!/usr/bin/python3

import os
import sys
import subprocess
import gettext
import threading
import tarfile
import stat
import tempfile
import hashlib
from time import strftime, localtime
import apt
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf

# i18n
gettext.install("mintbackup", "/usr/share/linuxmint/locale")

HOME = os.path.expanduser("~")
UI_FILE = '/usr/share/linuxmint/mintbackup/mintbackup.ui'


class TarFileMonitor():

    """ Bit of a hack but I can figure out what tarfile is doing now.. (progress wise)
    """

    def __init__(self, target, callback):
        self.counter = 0
        self.size = 0
        self.f = open(target, "rb")
        self.name = self.f.name
        self.fileno = self.f.fileno
        self.callback = callback
        self.size = os.path.getsize(target)

    def read(self, size=None):
        bytes = 0
        if size is not None:
            bytes = self.f.read(size)
            if bytes:
                self.counter += len(bytes)
                self.callback(self.counter, self.size)
        else:
            bytes = self.f.read()
            if bytes is not None:
                self.counter += len(bytes)
                self.callback(self.counter, self.size)
        return bytes

    def close(self):
        self.f.close()


class mINIFile():

    """ Funkai little class for abuse-safety. all atrr's are set from file
    """

    def load_from_string(self, line):
        if line.find(":"):
            l = line.split(":")
            if len(l) >= 2:
                tmp = ":".join(l[1:]).rstrip("\r\n")
                setattr(self, l[0], tmp)
        elif line.find("="):
            l = line.split("=")
            if len(l) >= 2:
                tmp = "=".join(l[1:]).rstrip("\r\n")
                setattr(self, l[0], tmp)

    def load_from_list(self, list):
        for line in list:
            self.load_from_string(line)

    def load_from_file(self, filename):
        try:
            fi = open(filename, "r")
            self.load_from_list(fi.readlines())
            fi.close()
        except:
            pass


class MessageDialog:

    """ Handy. Makes message dialogs easy :D
    """

    def __init__(self, title, message, style):
        self.title = title
        self.message = message
        self.style = style

    def show(self):

        """ Show me on screen
        """

        dialog = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT, self.style, Gtk.ButtonsType.OK, self.message)
        dialog.set_title(_("Backup Tool"))
        dialog.set_position(Gtk.WindowPosition.CENTER)
        dialog.run()
        dialog.destroy()


class MintBackup:

    """ The main class of the app
    """

    def __init__(self):
        self.builder = Gtk.Builder()
        self.builder.add_from_file(UI_FILE)

        # handle command line filenames
        if len(sys.argv) > 1:
            if len(sys.argv) == 2:
                filebackup = sys.argv[1]
                self.builder.get_object("filechooserbutton_restore_source").set_filename(filebackup)
                self.builder.get_object("notebook1").set_current_page(6)
            else:
                print("usage: " + sys.argv[0] + " filename.backup")
                sys.exit(1)
        else:
            self.builder.get_object("notebook1").set_current_page(0)

        # inidicates whether an operation is taking place.
        self.operating = False

        # preserve permissions?
        self.preserve_perms = True
        # preserve times?
        self.preserve_times = True
        # post-check files?
        self.postcheck = True
        # follow symlinks?
        self.follow_links = False
        # error?
        self.error = None
        # tarfile
        self.tar = None
        self.backup_source = None
        self.backup_dest = None

        # by default we restore archives, not directories (unless user chooses otherwise)
        self.restore_archive = True

        # page 0
        self.builder.get_object("button_backup_files").connect("clicked", self.wizard_buttons_cb, 1)
        self.builder.get_object("button_restore_files").connect("clicked", self.wizard_buttons_cb, 6)
        self.builder.get_object("button_backup_packages").connect("clicked", self.wizard_buttons_cb, 10)
        self.builder.get_object("button_restore_packages").connect("clicked", self.wizard_buttons_cb, 14)

        # set up backup page 1 (source/dest/options)
        # Displayname, [tarfile mode, file extension]
        comps = Gtk.ListStore(str, str, str)
        comps.append([_("Preserve structure"), None, None])
        # file extensions mintBackup specific
        comps.append([_(".tar file"), "w", ".tar"])
        comps.append([_(".tar.bz2 file"), "w:bz2", ".tar.bz2"])
        comps.append([_(".tar.gz file"), "w:gz", ".tar.gz"])
        self.builder.get_object("combobox_compress").set_model(comps)
        self.builder.get_object("combobox_compress").set_active(0)

        # backup overwrite options
        overs = Gtk.ListStore(str)
        overs.append([_("Never")])
        overs.append([_("Size mismatch")])
        overs.append([_("Modification time mismatch")])
        overs.append([_("Checksum mismatch")])
        overs.append([_("Always")])
        self.builder.get_object("combobox_delete_dest").set_model(overs)
        self.builder.get_object("combobox_delete_dest").set_active(3)

        # advanced options
        self.builder.get_object("checkbutton_integrity").set_active(self.postcheck)
        self.builder.get_object("checkbutton_integrity").connect("clicked", self.handle_checkbox)
        self.builder.get_object("checkbutton_perms").set_active(self.preserve_perms)
        self.builder.get_object("checkbutton_perms").connect("clicked", self.handle_checkbox)
        self.builder.get_object("checkbutton_times").set_active(self.preserve_times)
        self.builder.get_object("checkbutton_times").connect("clicked", self.handle_checkbox)
        self.builder.get_object("checkbutton_links").set_active(self.follow_links)
        self.builder.get_object("checkbutton_links").connect("clicked", self.handle_checkbox)
        # set up exclusions page
        self.iconTheme = Gtk.IconTheme.get_default()
        self.dirIcon = self.iconTheme.load_icon("folder", 16, 0)
        self.fileIcon = self.iconTheme.load_icon("document-new", 16, 0)
        ren = Gtk.CellRendererPixbuf()
        column = Gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "pixbuf", 1)
        self.builder.get_object("treeview_excludes").append_column(column)
        ren = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_("Excluded paths"), ren)
        column.add_attribute(ren, "text", 0)
        self.builder.get_object("treeview_excludes").append_column(column)
        self.builder.get_object("treeview_excludes").set_model(Gtk.ListStore(str, GdkPixbuf.Pixbuf, str))
        self.builder.get_object("button_add_file").connect("clicked", self.add_file_exclude)
        self.builder.get_object("button_add_folder").connect("clicked", self.add_folder_exclude)
        self.builder.get_object("button_remove_exclude").connect("clicked", self.remove_exclude)

        # set up overview page
        ren = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_("Type"), ren)
        column.add_attribute(ren, "markup", 0)
        self.builder.get_object("treeview_overview").append_column(column)
        ren = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_("Detail"), ren)
        column.add_attribute(ren, "text", 1)
        self.builder.get_object("treeview_overview").append_column(column)

        # Errors treeview for backup
        ren = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_("Path"), ren)
        column.add_attribute(ren, "text", 0)
        self.builder.get_object("treeview_backup_errors").append_column(column)
        column = Gtk.TreeViewColumn(_("Error"), ren)
        column.add_attribute(ren, "text", 1)
        self.builder.get_object("treeview_backup_errors").append_column(column)

        # Errors treeview for restore. yeh.
        ren = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_("Path"), ren)
        column.add_attribute(ren, "text", 0)
        self.builder.get_object("treeview_restore_errors").append_column(column)
        column = Gtk.TreeViewColumn(_("Error"), ren)
        column.add_attribute(ren, "text", 1)
        self.builder.get_object("treeview_restore_errors").append_column(column)
        # model.
        self.errors = Gtk.ListStore(str, str)

        # nav buttons
        self.builder.get_object("button_back").connect("clicked", self.back_callback)
        self.builder.get_object("button_forward").connect("clicked", self.forward_callback)
        self.builder.get_object("button_apply").connect("clicked", self.forward_callback)
        self.builder.get_object("button_cancel").connect("clicked", self.cancel_callback)

        self.builder.get_object("button_back").hide()
        self.builder.get_object("button_forward").hide()
        self.builder.get_object("main_window").connect("destroy", self.cancel_callback)
        self.builder.get_object("main_window").set_title(_("Backup Tool"))
        self.builder.get_object("main_window").show()

        # open archive button, opens an archive... :P
        self.builder.get_object("radiobutton_archive").connect("toggled", self.archive_switch)
        self.builder.get_object("radiobutton_dir").connect("toggled", self.archive_switch)
        self.builder.get_object("filechooserbutton_restore_source").connect("file-set", self.check_reset_file)

        self.builder.get_object("combobox_restore_del").set_model(overs)
        self.builder.get_object("combobox_restore_del").set_active(3)

        # packages list
        t = self.builder.get_object("treeview_packages")
        self.builder.get_object("button_select").connect("clicked", self.set_selection, t, True, False)
        self.builder.get_object("button_deselect").connect("clicked", self.set_selection, t, False, False)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.toggled_cb, t)
        c1 = Gtk.TreeViewColumn(_("Store?"), tog, active=0)
        c1.set_cell_data_func(tog, self.celldatamethod_checkbox)
        t.append_column(c1)
        c2 = Gtk.TreeViewColumn(_("Name"), Gtk.CellRendererText(), markup=2)
        t.append_column(c2)

        # choose a package list
        t = self.builder.get_object("treeview_package_list")
        self.builder.get_object("button_select_list").connect("clicked", self.set_selection, t, True, True)
        self.builder.get_object("button_deselect_list").connect("clicked", self.set_selection, t, False, True)
        self.builder.get_object("button_refresh").connect("clicked", self.refresh)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.toggled_cb, t)
        c1 = Gtk.TreeViewColumn(_("Install"), tog, active=0, activatable=2)
        c1.set_cell_data_func(tog, self.celldatamethod_checkbox)
        t.append_column(c1)
        c2 = Gtk.TreeViewColumn(_("Name"), Gtk.CellRendererText(), markup=1)
        t.append_column(c2)
        self.builder.get_object("filechooserbutton_package_source").connect("file-set", self.load_package_list_cb)

        # i18n - Page 0 (choose backup or restore)
        self.builder.get_object("label_wizard1").set_markup("<big><b>" + _("Backup or Restore") + "</b></big>")
        self.builder.get_object("label_wizard2").set_markup("<i>" + _("Choose from the following options") + "</i>")

        self.builder.get_object("label_create_backup").set_text(_("Backup files"))
        self.builder.get_object("label_restore_backup").set_text(_("Restore files"))
        self.builder.get_object("label_create_packages").set_text(_("Backup software selection"))
        self.builder.get_object("label_restore_packages").set_text(_("Restore software selection"))

        self.builder.get_object("label_detail1").set_markup("<small>" + _("Make a backup of your files") + "</small>")
        self.builder.get_object("label_detail2").set_markup("<small>" + _("Save the list of installed applications") + "</small>")
        self.builder.get_object("label_detail3").set_markup("<small>" + _("Restore a previous backup") + "</small>")
        self.builder.get_object("label_detail4").set_markup("<small>" + _("Restore previously installed applications") + "</small>")

        # i18n - Page 1 (choose backup directories)
        self.builder.get_object("label_title_destination").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.builder.get_object("label_caption_destination").set_markup("<i>" + _("Please select a source and a destination for your backup") + "</i>")
        self.builder.get_object("label_backup_source").set_label(_("Source:"))
        self.builder.get_object("label_backup_dest").set_label(_("Destination:"))
        self.builder.get_object("label_expander").set_label(_("Advanced options"))
        self.builder.get_object("label_backup_desc").set_label(_("Description:"))
        self.builder.get_object("label_compress").set_label(_("Output:"))
        self.builder.get_object("label_overwrite_dest").set_label(_("Overwrite:"))
        self.builder.get_object("checkbutton_integrity").set_label(_("Confirm integrity"))
        self.builder.get_object("checkbutton_links").set_label(_("Follow symlinks"))
        self.builder.get_object("checkbutton_perms").set_label(_("Preserve permissions"))
        self.builder.get_object("checkbutton_times").set_label(_("Preserve timestamps"))

        # i18n - Page 2 (choose files/directories to exclude)
        self.builder.get_object("label_title_exclude").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.builder.get_object("label_caption_exclude").set_markup("<i>" + _("Please select any files or directories you want to exclude") + "</i>")
        self.builder.get_object("label_add_file").set_label(_("Exclude files"))
        self.builder.get_object("label_add_folder").set_label(_("Exclude directories"))
        self.builder.get_object("label_remove").set_label(_("Remove"))

        # i18n - Page 3 (backup overview)
        self.builder.get_object("label_title_review").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.builder.get_object("label_caption_review").set_markup("<i>" + _("Please review the information below before starting the backup") + "</i>")

        # i18n - Page 4 (backing up status)
        self.builder.get_object("label_title_copying").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.builder.get_object("label_caption_copying").set_markup("<i>" + _("Please wait while your files are being backed up") + "</i>")
        self.builder.get_object("label_current_file").set_label(_("Backing up:"))

        # i18n - Page 5 (backup complete)
        self.builder.get_object("label_title_finished").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.builder.get_object("label_caption_finished").set_markup("<i>" + _("The backup is now finished") + "</i>")

        # i18n - Page 6 (Restore locations)
        self.builder.get_object("label_title_restore1").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.builder.get_object("label_caption_restore1").set_markup("<i>" + _("Please choose the type of backup to restore, its location and a destination") + "</i>")
        self.builder.get_object("radiobutton_archive").set_label(_("Archive"))
        self.builder.get_object("radiobutton_dir").set_label(_("Directory"))
        self.builder.get_object("label_restore_source").set_label(_("Source:"))
        self.builder.get_object("label_restore_dest").set_label(_("Destination:"))
        self.builder.get_object("label_restore_advanced").set_label(_("Advanced options"))
        self.builder.get_object("label_restore_overwrite").set_label(_("Overwrite:"))

        # i18n - Page 7 (Restore overview)
        self.builder.get_object("label_title_restore2").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.builder.get_object("label_caption_restore2").set_markup("<i>" + _("Please review the information below") + "</i>")
        self.builder.get_object("label_overview_source").set_markup("<b>" + _("Source:") + "</b>")
        self.builder.get_object("label_overview_description").set_markup("<b>" + _("Description:") + "</b>")

        # i18n - Page 8 (restore status)
        self.builder.get_object("label_title_restore3").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.builder.get_object("label_caption_restore3").set_markup("<i>" + _("Please wait while your files are being restored") + "</i>")
        self.builder.get_object("label_restore_status").set_label(_("Restoring:"))

        # i18n - Page 9 (restore complete)
        self.builder.get_object("label_title_restore4").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.builder.get_object("label_caption_restore4").set_markup("<i>" + _("The restoration of the files is now finished") + "</i>")

        # i18n - Page 10 (packages)
        self.builder.get_object("label_title_software_backup1").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.builder.get_object("label_caption_software_backup1").set_markup("<i>" + _("Please choose a destination") + "</i>")
        self.builder.get_object("label_package_dest").set_label(_("Destination"))

        # i18n - Page 11 (package list)
        self.builder.get_object("label_title_software_backup2").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.builder.get_object("label_caption_software_backup2").set_markup("<i>" + _("The list below shows the packages you added to Linux Mint") + "</i>")
        self.builder.get_object("label_select").set_label(_("Select all"))
        self.builder.get_object("label_deselect").set_label(_("Deselect all"))

        # i18n - Page 12 (backing up packages)
        self.builder.get_object("label_title_software_backup3").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.builder.get_object("label_caption_software_backup3").set_markup("<i>" + _("Please wait while your software selection is being backed up") + "</i>")
        self.builder.get_object("label_current_package").set_label(_("Backing up:"))

        # i18n - Page 13 (packages done)
        self.builder.get_object("label_title_software_backup4").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.builder.get_object("label_caption_software_backup4").set_markup("<i>" + _("The backup is now finished") + "</i>")

        # i18n - Page 14 (package restore)
        self.builder.get_object("label_title_software_restore1").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
        self.builder.get_object("label_caption_software_restore1").set_markup("<i>" + _("Please select a saved software selection") + "</i>")
        self.builder.get_object("label_package_source").set_markup(_("Software selection:"))

        # i18n - Page 15 (packages list)
        self.builder.get_object("label_title_software_restore2").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
        self.builder.get_object("label_caption_software_restore2").set_markup("<i>" + _("Select the packages you want to install") + "</i>")
        self.builder.get_object("label_select_list").set_label(_("Select all"))
        self.builder.get_object("label_deselect_list").set_label(_("Deselect all"))
        self.builder.get_object("label_refresh").set_label(_("Refresh"))

        # i18n - Page 16 (packages install done)
        self.builder.get_object("label_title_software_restore3").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
        self.builder.get_object("label_caption_software_restore3").set_markup("<i>" + _("The restoration is now finished") + "</i>")
        self.builder.get_object("label_install_done_value").set_markup(_("Your package selection was restored successfully"))

    def abt_resp(self, w, r):
        if r == Gtk.ResponseType.CANCEL:
            w.hide()

    def check_reset_file(self, w):
        """ Handle the file-set signal
        """

        fileset = w.get_filename()
        if fileset not in self.backup_source:
            if self.tar is not None:
                self.tar.close()
                self.tar = None
        self.backup_source = fileset

    def archive_switch(self, w):
        """ Switch between archive and directory sources
        """

        if self.builder.get_object("radiobutton_archive").get_active():
            # dealing with archives
            self.restore_archive = True
            self.builder.get_object("filechooserbutton_restore_source").set_action(Gtk.FileChooserAction.OPEN)
        else:
            self.restore_archive = False
            self.builder.get_object("filechooserbutton_restore_source").set_action(Gtk.FileChooserAction.SELECT_FOLDER)

    def handle_checkbox(self, widget):
        """ Handler for checkboxes
        """

        if widget == self.builder.get_object("checkbutton_integrity"):
            self.postcheck = widget.get_active()
        elif widget == self.builder.get_object("checkbutton_perms"):
            self.preserve_perms = widget.get_active()
        elif widget == self.builder.get_object("checkbutton_times"):
            self.preserve_times = widget.get_active()
        elif widget == self.builder.get_object("checkbutton_links"):
            self.follow_links = widget.get_active()

    def add_file_exclude(self, widget):
        """ Exclude file
        """

        model = self.builder.get_object("treeview_excludes").get_model()
        dialog = Gtk.FileChooserDialog(_("Backup Tool"), None, Gtk.FileChooserAction.OPEN, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        dialog.set_current_folder(self.backup_source)
        dialog.set_select_multiple(True)
        if dialog.run() == Gtk.ResponseType.OK:
            filenames = dialog.get_filenames()
            for filename in filenames:
                if not filename.find(self.backup_source):
                    model.append([filename[len(self.backup_source) + 1:], self.fileIcon, filename])
                else:
                    message = MessageDialog(_("Invalid path"), _("%s is not located within your source directory. Not added.") % filename, Gtk.MessageType.WARNING)
                    message.show()
        dialog.destroy()

    def add_folder_exclude(self, widget):
        """ Exclude directory
        """

        model = self.builder.get_object("treeview_excludes").get_model()
        dialog = Gtk.FileChooserDialog(_("Backup Tool"), None, Gtk.FileChooserAction.SELECT_FOLDER, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        dialog.set_current_folder(self.backup_source)
        dialog.set_select_multiple(True)
        if dialog.run() == Gtk.ResponseType.OK:
            filenames = dialog.get_filenames()
            for filename in filenames:
                if not filename.find(self.backup_source):
                    model.append([filename[len(self.backup_source) + 1:], self.dirIcon, filename])
                else:
                    message = MessageDialog(_("Invalid path"), _("%s is not located within your source directory. Not added.") % filename, Gtk.MessageType.WARNING)
                    message.show()
        dialog.destroy()

    def remove_exclude(self, widget):
        """ Remove the exclude
        """

        model = self.builder.get_object("treeview_excludes").get_model()
        selection = self.builder.get_object("treeview_excludes").get_selection()
        selected_rows = selection.get_selected_rows()[1]
        # don't you just hate python? :) Here's another hack for python not to get confused with its own paths while we're deleting multiple stuff.
        # actually.. gtk is probably to blame here.
        args = [(model.get_iter(path)) for path in selected_rows]
        for iter in args:
            model.remove(iter)

    def cancel_callback(self, widget):
        """ Cancel clicked
        """

        if self.tar is not None:
            self.tar.close()
            self.tar = None
        if self.operating:
            # in the middle of a job, let the appropriate thread
            # handle the cancel
            self.operating = False
        else:
            # just quit :)
            Gtk.main_quit()

    def wizard_buttons_cb(self, widget, param):
        """ First page buttons
        """

        self.builder.get_object("notebook1").set_current_page(param)
        self.builder.get_object("button_back").show()
        self.builder.get_object("button_back").set_sensitive(True)
        self.builder.get_object("button_forward").show()
        if param == 14:
            self.builder.get_object("button_forward").set_sensitive(False)
        else:
            self.builder.get_object("button_forward").set_sensitive(True)

    def forward_callback(self, widget):
        """ Forward / next buttons
        """

        self.backup_source = self.builder.get_object("filechooserbutton_backup_source").get_filename()
        self.backup_dest = self.builder.get_object("filechooserbutton_backup_dest").get_filename()
        book = self.builder.get_object("notebook1")
        sel = book.get_current_page()
        self.builder.get_object("button_back").set_sensitive(True)
        if sel == 1:
            # choose source/dest
            if self.backup_source is None or self.backup_dest is None:
                MessageDialog(_("Backup Tool"), _("Please choose directories for the source and the destination"), Gtk.MessageType.WARNING).show()
                return
            if self.backup_source == self.backup_dest:
                MessageDialog(_("Backup Tool"), _("Please choose different directories for the source and the destination"), Gtk.MessageType.WARNING).show()
                return

            excludes = self.builder.get_object("treeview_excludes").get_model()
            auto_excludes = [HOME + "/.Trash", HOME + "/.local/share/Trash", HOME + "/.thumbnails"]
            for auto_exclude in auto_excludes:
                if os.path.exists(auto_exclude):
                    if not auto_exclude.find(self.backup_source):
                        excludes.append([auto_exclude[len(self.backup_source) + 1:], self.dirIcon, auto_exclude])

            book.set_current_page(2)
        elif sel == 2:
            self.description = self.builder.get_object("entry_desc").get_text()
            # show overview
            model = Gtk.ListStore(str, str)
            model.append(["<b>" + _("Source") + "</b>", self.backup_source])
            model.append(["<b>" + _("Destination") + "</b>", self.backup_dest])
            if self.description != "":
                model.append(["<b>" + _("Description") + "</b>", self.description])
            # find compression format
            sel = self.builder.get_object("combobox_compress").get_active()
            comp = self.builder.get_object("combobox_compress").get_model()
            model.append(["<b>" + _("Compression") + "</b>", comp[sel][0]])
            # find overwrite rules
            sel = self.builder.get_object("combobox_delete_dest").get_active()
            over = self.builder.get_object("combobox_delete_dest").get_model()
            model.append(["<b>" + _("Overwrite destination files") + "</b>", over[sel][0]])
            excludes = self.builder.get_object("treeview_excludes").get_model()
            for row in excludes:
                model.append(["<b>" + _("Exclude") + "</b>", row[2]])
            self.builder.get_object("treeview_overview").set_model(model)
            book.set_current_page(3)
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_apply").show()
        elif sel == 3:
            # start copying :D
            book.set_current_page(4)
            self.builder.get_object("button_apply").set_sensitive(False)
            self.builder.get_object("button_back").set_sensitive(False)
            self.operating = True
            thread = threading.Thread(group=None, target=self.backup, name="mintBackup-copy", args=(), kwargs={})
            thread.start()
        elif sel == 4:
            # show info page.
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_back").hide()
            book.set_current_page(5)
        elif sel == 6:
            # sanity check the files (file --mimetype)
            self.restore_source = self.builder.get_object("filechooserbutton_restore_source").get_filename()
            self.restore_dest = self.builder.get_object("filechooserbutton_restore_dest").get_filename()
            if not self.restore_source or self.restore_source == "":
                MessageDialog(_("Backup Tool"), _("Please choose a file to restore from"), Gtk.MessageType.WARNING).show()
                return
            if self.restore_dest is None:
                MessageDialog(_("Backup Tool"), _("Please choose a destination directory"), Gtk.MessageType.ERROR).show()
                return
            thread = threading.Thread(group=None, target=self.prepare_restore, name="mintBackup-prepare", args=(), kwargs={})
            thread.start()
        elif sel == 7:
            # start restoring :D
            self.builder.get_object("button_apply").hide()
            self.builder.get_object("button_back").hide()
            book.set_current_page(8)
            self.operating = True
            thread = threading.Thread(group=None, target=self.restore, name="mintBackup-restore", args=(), kwargs={})
            thread.start()
        elif sel == 8:
            # show last page(restore finished status)
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_back").hide()
            book.set_current_page(9)
        elif sel == 10:
            f = self.builder.get_object("filechooserbutton_package_dest").get_filename()
            if f is None:
                MessageDialog(_("Backup Tool"), _("Please choose a destination directory"), Gtk.MessageType.ERROR).show()
                return
            self.package_dest = f
            book.set_current_page(11)
            thr = threading.Thread(group=None, name="mintBackup-packages", target=self.load_packages, args=(), kwargs={})
            thr.start()
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_apply").show()
        elif sel == 11:
            # show progress of packages page
            self.builder.get_object("button_forward").set_sensitive(False)
            self.builder.get_object("button_back").set_sensitive(False)
            book.set_current_page(12)
            self.operating = True
            thr = threading.Thread(group=None, name="mintBackup-packages", target=self.backup_packages, args=(), kwargs={})
            thr.start()
        elif sel == 14:
            thr = threading.Thread(group=None, name="mintBackup-packages", target=self.load_package_list, args=(), kwargs={})
            thr.start()
        elif sel == 15:
            inst = False
            model = self.builder.get_object("treeview_package_list").get_model()
            if len(model) == 0:
                MessageDialog(_("Backup Tool"), _("No packages need to be installed at this time"), Gtk.MessageType.INFO).show()
                return
            for row in model:
                if row[0]:
                    inst = True
                    break
            if not inst:
                MessageDialog(_("Backup Tool"), _("Please select one or more packages to install"), Gtk.MessageType.ERROR).show()
                return
            else:
                thr = threading.Thread(group=None, name="mintBackup-packages", target=self.install_packages, args=(), kwargs={})
                thr.start()

    def back_callback(self, widget):
        """ Back button
        """

        book = self.builder.get_object("notebook1")
        sel = book.get_current_page()
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_forward").show()
        if sel == 7 and len(sys.argv) == 2:
            self.builder.get_object("button_back").set_sensitive(False)
        if (sel == 6) or (sel == 10) or (sel == 14):
            book.set_current_page(0)
            self.builder.get_object("button_back").set_sensitive(False)
            self.builder.get_object("button_back").hide()
            self.builder.get_object("button_forward").hide()
            if self.tar is not None:
                self.tar.close()
                self.tar = None
        else:
            sel = sel - 1
            if sel == 0:
                self.builder.get_object("button_back").hide()
                self.builder.get_object("button_forward").hide()
            book.set_current_page(sel)

    def create_backup_file(self):
        """ Creates a .mintbackup file (for later restoration)
        """

        self.description = "mintBackup"
        desc = self.builder.get_object("entry_desc").get_text()

        if desc != "":
            self.description = desc

        try:
            of = os.path.join(self.backup_dest, ".mintbackup")

            lines = ["source: %s\n" % (self.backup_dest),
                     "destination: %s\n" % (self.backup_source),
                     "file_count: %s\n" % (self.file_count),
                     "description: %s\n" % (self.description)]

            with open(of, "w") as out:
                out.writelines(lines)
        except Exception as detail:
            print(detail)
            return False

        return True

    def backup(self):
        """ Does the actual copying
        """

        label = self.builder.get_object("label_current_file_value")
        os.chdir(self.backup_source)
        pbar = self.builder.get_object("progressbar1")
        Gdk.threads_enter()
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_forward").hide()
        self.builder.get_object("button_back").hide()
        label.set_label(_("Calculating..."))
        pbar.set_text(_("Calculating..."))
        Gdk.threads_leave()
        # get a count of all the files
        total = 0
        for top, dirs, files in os.walk(top=self.backup_source, onerror=None, followlinks=self.follow_links):
            Gdk.threads_enter()
            pbar.pulse()
            Gdk.threads_leave()
            for f in files:
                # Named pipes can cause program to hang. Find and add them to the exclude list.
                file_full_path = top + "/" + f
                excludes = self.builder.get_object("treeview_excludes").get_model()
                if stat.S_ISFIFO(os.stat(file_full_path).st_mode):  # If file is a named pipe
                    if not file_full_path.find(self.backup_source):
                        excludes.append([file_full_path[len(self.backup_source) + 1:], self.fileIcon, file_full_path])
                        self.errors.append([_("Skipping %(skipped_file)s because named pipes are not "
                                              "supported.") % {'skipped_file': file_full_path}, None])
                if not self.operating:
                    break
                if not self.is_excluded(os.path.join(top, f)):
                    total += 1

        sztotal = str(total)
        self.file_count = sztotal
        total = float(total)

        current_file = 0
        self.create_backup_file()

        # deletion policy
        del_policy = self.builder.get_object("combobox_delete_dest").get_active()

        # find out compression format, if any
        sel = self.builder.get_object("combobox_compress").get_active()
        comp = self.builder.get_object("combobox_compress").get_model()[sel]
        if comp[1] is not None:
            tar = None
            filetime = strftime("%Y-%m-%d-%H%M-backup", localtime())
            filename = os.path.join(self.backup_dest, filetime + comp[2] + ".part")
            final_filename = os.path.join(self.backup_dest, filetime + comp[2])
            try:
                tar = tarfile.open(name=filename, dereference=self.follow_links, mode=comp[1], bufsize=1024)
                mintfile = os.path.join(self.backup_dest, ".mintbackup")
                tar.add(mintfile, arcname=".mintbackup", recursive=False, exclude=None)
            except Exception as detail:
                print(detail)
                self.errors.append([str(detail), None])
            for top, dirs, files in os.walk(top=self.backup_source, onerror=None, followlinks=self.follow_links):
                if not self.operating or self.error is not None:
                    break
                for f in files:
                    rpath = os.path.join(top, f)
                    path = os.path.relpath(rpath)
                    if not self.is_excluded(rpath):
                        if os.path.islink(rpath):
                            if self.follow_links:
                                if not os.path.exists(rpath):
                                    self.update_restore_progress(0, 1, message=_("Skipping broken link"))
                                    self.errors.append([rpath, _("Broken link")])
                                    continue
                            else:
                                self.update_restore_progress(0, 1, message=_("Skipping link"))
                                current_file += 1
                                continue
                        Gdk.threads_enter()
                        label.set_label(path)
                        self.builder.get_object("label_file_count").set_text(str(current_file) + " / " + sztotal)
                        Gdk.threads_leave()
                        try:
                            underfile = TarFileMonitor(rpath, self.update_backup_progress)
                            finfo = tar.gettarinfo(name=None, arcname=path, fileobj=underfile)
                            tar.addfile(fileobj=underfile, tarinfo=finfo)
                            underfile.close()
                        except Exception as detail:
                            print(detail)
                            self.errors.append([rpath, str(detail)])
                        current_file = current_file + 1
            try:
                tar.close()
                os.remove(mintfile)
                os.rename(filename, final_filename)
            except Exception as detail:
                print(detail)
                self.errors.append([str(detail), None])
        else:
            # Copy to other directory, possibly on another device
            for top, dirs, files in os.walk(top=self.backup_source, topdown=False, onerror=None, followlinks=self.follow_links):
                if not self.operating:
                    break
                for f in files:
                    rpath = os.path.join(top, f)
                    path = os.path.relpath(rpath)
                    if not self.is_excluded(rpath):
                        target = os.path.join(self.backup_dest, path)
                        if os.path.islink(rpath):
                            if self.follow_links:
                                if not os.path.exists(rpath):
                                    self.update_restore_progress(0, 1, message=_("Skipping broken link"))
                                    current_file += 1
                                    continue
                            else:
                                self.update_restore_progress(0, 1, message=_("Skipping link"))
                                current_file += 1
                                continue
                        dir = os.path.split(target)
                        if not os.path.exists(dir[0]):
                            try:
                                os.makedirs(dir[0])
                            except Exception as detail:
                                print(detail)
                                self.errors.append([dir[0], str(detail)])
                        Gdk.threads_enter()
                        label.set_label(path)
                        self.builder.get_object("label_file_count").set_text(str(current_file) + " / " + sztotal)
                        Gdk.threads_leave()
                        try:
                            if os.path.exists(target):
                                if del_policy == 1:
                                    # source size != dest size
                                    file1 = os.path.getsize(rpath)
                                    file2 = os.path.getsize(target)
                                    if file1 != file2:
                                        os.remove(target)
                                        self.copy_file(rpath, target, sourceChecksum=None)
                                    else:
                                        self.update_backup_progress(0, 1, message=_("Skipping identical file"))
                                elif del_policy == 2:
                                    # source time != dest time
                                    file1 = os.path.getmtime(rpath)
                                    file2 = os.path.getmtime(target)
                                    if file1 != file2:
                                        os.remove(target)
                                        self.copy_file(rpath, target, sourceChecksum=None)
                                    else:
                                        self.update_backup_progress(0, 1, message=_("Skipping identical file"))
                                elif del_policy == 3:
                                    # checksums
                                    file1 = self.get_checksum(rpath)
                                    file2 = self.get_checksum(target)
                                    if file1 not in file2:
                                        os.remove(target)
                                        self.copy_file(rpath, target, sourceChecksum=file1)
                                    else:
                                        self.update_backup_progress(0, 1, message=_("Skipping identical file"))
                                elif del_policy == 4:
                                    # always delete
                                    os.remove(target)
                                    self.copy_file(rpath, target, sourceChecksum=None)
                            else:
                                self.copy_file(rpath, target, sourceChecksum=None)
                            current_file = current_file + 1
                        except Exception as detail:
                            print(detail)
                            self.errors.append([rpath, str(detail)])
                    del f
                    if self.preserve_times or self.preserve_perms:
                        # loop back over the directories now to reset the a/m/time
                        for d in dirs:
                            rpath = os.path.join(top, d)
                            path = os.path.relpath(rpath)
                            target = os.path.join(self.backup_dest, path)
                            self.clone_dir(rpath, target)
                            del d

        if current_file < total:
            self.errors.append([_("Warning: Some files were not saved, copied: %(current_file)d files out of %(total)d total") % {'current_file': current_file, 'total': total}, None])
        if len(self.errors) > 0:
            Gdk.threads_enter()
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.builder.get_object("label_finished_status").set_markup(_("An error occurred during the backup"))
            self.builder.get_object("image_finished").set_from_pixbuf(img)
            self.builder.get_object("treeview_backup_errors").set_model(self.errors)
            self.builder.get_object("win_errors").show_all()
            self.builder.get_object("notebook1").next_page()
            Gdk.threads_leave()
        else:
            if not self.operating:
                Gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.builder.get_object("label_finished_status").set_label(_("The backup was aborted"))
                self.builder.get_object("image_finished").set_from_pixbuf(img)
                self.builder.get_object("notebook1").next_page()
                Gdk.threads_leave()
            else:
                Gdk.threads_enter()
                label.set_label("Done")
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.builder.get_object("label_finished_status").set_label(_("The backup completed successfully"))
                self.builder.get_object("image_finished").set_from_pixbuf(img)
                self.builder.get_object("notebook1").next_page()
                Gdk.threads_leave()
        self.operating = False

    def is_excluded(self, filename):
        """ Returns true if the file/directory is on the exclude list
        """

        for row in self.builder.get_object("treeview_excludes").get_model():
            if filename.startswith(row[2]):
                return True
        return False

    def update_backup_progress(self, current, total, message=None):
        """ Update the backup progress bar
        """

        current = float(current)
        total = float(total)
        fraction = float(current / total)
        Gdk.threads_enter()
        self.builder.get_object("progressbar1").set_fraction(fraction)
        if message is not None:
            self.builder.get_object("progressbar1").set_text(message)
        else:
            self.builder.get_object("progressbar1").set_text(str(int(fraction * 100)) + "%")
        Gdk.threads_leave()

    def copy_file(self, source, dest, restore=None, sourceChecksum=None):
        """ Utility method - copy file, also provides a quick way of aborting a copy, which
        using modules doesn't allow me to do..
        """

        try:
            # represents max buffer size
            BUF_MAX = 16 * 1024  # so we don't get stuck on I/O ops
            errfile = None
            src = open(source, 'rb')
            total = os.path.getsize(source)
            current = 0
            dst = open(dest, 'wb')
            while True:
                if not self.operating:
                    # Abort!
                    errfile = dest
                    break
                read = src.read(BUF_MAX)
                if read:
                    dst.write(read)
                    current += len(read)
                    if restore:
                        self.update_restore_progress(current, total)
                    else:
                        self.update_backup_progress(current, total)
                else:
                    break
            src.close()
            if errfile:
                # Remove aborted file (avoid corruption)
                dst.close()
                os.remove(errfile)
            else:
                fd = dst.fileno()
                if self.preserve_perms:
                    # set permissions
                    finfo = os.stat(source)
                    owner = finfo[stat.ST_UID]
                    group = finfo[stat.ST_GID]
                    os.fchown(fd, owner, group)
                    dst.flush()
                    os.fsync(fd)
                    dst.close()
                if self.preserve_times:
                    finfo = os.stat(source)
                    atime = finfo[stat.ST_ATIME]
                    mtime = finfo[stat.ST_MTIME]
                    os.utime(dest, (atime, mtime))
                else:
                    dst.flush()
                    os.fsync(fd)
                    dst.close()

                if self.postcheck:
                    if sourceChecksum is not None:
                        file1 = sourceChecksum
                    else:
                        file1 = self.get_checksum(source, restore)
                    file2 = self.get_checksum(dest, restore)
                    if file1 not in file2:
                        print(_("Checksum Mismatch:") + " [" + file1 + "] [" + file1 + "]")
                        self.errors.append([source, _("Checksum Mismatch")])
        except OSError as bad:
            if len(bad.args) > 2:
                print("{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]")
                self.errors.append([bad.args[2], bad.args[1]])
            else:
                print("{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]")
                self.errors.append([source, bad.args[1]])

    def clone_dir(self, source, dest):
        """ mkdir and clone permissions
        """

        try:
            if not os.path.exists(dest):
                os.mkdir(dest)
            if self.preserve_perms:
                finfo = os.stat(source)
                owner = finfo[stat.ST_UID]
                group = finfo[stat.ST_GID]
                os.chown(dest, owner, group)
            if self.preserve_times:
                finfo = os.stat(source)
                atime = finfo[stat.ST_ATIME]
                mtime = finfo[stat.ST_MTIME]
                os.utime(dest, (atime, mtime))
        except OSError as bad:
            if len(bad.args) > 2:
                print("{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]")
                self.errors.append([bad.args[2], bad.args[1]])
            else:
                print("{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]")
                self.errors.append([source, bad.args[1]])

    def get_checksum(self, source, restore=None):
        """ Grab the checksum for the input filename and return it
        """
        MAX_BUF = 16 * 1024
        current = 0
        try:
            check = hashlib.sha1()
            input = open(source, "rb")
            total = os.path.getsize(source)
            while True:
                if not self.operating:
                    return None
                read = input.read(MAX_BUF)
                if not read:
                    break
                check.update(read)
                current += len(read)
                if restore:
                    self.update_restore_progress(current, total, message=_("Calculating checksum"))
                else:
                    self.update_backup_progress(current, total, message=_("Calculating checksum"))
            input.close()
            return check.hexdigest()
        except OSError as bad:
            if len(bad.args) > 2:
                print("{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]")
                self.errors.append([bad.args[2], bad.args[1]])
            else:
                print("{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]")
                self.errors.append([source, bad.args[1]])
        return None

    def get_checksum_for_file(self, source):
        """ Grabs checksum for fileobj type object
        """

        MAX_BUF = 16 * 1024
        current = 0
        total = source.size
        try:
            check = hashlib.sha1()
            while True:
                if not self.operating:
                    return None
                read = source.read(MAX_BUF)
                if not read:
                    break
                check.update(read)
                current += len(read)
                self.update_restore_progress(current, total, message=_("Calculating checksum"))
            source.close()
            return check.hexdigest()
        except Exception as detail:
            self.errors.append([source, str(detail)])
            print(detail)
        return None

    def update_restore_progress(self, current, total, message=None):
        """ Update the restore progress bar
        """

        current = float(current)
        total = float(total)
        fraction = float(current / total)
        Gdk.threads_enter()
        self.builder.get_object("progressbar_restore").set_fraction(fraction)
        if message is not None:
            self.builder.get_object("progressbar_restore").set_text(message)
        else:
            self.builder.get_object("progressbar_restore").set_text(str(int(fraction * 100)) + "%")
        Gdk.threads_leave()

    def prepare_restore(self):
        """ Prepare the restore, reads the .mintbackup file if present
        """

        if self.restore_archive:
            # restore archives.
            if self.tar is not None:
                Gdk.threads_enter()
                self.builder.get_object("notebook1").set_current_page(7)
                self.builder.get_object("button_forward").hide()
                self.builder.get_object("button_apply").show()
                Gdk.threads_leave()
                return
            Gdk.threads_enter()
            self.builder.get_object("main_window").set_sensitive(False)
            self.builder.get_object("main_window").get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.WATCH))
            Gdk.threads_leave()
            self.conf = mINIFile()
            try:
                self.tar = tarfile.open(self.restore_source, "r")
                mintfile = self.tar.getmember(".mintbackup")
                if mintfile is None:
                    print("Processing a backup not created with this tool")
                    self.conf.description = _("(Not created with the Backup Tool)")
                    self.conf.file_count = -1
                else:
                    mfile = self.tar.extractfile(mintfile)
                    self.conf.load_from_list(mfile.readlines())
                    mfile.close()

                Gdk.threads_enter()
                self.builder.get_object("label_overview_description_value").set_label(self.conf.description)
                self.builder.get_object("button_back").set_sensitive(True)
                self.builder.get_object("button_forward").hide()
                self.builder.get_object("button_apply").show()
                self.builder.get_object("notebook1").set_current_page(7)
                Gdk.threads_leave()

            except Exception as detail:
                print(detail)
        else:
            # Restore from directory
            self.conf = mINIFile()
            try:
                mfile = os.path.join(self.restore_source, ".mintbackup")
                if not os.path.exists(mfile):
                    print("Processing a backup not created with this tool")
                    self.conf.description = _("(Not created with the Backup Tool)")
                    self.conf.file_count = -1
                else:
                    self.conf.load_from_file(mfile)

                Gdk.threads_enter()
                self.builder.get_object("label_overview_description_value").set_label(self.conf.description)
                self.builder.get_object("button_back").set_sensitive(True)
                self.builder.get_object("button_forward").hide()
                self.builder.get_object("button_apply").show()
                self.builder.get_object("notebook1").set_current_page(7)
                Gdk.threads_leave()

            except Exception as detail:
                print(detail)
        Gdk.threads_enter()
        self.builder.get_object("label_overview_source_value").set_label(self.restore_source)
        self.builder.get_object("label_overview_dest_value").set_label(self.restore_dest)
        self.builder.get_object("main_window").set_sensitive(True)
        self.builder.get_object("main_window").get_window().set_cursor(None)
        Gdk.threads_leave()

    def extract_file(self, source, dest, record):
        """ Extract file from archive
        """

        MAX_BUF = 512
        current = 0
        total = record.size
        errflag = False
        while True:
            if not self.operating:
                errflag = True
                break
            read = source.read(MAX_BUF)
            if not read:
                break
            dest.write(read)
            current += len(read)
            self.update_restore_progress(current, total)
        source.close()
        if errflag:
            dest.close()
            os.remove(target)
        else:
            # set permissions
            fd = dest.fileno()
            os.fchown(fd, record.uid, record.gid)
            os.fchmod(fd, record.mode)
            dest.flush()
            os.fsync(fd)
            dest.close()
            os.utime(dest.name, (record.mtime, record.mtime))

    def restore(self):
        """ Restore from archive
        """

        self.preserve_perms = True
        self.preserve_times = True
        self.postcheck = True
        Gdk.threads_enter()
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_forward").hide()
        self.builder.get_object("button_back").hide()
        Gdk.threads_leave()

        del_policy = self.builder.get_object("combobox_restore_del").get_active()
        Gdk.threads_enter()
        pbar = self.builder.get_object("progressbar_restore")
        pbar.set_text(_("Calculating..."))
        label = self.builder.get_object("label_restore_status_value")
        label.set_label(_("Calculating..."))
        Gdk.threads_leave()

        # restore from archive
        self.error = None
        if self.restore_archive:
            os.chdir(self.restore_dest)
            sztotal = self.conf.file_count
            total = float(sztotal)
            if total == -1:
                tmp = len(self.tar.getmembers())
                szttotal = str(tmp)
                total = float(tmp)
            current_file = 0
            MAX_BUF = 1024
            for record in self.tar.getmembers():
                if not self.operating:
                    break
                if record.name == ".mintbackup":
                    # skip mintbackup file
                    continue
                Gdk.threads_enter()
                label.set_label(record.name)
                Gdk.threads_leave()
                if record.isdir():
                    target = os.path.join(self.restore_dest, record.name)
                    if not os.path.exists(target):
                        try:
                            os.mkdir(target)
                            os.chown(target, record.uid, record.gid)
                            os.chmod(target, record.mode)
                            os.utime(target, (record.mtime, record.mtime))
                        except Exception as detail:
                            print(detail)
                            self.errors.append([target, str(detail)])
                if record.isreg():
                    target = os.path.join(self.restore_dest, record.name)
                    dir = os.path.split(target)
                    if not os.path.exists(dir[0]):
                        try:
                            os.makedirs(dir[0])
                        except Exception as detail:
                            print(detail)
                            self.errors.append([dir[0], str(detail)])
                    Gdk.threads_enter()
                    self.builder.get_object("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
                    Gdk.threads_leave()
                    try:
                        if os.path.exists(target):
                            if del_policy == 1:
                                # source size != dest size
                                file1 = record.size
                                file2 = os.path.getsize(target)
                                if file1 != file2:
                                    os.remove(target)
                                    gz = self.tar.extractfile(record)
                                    out = open(target, "wb")
                                    self.extract_file(gz, out, record)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif del_policy == 2:
                                # source time != dest time
                                file1 = record.mtime
                                file2 = os.path.getmtime(target)
                                if file1 != file2:
                                    os.remove(target)
                                    gz = self.tar.extractfile(record)
                                    out = open(target, "wb")
                                    self.extract_file(gz, out, record)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif del_policy == 3:
                                # checksums
                                gz = self.tar.extractfile(record)
                                file1 = self.get_checksum_for_file(gz)
                                file2 = self.get_checksum(target)
                                if file1 not in file2:
                                    os.remove(target)
                                    out = open(target, "wb")
                                    gz.close()
                                    gz = self.tar.extractfile(record)
                                    self.extract_file(gz, out, record)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif del_policy == 4:
                                # always delete
                                os.remove(target)
                                gz = self.tar.extractfile(record)
                                out = open(target, "wb")
                                self.extract_file(gz, out, record)
                        else:
                            gz = self.tar.extractfile(record)
                            out = open(target, "wb")
                            self.extract_file(gz, out, record)
                        current_file = current_file + 1
                    except Exception as detail:
                        print(detail)
                        self.errors.append([record.name, str(detail)])
            try:
                self.tar.close()
            except:
                pass
        else:
            # restore backup from dir.
            os.chdir(self.restore_source)
            sztotal = self.conf.file_count
            total = float(sztotal)
            current_file = 0
            if total == -1:
                for top, dirs, files in os.walk(top=self.restore_source, onerror=None, followlinks=self.follow_links):
                    pbar.pulse()
                    for f in files:
                        if not self.operating:
                            break
                        total += 1
                sztotal = str(total)
                total = float(total)
            for top, dirs, files in os.walk(top=self.restore_source, topdown=False, onerror=None, followlinks=self.follow_links):
                if not self.operating:
                    break
                for f in files:
                    if ".mintbackup" in f:
                        continue
                    rpath = os.path.join(top, f)
                    path = os.path.relpath(rpath)
                    target = os.path.join(self.restore_dest, path)
                    dir = os.path.split(target)
                    if not os.path.exists(dir[0]):
                        try:
                            os.makedirs(dir[0])
                        except Exception as detail:
                            print(detail)
                            self.errors.append([dir[0], str(detail)])
                    Gdk.threads_enter()
                    label.set_label(path)
                    Gdk.threads_leave()
                    self.builder.get_object("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
                    try:
                        if os.path.exists(target):
                            if del_policy == 1:
                                # source size != dest size
                                file1 = os.path.getsize(rpath)
                                file2 = os.path.getsize(target)
                                if file1 != file2:
                                    os.remove(target)
                                    self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif del_policy == 2:
                                # source time != dest time
                                file1 = os.path.getmtime(rpath)
                                file2 = os.path.getmtime(target)
                                if file1 != file2:
                                    os.remove(target)
                                    self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif del_policy == 3:
                                # checksums (check size first)
                                if os.path.getsize(rpath) == os.path.getsize(target):
                                    file1 = self.get_checksum(rpath)
                                    file2 = self.get_checksum(target)
                                    if file1 not in file2:
                                        os.remove(target)
                                        self.copy_file(rpath, target, restore=True, sourceChecksum=file1)
                                    else:
                                        self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                                else:
                                    os.remove(target)
                                    self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                            elif del_policy == 4:
                                # always delete
                                os.remove(target)
                                self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                        else:
                            self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                        current_file += 1
                    except Exception as detail:
                        print(detail)
                        self.errors.append([rpath, str(detail)])
                    del f
                    if self.preserve_times or self.preserve_perms:
                        # loop back over the directories now to reset the a/m/time
                        for d in dirs:
                            rpath = os.path.join(top, d)
                            path = os.path.relpath(rpath)
                            target = os.path.join(self.restore_dest, path)
                            self.clone_dir(rpath, target)
                            del d
        if current_file < total:
            self.error = _("Warning: Some files were not restored, copied: %(current_file)d files out of %(total)d total") % {'current_file': current_file, 'total': total}
        if len(self.errors) > 0:
            Gdk.threads_enter()
            self.builder.get_object("label_restore_finished_value").set_label(_("An error occurred during the restoration"))
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.builder.get_object("image_restore_finished").set_from_pixbuf(img)
            self.builder.get_object("treeview_restore_errors").set_model(self.errors)
            self.builder.get_object("win_restore_errors").show_all()
            self.builder.get_object("notebook1").next_page()
            Gdk.threads_leave()
        else:
            if not self.operating:
                Gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.builder.get_object("label_restore_finished_value").set_label(_("The restoration was aborted"))
                self.builder.get_object("image_restore_finished").set_from_pixbuf(img)
                self.builder.get_object("notebook1").next_page()
                Gdk.threads_leave()
            else:
                Gdk.threads_enter()
                label.set_label("Done")
                pbar.set_text("Done")
                self.builder.get_object("label_restore_finished_value").set_label(_("The restoration completed successfully"))
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.builder.get_object("image_restore_finished").set_from_pixbuf(img)
                self.builder.get_object("notebook1").next_page()
                Gdk.threads_leave()
        self.operating = False

    def load_packages(self):
        """ Load the package list
        """

        Gdk.threads_enter()
        model = Gtk.ListStore(bool, str, str)
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.builder.get_object("main_window").set_sensitive(False)
        self.builder.get_object("main_window").get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.WATCH))
        Gdk.threads_leave()
        try:
            p = subprocess.Popen("aptitude search ~M", shell=True, stdout=subprocess.PIPE)
            self.blacklist = list()
            for l in p.stdout:
                l = l.decode('utf-8')
                l = l.rstrip("\r\n")
                l = l.split(" ")
                self.blacklist.append(l[2])
            bl = open("/usr/share/linuxmint/mintbackup/software-selections.list", "r")
            for l in bl.readlines():
                if l.startswith("#"):
                    # ignore comments
                    continue
                l = l.rstrip("\r\n")
                self.blacklist.append(l)
            bl.close()
        except Exception as detail:
            print(detail)
        cache = apt.Cache()
        for pkg in cache:
            if pkg.installed:
                if self.is_manual_installed(pkg.name):
                    desc = "<big>" + pkg.name + "</big>\n<small>" + pkg.installed.summary.replace("&", "&amp;") + "</small>"
                    Gdk.threads_enter()
                    model.append([True, pkg.name, desc])
                    Gdk.threads_leave()
        Gdk.threads_enter()
        self.builder.get_object("treeview_packages").set_model(model)
        self.builder.get_object("main_window").set_sensitive(True)
        self.builder.get_object("main_window").get_window().set_cursor(None)
        Gdk.threads_leave()

    def is_manual_installed(self, pkgname):
        """ Is the package manually installed?
        """

        for b in self.blacklist:
            if pkgname == b:
                return False
        return True

    def toggled_cb(self, ren, path, treeview):
        """ Toggled (update model)
        """

        model = treeview.get_model()
        iter = model.get_iter(path)
        if iter != None:
            checked = model.get_value(iter, 0)
            model.set_value(iter, 0, (not checked))

    def celldatamethod_checkbox(self, column, cell, model, iter, user_data):
        """ For the packages treeview
        """

        checked = model.get_value(iter, 0)
        cell.set_property("active", checked)

    def show_package_choose(self, w):
        """ Show filechooser for package backup
        """

        dialog = Gtk.FileChooserDialog(_("Backup Tool"), None, Gtk.FileChooserAction.SAVE, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
        dialog.set_current_folder(HOME)
        dialog.set_select_multiple(False)
        if dialog.run() == Gtk.ResponseType.OK:
            self.package_dest = dialog.get_filename()
            self.builder.get_object("entry_package_dest").set_text(self.package_dest)
        dialog.destroy()

    def backup_packages(self):
        """ "backup" the package selection
        """

        pbar = self.builder.get_object("progressbar_packages")
        lab = self.builder.get_object("label_current_package_value")
        Gdk.threads_enter()
        pbar.set_text(_("Calculating..."))
        lab.set_label(_("Calculating..."))
        Gdk.threads_leave()
        model = self.builder.get_object("treeview_packages").get_model()
        total = 0
        count = 0
        for row in model:
            if not self.operating or self.error is not None:
                break

            if not row[0]:
                continue
            total += 1
        pbar.set_text("%d / %d" % (count, total))
        try:
            filetime = strftime("%Y-%m-%d-%H%M-package.list", localtime())
            filename = "software_selection_%s@%s" % (subprocess.getoutput("hostname"), filetime)
            out = open(os.path.join(self.package_dest, filename), "w")
            for row in model:
                if not self.operating or self.error is not None:
                    break
                if row[0]:
                    count += 1
                    out.write("%s\t%s\n" % (row[1], "install"))
                    Gdk.threads_enter()
                    pbar.set_text("%d / %d" % (count, total))
                    pbar.set_fraction(float(count / total))
                    lab.set_label(row[1])
                    Gdk.threads_leave()
            out.close()
            subprocess.call(["chmod", "a+rx", self.package_dest])
            subprocess.call(["chmod", "a+rw", os.path.join(self.package_dest, filename)])
        except Exception as detail:
            self.error = str(detail)

        if self.error is not None:
            Gdk.threads_enter()
            self.builder.get_object("label_packages_done_value").set_label(_("An error occurred during the backup:") + "\n" + self.error)
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.builder.get_object("image_packages_done").set_from_pixbuf(img)
            self.builder.get_object("notebook1").next_page()
            Gdk.threads_leave()
        else:
            if not self.operating:
                Gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.builder.get_object("label_packages_done_value").set_label(_("The backup was aborted"))
                self.builder.get_object("image_packages_done").set_from_pixbuf(img)
                self.builder.get_object("notebook1").next_page()
                Gdk.threads_leave()
            else:
                Gdk.threads_enter()
                lab.set_label("Done")
                pbar.set_text("Done")
                self.builder.get_object("label_packages_done_value").set_label(_("Your software selection was backed up successfully"))
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.builder.get_object("image_packages_done").set_from_pixbuf(img)
                self.builder.get_object("notebook1").next_page()
                Gdk.threads_leave()
        Gdk.threads_enter()
        self.builder.get_object("button_apply").hide()
        self.builder.get_object("button_back").hide()
        Gdk.threads_leave()
        self.operating = False

    def load_package_list_cb(self, w):
        """ Check validity of file
        """

        self.package_source = w.get_filename()
        # magic info, i.e. we ignore files that don't have this.
        try:
            source = open(self.package_source, "r")
            re = source.readlines()
            error = False
            for line in re:
                line = line.rstrip("\r\n")
                if line != "":
                    if not line.endswith("\tinstall"):
                        error = True
                        break
            source.close()
            if error:
                MessageDialog(_("Backup Tool"), _("The specified file is not a valid software selection"), Gtk.MessageType.ERROR).show()
                #self.builder.get_object("scroller_packages").hide()
                self.builder.get_object("button_forward").set_sensitive(False)
                return
            else:
                self.builder.get_object("button_forward").set_sensitive(True)
        except Exception as detail:
            print(detail)
            MessageDialog(_("Backup Tool"), _("An error occurred while accessing the file"), Gtk.MessageType.ERROR).show()

    def refresh(self, w):
        """ Refresh package list
        """

        thr = threading.Thread(group=None, name="mintBackup-packages", target=self.load_package_list, args=(), kwargs={})
        thr.start()

    def load_package_list(self):
        """ Load package list into treeview
        """

        Gdk.threads_enter()
        self.builder.get_object("button_forward").hide()
        self.builder.get_object("button_apply").show()
        self.builder.get_object("button_apply").set_sensitive(True)
        self.builder.get_object("main_window").set_sensitive(False)
        self.builder.get_object("main_window").get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.WATCH))
        model = Gtk.ListStore(bool, str, bool, str)
        self.builder.get_object("treeview_package_list").set_model(model)
        Gdk.threads_leave()
        try:
            source = open(self.package_source, "r")
            cache = apt.Cache()
            for line in source.readlines():
                if line.startswith("#"):
                    # ignore comments
                    continue
                line = line.rstrip("\r\n")
                if line == "":
                    # ignore empty lines
                    continue
                line = line.split("\t")[0]
                inst = True
                if line in cache:
                    pkg = cache[line]
                    if not pkg.is_installed:
                        if pkg.candidate is not None:
                            desc = pkg.candidate.summary.replace("&", "&amp;")
                            line = "<big>" + line + "</big>\n<small>" + desc + "</small>"
                        else:
                            inst = False
                            line = "<big>" + line + "</big>\n<small>" + _("Could not locate the package") + "</small>"
                        Gdk.threads_enter()
                        model.append([inst, line, inst, pkg.name])
                        Gdk.threads_leave()
                else:
                    inst = False
                    line = "<big>" + line + "</big>\n<small>" + _("Could not locate the package") + "</small>"
                    Gdk.threads_enter()
                    model.append([inst, line, inst, line])
                    Gdk.threads_leave()
            source.close()
        except Exception as detail:
            print(detail)
            MessageDialog(_("Backup Tool"), _("An error occurred while accessing the file"), Gtk.MessageType.ERROR).show()
        Gdk.threads_enter()
        self.builder.get_object("main_window").set_sensitive(True)
        self.builder.get_object("main_window").get_window().set_cursor(None)
        if len(model) == 0:
            self.builder.get_object("button_forward").hide()
            self.builder.get_object("button_back").hide()
            self.builder.get_object("button_apply").hide()
            self.builder.get_object("notebook1").set_current_page(16)
        else:
            self.builder.get_object("notebook1").set_current_page(15)
            self.builder.get_object("button_forward").set_sensitive(True)
        Gdk.threads_leave()

    def install_packages(self):
        """ Installs the package selection
        """
        # launch synaptic..
        Gdk.threads_enter()
        self.builder.get_object("main_window").get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.WATCH))
        self.builder.get_object("main_window").set_sensitive(False)
        Gdk.threads_leave()

        cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window", "--non-interactive", "--parent-window-id", str(self.builder.get_object("main_window").get_window().get_xid())]
        cmd.append("--progress-str")
        cmd.append("\"" + _("Please wait, this can take some time") + "\"")
        cmd.append("--finish-str")
        cmd.append("\"" + _("The installation is complete") + "\"")
        f = tempfile.NamedTemporaryFile()
        model = self.builder.get_object("treeview_package_list").get_model()
        for row in model:
            if row[0]:
                line = ("%s\tinstall\n" % row[3]).encode("UTF-8")
                f.write(line)
        cmd.append("--set-selections-file")
        cmd.append("%s" % f.name)
        f.flush()
        comnd = subprocess.Popen(' '.join(cmd), shell=True)
        returnCode = comnd.wait()
        f.close()

        Gdk.threads_enter()
        self.builder.get_object("main_window").get_window().set_cursor(None)
        self.builder.get_object("main_window").set_sensitive(True)
        self.builder.get_object("button_back").set_sensitive(True)
        self.builder.get_object("button_forward").set_sensitive(True)
        Gdk.threads_leave()

        self.refresh(None)

    def set_selection(self, w, treeview, selection, check):
        """ Select / deselect all
        """

        model = treeview.get_model()
        for row in model:
            if check:
                if row[2]:
                    row[0] = selection
            else:
                row[0] = selection

if __name__ == "__main__":
    Gdk.threads_init()
    MintBackup()
    Gdk.threads_enter()
    Gtk.main()
    Gdk.threads_leave()
