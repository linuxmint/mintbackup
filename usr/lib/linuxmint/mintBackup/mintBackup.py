#!/usr/bin/env python

try:
	import pygtk
	pygtk.require("2.0")
except Exception, detail:
	print "You do not have a recent version of GTK"

try:
	import os
	import sys
	import commands
	import gtk
	import gtk.glade
	import gettext
	import threading
	import tarfile
	import stat
	import shutil
	import hashlib
	from time import strftime, localtime, sleep
	import apt
	import subprocess
	from user import home
	import tempfile
except Exception, detail:
	print "You do not have the required dependencies"

# i18n
gettext.install("mintbackup", "/usr/share/linuxmint/locale")

# i18n for menu item
menuName = _("Backup Tool")
menuComment = _("Make a backup of your home directory")

class TarFileMonitor():
	''' Bit of a hack but I can figure out what tarfile is doing now.. (progress wise) '''
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
		if(size is not None):
			bytes = self.f.read(size)
			if(bytes):
				self.counter += len(bytes)
				self.callback(self.counter, self.size)
		else:
			bytes = self.f.read()
			if(bytes is not None):
				self.counter += len(bytes)
				self.callback(self.counter, self.size)
		return bytes
	def close(self):
		self.f.close()

''' Funkai little class for abuse-safety. all atrr's are set from file '''
class mINIFile():
	def load_from_string(self, line):
		if(line.find(":")):
			l = line.split(":")
			if(len(l) >= 2):
				tmp = ":".join(l[1:]).rstrip("\r\n")
				setattr(self, l[0], tmp)
		elif(line.find("=")):
			l = line.split("=")
			if(len(l) >= 2):
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
''' Handy. Makes message dialogs easy :D '''
class MessageDialog(apt.FetchProgress):

	def __init__(self, title, message, style):
		self.title = title
		self.message = message
		self.style = style

	''' Show me on screen '''
	def show(self):
		
		dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, self.style, gtk.BUTTONS_OK, self.message)
		dialog.set_title(_("Backup Tool"))
		dialog.set_position(gtk.WIN_POS_CENTER)
	        dialog.run()
	        dialog.destroy()

''' The main class of the app '''
class MintBackup:

	''' New MintBackup '''
	def __init__(self):
		self.glade = '/usr/lib/linuxmint/mintBackup/mintBackup.glade'
		self.wTree = gtk.glade.XML(self.glade, 'main_window')
		self.wTree.get_widget("main_window").set_icon_from_file("/usr/lib/linuxmint/mintBackup/icon.png")

		# handle command line filenames
		if(len(sys.argv) > 1):
			if(len(sys.argv) == 2):
				filebackup = sys.argv[1]
				self.wTree.get_widget("filechooserbutton_restore_source").set_filename(filebackup)
				self.wTree.get_widget("notebook1").set_current_page(6)
			else:
				print "usage: " + sys.argv[0] + " filename.backup"
				sys.exit(1)
		else:
			self.wTree.get_widget("notebook1").set_current_page(0)

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
		self.backup_source = self.wTree.get_widget("filechooserbutton_backup_source").get_filename()
		self.backup_dest = self.wTree.get_widget("filechooserbutton_backup_source").get_filename()

		# by default we restore archives, not directories (unless user chooses otherwise)
		self.restore_archive = True
		
		# page 0
		self.wTree.get_widget("button_backup_files").connect("clicked", self.wizard_buttons_cb, 1)
		self.wTree.get_widget("button_restore_files").connect("clicked", self.wizard_buttons_cb, 6)
		self.wTree.get_widget("button_backup_packages").connect("clicked", self.wizard_buttons_cb, 10)
		self.wTree.get_widget("button_restore_packages").connect("clicked", self.wizard_buttons_cb, 14)
		
		# set up backup page 1 (source/dest/options)
		# Displayname, [tarfile mode, file extension]
		comps = gtk.ListStore(str,str,str)
		comps.append([_("Preserve structure"), None, None])
		# file extensions mintBackup specific
		comps.append([_(".tar file"), "w", ".tar"])
		comps.append([_(".tar.bz2 file"), "w:bz2", ".tar.bz2"])
		comps.append([_(".tar.gz file"), "w:gz", ".tar.gz"])
		self.wTree.get_widget("combobox_compress").set_model(comps)
		self.wTree.get_widget("combobox_compress").set_active(0)

		# backup overwrite options
		overs = gtk.ListStore(str)
		overs.append([_("Never")])
		overs.append([_("Size mismatch")])
		overs.append([_("Modification time mismatch")])
		overs.append([_("Checksum mismatch")])
		overs.append([_("Always")])
		self.wTree.get_widget("combobox_delete_dest").set_model(overs)
		self.wTree.get_widget("combobox_delete_dest").set_active(3)

		# advanced options
		self.wTree.get_widget("checkbutton_integrity").set_active(self.postcheck)
		self.wTree.get_widget("checkbutton_integrity").connect("clicked", self.handle_checkbox)
		self.wTree.get_widget("checkbutton_perms").set_active(self.preserve_perms)
		self.wTree.get_widget("checkbutton_perms").connect("clicked", self.handle_checkbox)
		self.wTree.get_widget("checkbutton_times").set_active(self.preserve_times)
		self.wTree.get_widget("checkbutton_times").connect("clicked", self.handle_checkbox)
		self.wTree.get_widget("checkbutton_links").set_active(self.follow_links)
		self.wTree.get_widget("checkbutton_links").connect("clicked", self.handle_checkbox)
		# set up exclusions page
		self.iconTheme = gtk.icon_theme_get_default()
		self.dirIcon = self.iconTheme.load_icon("folder", 16, 0)
		self.fileIcon = self.iconTheme.load_icon("document-new", 16, 0)
		ren = gtk.CellRendererPixbuf()
		column = gtk.TreeViewColumn("", ren)
		column.add_attribute(ren, "pixbuf", 1)
		self.wTree.get_widget("treeview_excludes").append_column(column)
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_("Excluded paths"), ren)
		column.add_attribute(ren, "text", 0)
		self.wTree.get_widget("treeview_excludes").append_column(column)
		self.wTree.get_widget("treeview_excludes").set_model(gtk.ListStore(str, gtk.gdk.Pixbuf, str))
		self.wTree.get_widget("button_add_file").connect("clicked", self.add_file_exclude)
		self.wTree.get_widget("button_add_folder").connect("clicked", self.add_folder_exclude)
		self.wTree.get_widget("button_remove_exclude").connect("clicked", self.remove_exclude)

		# set up overview page
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_("Type"), ren)
		column.add_attribute(ren, "markup", 0)
		self.wTree.get_widget("treeview_overview").append_column(column)
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_("Detail"), ren)
		column.add_attribute(ren, "text", 1)
		self.wTree.get_widget("treeview_overview").append_column(column)
		
		# Errors treeview for backup
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_("Path"), ren)
		column.add_attribute(ren, "text", 0)
		self.wTree.get_widget("treeview_backup_errors").append_column(column)
		column = gtk.TreeViewColumn(_("Error"), ren)
		column.add_attribute(ren, "text", 1)
		self.wTree.get_widget("treeview_backup_errors").append_column(column)
		
		# Errors treeview for restore. yeh.
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_("Path"), ren)
		column.add_attribute(ren, "text", 0)
		self.wTree.get_widget("treeview_restore_errors").append_column(column)
		column = gtk.TreeViewColumn(_("Error"), ren)
		column.add_attribute(ren, "text", 1)
		self.wTree.get_widget("treeview_restore_errors").append_column(column)
		# model.
		self.errors = gtk.ListStore(str,str)

		# nav buttons
		self.wTree.get_widget("button_back").connect("clicked", self.back_callback)
		self.wTree.get_widget("button_forward").connect("clicked", self.forward_callback)
		self.wTree.get_widget("button_apply").connect("clicked", self.forward_callback)
		self.wTree.get_widget("button_cancel").connect("clicked", self.cancel_callback)
		self.wTree.get_widget("button_about").connect("clicked", self.about_callback)

		self.wTree.get_widget("button_back").hide()
		self.wTree.get_widget("button_forward").hide()
		self.wTree.get_widget("main_window").connect("destroy", self.cancel_callback)
		self.wTree.get_widget("main_window").set_title(_("Backup Tool"))
		self.wTree.get_widget("main_window").show()

		# open archive button, opens an archive... :P
		self.wTree.get_widget("radiobutton_archive").connect("toggled", self.archive_switch)
		self.wTree.get_widget("radiobutton_dir").connect("toggled", self.archive_switch)
		self.wTree.get_widget("filechooserbutton_restore_source").connect("file-set", self.check_reset_file)

		self.wTree.get_widget("filechooserbutton_backup_source").connect("current-folder-changed", self.save_backup_source)
		self.wTree.get_widget("filechooserbutton_backup_dest").connect("current-folder-changed", self.save_backup_dest)

		self.wTree.get_widget("combobox_restore_del").set_model(overs)
		self.wTree.get_widget("combobox_restore_del").set_active(3)
		
		# packages list
		t = self.wTree.get_widget("treeview_packages")
		self.wTree.get_widget("button_select").connect("clicked", self.set_selection, t, True, False)
		self.wTree.get_widget("button_deselect").connect("clicked", self.set_selection, t, False, False)
		tog = gtk.CellRendererToggle()
		tog.connect("toggled", self.toggled_cb, t)
		c1 = gtk.TreeViewColumn(_("Store?"), tog, active=0)
		c1.set_cell_data_func(tog, self.celldatafunction_checkbox)
		t.append_column(c1)
		c2 = gtk.TreeViewColumn(_("Name"), gtk.CellRendererText(), markup=2)
		t.append_column(c2)
		
		# choose a package list
		t = self.wTree.get_widget("treeview_package_list")
		self.wTree.get_widget("button_select_list").connect("clicked", self.set_selection, t, True, True)
		self.wTree.get_widget("button_deselect_list").connect("clicked", self.set_selection, t, False, True)
		self.wTree.get_widget("button_refresh").connect("clicked", self.refresh)
		tog = gtk.CellRendererToggle()
		tog.connect("toggled", self.toggled_cb, t)
		c1 = gtk.TreeViewColumn(_("Install"), tog, active=0, activatable=2)
		c1.set_cell_data_func(tog, self.celldatafunction_checkbox)
		t.append_column(c1)
		c2 = gtk.TreeViewColumn(_("Name"), gtk.CellRendererText(), markup=1)
		t.append_column(c2)
		self.wTree.get_widget("filechooserbutton_package_source").connect("file-set", self.load_package_list_cb)
		
		# i18n - Page 0 (choose backup or restore)
		self.wTree.get_widget("label_wizard1").set_markup("<big><b>" + _("Backup or Restore") + "</b></big>")
		self.wTree.get_widget("label_wizard2").set_markup("<i><span foreground=\"#555555\">" + _("Choose from the following options") + "</span></i>")

		self.wTree.get_widget("label_create_backup").set_text(_("Backup files"))
		self.wTree.get_widget("label_restore_backup").set_text(_("Restore files"))
		self.wTree.get_widget("label_create_packages").set_text(_("Backup software selection"))
		self.wTree.get_widget("label_restore_packages").set_text(_("Restore software selection"))

		self.wTree.get_widget("label_detail1").set_markup("<small>" + _("Make a backup of your files") + "</small>")
		self.wTree.get_widget("label_detail2").set_markup("<small>" + _("Save the list of installed applications") + "</small>")
		self.wTree.get_widget("label_detail3").set_markup("<small>" + _("Restore a previous backup") + "</small>")
		self.wTree.get_widget("label_detail4").set_markup("<small>" + _("Restore previously installed applications") + "</small>")

		self.wTree.get_widget("image_backup_data").set_from_file("/usr/lib/linuxmint/mintBackup/backup-data.svg")
		self.wTree.get_widget("image_restore_data").set_from_file("/usr/lib/linuxmint/mintBackup/restore-data.svg")
		self.wTree.get_widget("image_backup_software").set_from_file("/usr/lib/linuxmint/mintBackup/backup-software.svg")
		self.wTree.get_widget("image_restore_software").set_from_file("/usr/lib/linuxmint/mintBackup/restore-software.svg")

		# i18n - Page 1 (choose backup directories)
		self.wTree.get_widget("label_title_destination").set_markup("<big><b>" + _("Backup files") + "</b></big>")
		self.wTree.get_widget("label_caption_destination").set_markup("<i><span foreground=\"#555555\">" + _("Please select a source and a destination for your backup") + "</span></i>")
		self.wTree.get_widget("label_backup_source").set_label(_("Source:"))
		self.wTree.get_widget("label_backup_dest").set_label(_("Destination:"))
		self.wTree.get_widget("label_expander").set_label(_("Advanced options"))
		self.wTree.get_widget("label_backup_desc").set_label(_("Description:"))
		self.wTree.get_widget("label_compress").set_label(_("Output:"))
		self.wTree.get_widget("label_overwrite_dest").set_label(_("Overwrite:"))
		self.wTree.get_widget("checkbutton_integrity").set_label(_("Confirm integrity"))
		self.wTree.get_widget("checkbutton_links").set_label(_("Follow symlinks"))
		self.wTree.get_widget("checkbutton_perms").set_label(_("Preserve permissions"))
		self.wTree.get_widget("checkbutton_times").set_label(_("Preserve timestamps"))

		# i18n - Page 2 (choose files/directories to exclude)
		self.wTree.get_widget("label_title_exclude").set_markup("<big><b>" + _("Backup files") + "</b></big>")
		self.wTree.get_widget("label_caption_exclude").set_markup("<i><span foreground=\"#555555\">" + _("Please select any files or directories you want to exclude") + "</span></i>")
		self.wTree.get_widget("label_add_file").set_label(_("Exclude files"))
		self.wTree.get_widget("label_add_folder").set_label(_("Exclude directories"))
		self.wTree.get_widget("label_remove").set_label(_("Remove"))

		# i18n - Page 3 (backup overview)
		self.wTree.get_widget("label_title_review").set_markup("<big><b>" + _("Backup files") + "</b></big>")
		self.wTree.get_widget("label_caption_review").set_markup("<i><span foreground=\"#555555\">" + _("Please review the information below before starting the backup") + "</span></i>")

		# i18n - Page 4 (backing up status)
		self.wTree.get_widget("label_title_copying").set_markup("<big><b>" + _("Backup files") + "</b></big>")
		self.wTree.get_widget("label_caption_copying").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your files are being backed up") + "</span></i>")
		self.wTree.get_widget("label_current_file").set_label(_("Backing up:"))

		# i18n - Page 5 (backup complete)
		self.wTree.get_widget("label_title_finished").set_markup("<big><b>" + _("Backup files") + "</b></big>")
		self.wTree.get_widget("label_caption_finished").set_markup("<i><span foreground=\"#555555\">" + _("The backup is now finished") + "</span></i>")		

		# i18n - Page 6 (Restore locations)
		self.wTree.get_widget("label_title_restore1").set_markup("<big><b>" + _("Restore files") + "</b></big>")
		self.wTree.get_widget("label_caption_restore1").set_markup("<i><span foreground=\"#555555\">" + _("Please choose the type of backup to restore, its location and a destination") + "</span></i>")
		self.wTree.get_widget("radiobutton_archive").set_label(_("Archive"))
		self.wTree.get_widget("radiobutton_dir").set_label(_("Directory"))
		self.wTree.get_widget("label_restore_source").set_label(_("Source:"))
		self.wTree.get_widget("label_restore_dest").set_label(_("Destination:"))
		self.wTree.get_widget("label_restore_advanced").set_label(_("Advanced options"))
		self.wTree.get_widget("label_restore_overwrite").set_label(_("Overwrite:"))

		# i18n - Page 7 (Restore overview)
		self.wTree.get_widget("label_title_restore2").set_markup("<big><b>" + _("Restore files") + "</b></big>")
		self.wTree.get_widget("label_caption_restore2").set_markup("<i><span foreground=\"#555555\">" + _("Please review the information below") + "</span></i>")
		self.wTree.get_widget("label_overview_source").set_markup("<b>" + _("Source:") + "</b>")
		self.wTree.get_widget("label_overview_description").set_markup("<b>" + _("Description:") + "</b>")

		# i18n - Page 8 (restore status)
		self.wTree.get_widget("label_title_restore3").set_markup("<big><b>" + _("Restore files") + "</b></big>")
		self.wTree.get_widget("label_caption_restore3").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your files are being restored") + "</span></i>")
		self.wTree.get_widget("label_restore_status").set_label(_("Restoring:"))

		# i18n - Page 9 (restore complete)
		self.wTree.get_widget("label_title_restore4").set_markup("<big><b>" + _("Restore files") + "</b></big>")
		self.wTree.get_widget("label_caption_restore4").set_markup("<i><span foreground=\"#555555\">" + _("The restoration of the files is now finished") + "</span></i>")

		# i18n - Page 10 (packages)
		self.wTree.get_widget("label_title_software_backup1").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
		self.wTree.get_widget("label_caption_software_backup1").set_markup("<i><span foreground=\"#555555\">" + _("Please choose a destination") + "</span></i>")
		self.wTree.get_widget("label_package_dest").set_label(_("Destination"))
		
		# i18n - Page 11 (package list)
		self.wTree.get_widget("label_title_software_backup2").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
		self.wTree.get_widget("label_caption_software_backup2").set_markup("<i><span foreground=\"#555555\">" + _("The list below shows the packages you added to Linux Mint") + "</span></i>")
		self.wTree.get_widget("label_select").set_label(_("Select all"))
		self.wTree.get_widget("label_deselect").set_label(_("Deselect all"))
		
		# i18n - Page 12 (backing up packages)
		self.wTree.get_widget("label_title_software_backup3").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
		self.wTree.get_widget("label_caption_software_backup3").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your software selection is being backed up") + "</span></i>")
		self.wTree.get_widget("label_current_package").set_label(_("Backing up:"))
		
		# i18n - Page 13 (packages done)
		self.wTree.get_widget("label_title_software_backup4").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
		self.wTree.get_widget("label_caption_software_backup4").set_markup("<i><span foreground=\"#555555\">" + _("The backup is now finished") + "</span></i>")

		# i18n - Page 14 (package restore)
		self.wTree.get_widget("label_title_software_restore1").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
		self.wTree.get_widget("label_caption_software_restore1").set_markup("<i><span foreground=\"#555555\">" + _("Please select a saved software selection") + "</span></i>")
		self.wTree.get_widget("label_package_source").set_markup(_("Software selection:"))

		# i18n - Page 15 (packages list)
		self.wTree.get_widget("label_title_software_restore2").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
		self.wTree.get_widget("label_caption_software_restore2").set_markup("<i><span foreground=\"#555555\">" + _("Select the packages you want to install") + "</span></i>")
		self.wTree.get_widget("label_select_list").set_label(_("Select all"))
		self.wTree.get_widget("label_deselect_list").set_label(_("Deselect all"))
		self.wTree.get_widget("label_refresh").set_label(_("Refresh"))
		
		# i18n - Page 16 (packages install done)
		self.wTree.get_widget("label_title_software_restore3").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
		self.wTree.get_widget("label_caption_software_restore3").set_markup("<i><span foreground=\"#555555\">" + _("The restoration is now finished") + "</span></i>")
		self.wTree.get_widget("label_install_done_value").set_markup(_("Your package selection was restored succesfully"))
		
	''' show the pretty aboutbox. '''
	def about_callback(self, w):
		dlg = gtk.AboutDialog()
		dlg.set_title(_("About"))
		dlg.set_program_name("mintBackup")	
		dlg.set_comments(_("Backup Tool"))
		try:
			h = open('/usr/share/common-licenses/GPL','r')
			s = h.readlines()
			gpl = ""
			for line in s:
				gpl += line
			h.close()
			dlg.set_license(gpl)
		except Exception, detail:
			print detail
		try: 
			version = commands.getoutput("/usr/lib/linuxmint/common/version.py mintbackup")
			dlg.set_version(version)
		except Exception, detail:
			print detail

		dlg.set_authors(["Ikey Doherty <contactjfreak@googlemail.com>", "Clement Lefebvre <root@linuxmint.com>"]) 
		dlg.set_icon_from_file("/usr/lib/linuxmint/mintBackup/icon.png")
		dlg.set_logo(gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintBackup/icon.svg"))
		def close(w, res):
		    if res == gtk.RESPONSE_CANCEL:
		        w.hide()
		dlg.connect("response", close)
		dlg.show()


	def abt_resp(self, w, r):
		if r == gtk.RESPONSE_CANCEL:
			w.hide()

	def save_backup_source(self, w):
		self.backup_source = w.get_filename()		

	def save_backup_dest(self, w):
		self.backup_dest = w.get_filename()
		
	''' handle the file-set signal '''
	def check_reset_file(self, w):
		fileset = w.get_filename()
		if(fileset not in self.backup_source):
			if(self.tar is not None):
				self.tar.close()
				self.tar = None
		self.backup_source = fileset

	''' switch between archive and directory sources '''
	def archive_switch(self, w):
		if(self.wTree.get_widget("radiobutton_archive").get_active()):
			# dealing with archives
			self.restore_archive = True
			self.wTree.get_widget("filechooserbutton_restore_source").set_action(gtk.FILE_CHOOSER_ACTION_OPEN)
		else:
			self.restore_archive = False
			self.wTree.get_widget("filechooserbutton_restore_source").set_action(gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER)

	''' handler for checkboxes '''
	def handle_checkbox(self, widget):
		if(widget == self.wTree.get_widget("checkbutton_integrity")):
			self.postcheck = widget.get_active()
		elif(widget == self.wTree.get_widget("checkbutton_perms")):
			self.preserve_perms = widget.get_active()
		elif(widget == self.wTree.get_widget("checkbutton_times")):
			self.preserve_times = widget.get_active()
		elif(widget == self.wTree.get_widget("checkbutton_links")):
			self.follow_links = widget.get_active()
	
	''' Exclude file '''
	def add_file_exclude(self, widget):
		model = self.wTree.get_widget("treeview_excludes").get_model()
		dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_OPEN, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
		dialog.set_current_folder(self.backup_source)
		dialog.set_select_multiple(True)
		if dialog.run() == gtk.RESPONSE_OK:
			filenames = dialog.get_filenames()
			for filename in filenames:					
				if (not filename.find(self.backup_source)):
					model.append([filename[len(self.backup_source)+1:], self.fileIcon, filename])
				else:
					message = MessageDialog(_("Invalid path"), _("%s is not located within your source directory. Not added.") % filename, gtk.MESSAGE_WARNING)
		    			message.show()
		dialog.destroy()

	''' Exclude directory '''
	def add_folder_exclude(self, widget):
		model = self.wTree.get_widget("treeview_excludes").get_model()
		dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
		dialog.set_current_folder(self.backup_source)
		dialog.set_select_multiple(True)
		if dialog.run() == gtk.RESPONSE_OK:
			filenames = dialog.get_filenames()					
			for filename in filenames:
				if (not filename.find(self.backup_source)):
					model.append([filename[len(self.backup_source)+1:], self.dirIcon, filename])
				else:
					message = MessageDialog(_("Invalid path"), _("%s is not located within your source directory. Not added.") % filename, gtk.MESSAGE_WARNING)
		    			message.show()
		dialog.destroy()

	''' Remove the exclude '''
	def remove_exclude(self, widget):
		model = self.wTree.get_widget("treeview_excludes").get_model()
		selection = self.wTree.get_widget("treeview_excludes").get_selection()
		selected_rows = selection.get_selected_rows()[1]
		# don't you just hate python? :) Here's another hack for python not to get confused with its own paths while we're deleting multiple stuff. 
		# actually.. gtk is probably to blame here. 
		args = [(model.get_iter(path)) for path in selected_rows] 
		for iter in args:
        		model.remove(iter)
	
	''' Cancel clicked '''
	def cancel_callback(self, widget):
		if(self.tar is not None):
			self.tar.close()
			self.tar = None
		if(self.operating):
			# in the middle of a job, let the appropriate thread
			# handle the cancel
			self.operating = False
		else:
			# just quit :)
			gtk.main_quit()

	''' First page buttons '''
	def wizard_buttons_cb(self, widget, param):
		self.wTree.get_widget("notebook1").set_current_page(param)
		self.wTree.get_widget("button_back").show()
		self.wTree.get_widget("button_back").set_sensitive(True)
		self.wTree.get_widget("button_forward").show()
		self.wTree.get_widget("button_about").hide()
		if(param == 14):
			self.wTree.get_widget("button_forward").set_sensitive(False)
		else:
			self.wTree.get_widget("button_forward").set_sensitive(True)
			
	''' Next button '''
	def forward_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
		self.wTree.get_widget("button_back").set_sensitive(True)
		if(sel == 1):
			# choose source/dest
			if(self.backup_source == self.backup_dest):
				MessageDialog(_("Backup Tool"), _("Please choose different directories for the source and the destination"), gtk.MESSAGE_WARNING).show()
				return

			excludes = self.wTree.get_widget("treeview_excludes").get_model()
			auto_excludes = [home + "/.Trash", home + "/.local/share/Trash", home + "/.thumbnails"]
			for auto_exclude in auto_excludes:
				if os.path.exists(auto_exclude):			
					if (not auto_exclude.find(self.backup_source)):
						excludes.append([auto_exclude[len(self.backup_source)+1:], self.dirIcon, auto_exclude])
	
			book.set_current_page(2)
		elif(sel == 2):
			self.description = self.wTree.get_widget("entry_desc").get_text()
			# show overview
			model = gtk.ListStore(str, str)
			model.append(["<b>" + _("Source") + "</b>", self.backup_source])
			model.append(["<b>" + _("Destination") + "</b>", self.backup_dest])
			if (self.description != ""):
				model.append(["<b>" + _("Description") + "</b>", self.description])
			# find compression format
			sel = self.wTree.get_widget("combobox_compress").get_active()
			comp = self.wTree.get_widget("combobox_compress").get_model()
			model.append(["<b>" + _("Compression") + "</b>", comp[sel][0]])
			# find overwrite rules
			sel = self.wTree.get_widget("combobox_delete_dest").get_active()
			over = self.wTree.get_widget("combobox_delete_dest").get_model()
			model.append(["<b>" + _("Overwrite destination files") + "</b>", over[sel][0]])
			excludes = self.wTree.get_widget("treeview_excludes").get_model()
			for row in excludes:
				model.append(["<b>" + _("Exclude") + "</b>", row[2]])
			self.wTree.get_widget("treeview_overview").set_model(model)
			book.set_current_page(3)
			self.wTree.get_widget("button_forward").hide()
			self.wTree.get_widget("button_apply").show()
		elif(sel == 3):
			# start copying :D
			book.set_current_page(4)
			self.wTree.get_widget("button_apply").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			self.operating = True
			thread = threading.Thread(group=None, target=self.backup, name="mintBackup-copy", args=(), kwargs={})
			thread.start()
		elif(sel == 4):
			# show info page.
			self.wTree.get_widget("button_forward").hide()
			self.wTree.get_widget("button_back").hide()
			book.set_current_page(5)
		elif(sel == 6):
			# sanity check the files (file --mimetype)
			self.restore_source = self.wTree.get_widget("filechooserbutton_restore_source").get_filename()
			self.restore_dest = self.wTree.get_widget("filechooserbutton_restore_dest").get_filename()
			if(not self.restore_source or self.restore_source == ""):
				MessageDialog(_("Backup Tool"), _("Please choose a file to restore from"), gtk.MESSAGE_WARNING).show()
				return
			thread = threading.Thread(group=None, target=self.prepare_restore, name="mintBackup-prepare", args=(), kwargs={})
			thread.start()
		elif(sel == 7):
			# start restoring :D
			self.wTree.get_widget("button_apply").hide()
			self.wTree.get_widget("button_back").hide()
			book.set_current_page(8)
			self.operating = True
			thread = threading.Thread(group=None, target=self.restore, name="mintBackup-restore", args=(), kwargs={})
			thread.start()
		elif(sel == 8):
			# show last page(restore finished status)
			self.wTree.get_widget("button_forward").hide()
			self.wTree.get_widget("button_back").hide()
			book.set_current_page(9)
		elif(sel == 10):
			book.set_current_page(11)
			thr = threading.Thread(group=None, name="mintBackup-packages", target=self.load_packages, args=(), kwargs={})
			thr.start()
			self.wTree.get_widget("button_forward").hide()
			self.wTree.get_widget("button_apply").show()
		elif(sel == 11):
			# show progress of packages page 
			self.wTree.get_widget("button_forward").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			book.set_current_page(12)
			f = self.wTree.get_widget("filechooserbutton_package_dest").get_filename()
			if f is None:
				MessageDialog(_("Backup Tool"), _("Please choose a destination directory"), gtk.MESSAGE_ERROR).show()
				return
			else:
				self.package_dest = f
				self.operating = True
				thr = threading.Thread(group=None, name="mintBackup-packages", target=self.backup_packages, args=(), kwargs={})
				thr.start()
		elif(sel == 14):
			thr = threading.Thread(group=None, name="mintBackup-packages", target=self.load_package_list, args=(), kwargs={})
			thr.start()
		elif(sel == 15):
			inst = False
			model = self.wTree.get_widget("treeview_package_list").get_model()
			if(len(model) == 0):
				MessageDialog(_("Backup Tool"), _("No packages need to be installed at this time"), gtk.MESSAGE_INFO).show()
				return
			for row in model:
				if(row[0]):
					inst = True
					break
			if(not inst):
				MessageDialog(_("Backup Tool"), _("Please select one or more packages to install"), gtk.MESSAGE_ERROR).show()
				return
			else:
				thr = threading.Thread(group=None, name="mintBackup-packages", target=self.install_packages, args=(), kwargs={})
				thr.start()
							
	''' Back button '''
	def back_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
		self.wTree.get_widget("button_apply").hide()
		self.wTree.get_widget("button_forward").show()
		if(sel == 7 and len(sys.argv) == 2):
			self.wTree.get_widget("button_back").set_sensitive(False)
		if(sel == 6 or sel == 10 or sel == 14):
			book.set_current_page(0)
			self.wTree.get_widget("button_back").set_sensitive(False)
			self.wTree.get_widget("button_back").hide()
			self.wTree.get_widget("button_forward").hide()
			self.wTree.get_widget("button_about").show()
			if(self.tar is not None):
				self.tar.close()
				self.tar = None
		else:
			sel = sel -1
			if(sel == 0):
				self.wTree.get_widget("button_back").hide()
				self.wTree.get_widget("button_forward").hide()
				self.wTree.get_widget("button_about").show()
			book.set_current_page(sel)
		
	''' Creates a .mintbackup file (for later restoration) '''
	def create_backup_file(self):
		self.description = "mintBackup"
		desc = self.wTree.get_widget("entry_desc").get_text()
		if(desc != ""):
			self.description = desc
		try:
			of = os.path.join(self.backup_dest, ".mintbackup")
			out = open(of, "w")
			lines = [  "source: %s\n" % (self.backup_dest),
						"destination: %s\n" % (self.backup_source),
						"file_count: %s\n" % (self.file_count),
						"description: %s\n" % (self.description) ]
			out.writelines(lines)
			out.close()
		except:
			return False
		return True
		
	''' Does the actual copying '''
	def backup(self):
		label = self.wTree.get_widget("label_current_file_value")
		os.chdir(self.backup_source)
		pbar = self.wTree.get_widget("progressbar1")
		gtk.gdk.threads_enter()
		self.wTree.get_widget("button_apply").hide()
		self.wTree.get_widget("button_forward").hide()
		self.wTree.get_widget("button_back").hide()
		label.set_label(_("Calculating..."))
		pbar.set_text(_("Calculating..."))
		gtk.gdk.threads_leave()
		# get a count of all the files
		total = 0
		for top,dirs,files in os.walk(top=self.backup_source,onerror=None, followlinks=self.follow_links):
			gtk.gdk.threads_enter()
			pbar.pulse()
			gtk.gdk.threads_leave()
			for f in files:
				if(not self.operating):
					break
				if(not self.is_excluded(os.path.join(top, f))):
					total += 1
								
		sztotal = str(total)
		self.file_count = sztotal
		total = float(total)

		current_file = 0
		self.create_backup_file()
		
		# deletion policy
		del_policy = self.wTree.get_widget("combobox_delete_dest").get_active()

		# find out compression format, if any
		sel = self.wTree.get_widget("combobox_compress").get_active()
		comp = self.wTree.get_widget("combobox_compress").get_model()[sel]
		if(comp[1] is not None):
			tar = None
			filetime = strftime("%Y-%m-%d-%H%M-backup", localtime())
			filename = os.path.join(self.backup_dest, filetime + comp[2] + ".part")
			final_filename = os.path.join(self.backup_dest, filetime + comp[2])
			try:
				tar = tarfile.open(name=filename, dereference=self.follow_links, mode=comp[1], bufsize=1024)
				mintfile = os.path.join(self.backup_dest, ".mintbackup")
				tar.add(mintfile, arcname=".mintbackup", recursive=False, exclude=None)
			except Exception, detail:
				print detail
				self.errors.append([str(detail), None])
			for top,dirs,files in os.walk(top=self.backup_source, onerror=None, followlinks=self.follow_links):
				if(not self.operating or self.error is not None):
					break
				for f in files:
					rpath = os.path.join(top, f)
					path = os.path.relpath(rpath)
					if(not self.is_excluded(rpath)):
						if(os.path.islink(rpath)):
							if(self.follow_links):
								if(not os.path.exists(rpath)):
									self.update_restore_progress(0, 1, message=_("Skipping broken link"))
									self.errors.append([rpath, _("Broken link")])
									continue
							else:
								self.update_restore_progress(0, 1, message=_("Skipping link"))
								current_file += 1
								continue
						gtk.gdk.threads_enter()
						label.set_label(path)
						self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
						gtk.gdk.threads_leave()
						try:
							underfile = TarFileMonitor(rpath, self.update_backup_progress)
							finfo = tar.gettarinfo(name=None, arcname=path, fileobj=underfile)
							tar.addfile(fileobj=underfile, tarinfo=finfo)
							underfile.close()
						except Exception, detail:
							print detail
							self.errors.append([rpath, str(detail)])
						current_file = current_file + 1
			try:
				tar.close()
				os.remove(mintfile)
				os.rename(filename, final_filename)
			except Exception, detail:
				print detail
				self.errors.append([str(detail), None])
		else:
			# Copy to other directory, possibly on another device
			for top,dirs,files in os.walk(top=self.backup_source,topdown=False,onerror=None,followlinks=self.follow_links):
				if(not self.operating):
					break
				for f in files:
					rpath = os.path.join(top, f)
					path = os.path.relpath(rpath)
					if(not self.is_excluded(rpath)):
						target = os.path.join(self.backup_dest, path)
						if(os.path.islink(rpath)):
							if(self.follow_links):
								if(not os.path.exists(rpath)):
									self.update_restore_progress(0, 1, message=_("Skipping broken link"))
									current_file += 1
									continue
							else:
								self.update_restore_progress(0, 1, message=_("Skipping link"))
								current_file += 1
								continue
						dir = os.path.split(target)
						if(not os.path.exists(dir[0])):
							try:
								os.makedirs(dir[0])		
							except Exception, detail:
								print detail
								self.errors.append([dir[0], str(detail)])						
						gtk.gdk.threads_enter()
						label.set_label(path)
						self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
						gtk.gdk.threads_leave()
						try:
							if(os.path.exists(target)):
								if(del_policy == 1):
									# source size != dest size
									file1 = os.path.getsize(rpath)
									file2 = os.path.getsize(target)
									if(file1 != file2):
										os.remove(target)
										self.copy_file(rpath, target, sourceChecksum=None)
									else:
										self.update_backup_progress(0, 1, message=_("Skipping identical file"))
								elif(del_policy == 2):
									# source time != dest time
									file1 = os.path.getmtime(rpath)
									file2 = os.path.getmtime(target)
									if(file1 != file2):
										os.remove(target)
										self.copy_file(rpath, target, sourceChecksum=None)
									else:
										self.update_backup_progress(0, 1, message=_("Skipping identical file"))
								elif(del_policy == 3):
									# checksums
									file1 = self.get_checksum(rpath)
									file2 = self.get_checksum(target)
									if(file1 not in file2):
										os.remove(target)
										self.copy_file(rpath, target, sourceChecksum=file1)
									else:
										self.update_backup_progress(0, 1, message=_("Skipping identical file"))
								elif(del_policy == 4):
									# always delete
									os.remove(target)
									self.copy_file(rpath, target, sourceChecksum=None)
							else:
								self.copy_file(rpath, target, sourceChecksum=None)
							current_file = current_file + 1
						except Exception, detail:
							print detail
							self.errors.append([rpath, str(detail)])
					del f
					if(self.preserve_times or self.preserve_perms):
						# loop back over the directories now to reset the a/m/time
						for d in dirs:
							rpath = os.path.join(top, d)
							path = os.path.relpath(rpath)
							target = os.path.join(self.backup_dest, path)
							self.clone_dir(rpath, target)
							del d

		if(current_file < total):
			self.errors.append([_("Warning: Some files were not saved, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}, None])
		if(len(self.errors) > 0):
			gtk.gdk.threads_enter()
			img = self.iconTheme.load_icon("dialog-error", 48, 0)
			self.wTree.get_widget("label_finished_status").set_markup(_("An error occured during the backup"))
			self.wTree.get_widget("image_finished").set_from_pixbuf(img)
			self.wTree.get_widget("treeview_backup_errors").set_model(self.errors)
			self.wTree.get_widget("win_errors").show_all()
			self.wTree.get_widget("notebook1").next_page()
			gtk.gdk.threads_leave()
		else:
			if(not self.operating):
				gtk.gdk.threads_enter()
				img = self.iconTheme.load_icon("dialog-warning", 48, 0)
				self.wTree.get_widget("label_finished_status").set_label(_("The backup was aborted"))
				self.wTree.get_widget("image_finished").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
			else:
				gtk.gdk.threads_enter()
				label.set_label("Done")
				img = self.iconTheme.load_icon("dialog-information", 48, 0)
				self.wTree.get_widget("label_finished_status").set_label(_("The backup completed successfully"))
				self.wTree.get_widget("image_finished").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
		self.operating = False

	''' Returns true if the file/directory is on the exclude list '''
	def is_excluded(self, filename):
		for row in self.wTree.get_widget("treeview_excludes").get_model():
			if(filename.startswith(row[2])):
				return True
		return False

	''' Update the backup progress bar '''
	def update_backup_progress(self, current, total, message=None):
		current = float(current)
		total = float(total)
		fraction = float(current / total)
		gtk.gdk.threads_enter()
		self.wTree.get_widget("progressbar1").set_fraction(fraction)
		if(message is not None):
			self.wTree.get_widget("progressbar1").set_text(message)
		else:
			self.wTree.get_widget("progressbar1").set_text(str(int(fraction *100)) + "%")
		gtk.gdk.threads_leave()

	''' Utility method - copy file, also provides a quick way of aborting a copy, which
	    using modules doesn't allow me to do.. '''
	def copy_file(self, source, dest, restore=None, sourceChecksum=None):
		try:
			# represents max buffer size
			BUF_MAX = 16 * 1024 # so we don't get stuck on I/O ops
			errfile = None
			src = open(source, 'rb')
			total = os.path.getsize(source)
			current = 0
			dst = open(dest, 'wb')
			while True:
				if(not self.operating):
					# Abort!
					errfile = dest
					break
				read = src.read(BUF_MAX)
				if(read):
					dst.write(read)
					current += len(read)
					if(restore):
						self.update_restore_progress(current, total)
					else:
						self.update_backup_progress(current, total)
				else:
					break
			src.close()
			if(errfile):
				# Remove aborted file (avoid corruption)
				dst.close()
				os.remove(errfile)
			else:
				fd = dst.fileno()
				if(self.preserve_perms):
					# set permissions
					finfo = os.stat(source)
					owner = finfo[stat.ST_UID]
					group = finfo[stat.ST_GID]
					os.fchown(fd, owner, group)
					dst.flush()
					os.fsync(fd)
					dst.close()
				if(self.preserve_times):
					finfo = os.stat(source)
					atime = finfo[stat.ST_ATIME]
					mtime = finfo[stat.ST_MTIME]
					os.utime(dest, (atime, mtime))
				else:
					dst.flush()
					os.fsync(fd)
					dst.close()

				if(self.postcheck):
					if (sourceChecksum is not None):
						file1 = sourceChecksum
					else:
						file1 = self.get_checksum(source, restore)
					file2 = self.get_checksum(dest, restore)
					if(file1 not in file2):
						print _("Checksum Mismatch:") + " [" + file1 + "] [" + file1 + "]"
						self.errors.append([source, _("Checksum Mismatch")])
		except OSError as bad:
			if(len(bad.args) > 2):
				print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
				self.errors.append([bad.args[2], bad.args[1]])
			else:
				print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
				self.errors.append([source, bad.args[1]])
			
	
	''' mkdir and clone permissions '''
	def clone_dir(self, source, dest):
		try:
			if(not os.path.exists(dest)):
				os.mkdir(dest)
			if(self.preserve_perms):
				finfo = os.stat(source)
				owner = finfo[stat.ST_UID]
				group = finfo[stat.ST_GID]
				os.chown(dest, owner, group)
			if(self.preserve_times):
				finfo = os.stat(source)
				atime = finfo[stat.ST_ATIME]
				mtime = finfo[stat.ST_MTIME]
				os.utime(dest, (atime, mtime))
		except OSError as bad:
			if(len(bad.args) > 2):
				print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
				self.errors.append([bad.args[2], bad.args[1]])
			else:
				print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
				self.errors.append([source, bad.args[1]])
				
	''' Grab the checksum for the input filename and return it '''
	def get_checksum(self, source, restore=None):
		MAX_BUF = 16*1024
		current = 0
		try:
			check = hashlib.sha1()
			input = open(source, "rb")
			total = os.path.getsize(source)
			while True:
				if(not self.operating):
					return None
				read = input.read(MAX_BUF)
				if(not read):
					break
				check.update(read)
				current += len(read)
				if(restore):
					self.update_restore_progress(current, total, message=_("Calculating checksum"))
				else:
					self.update_backup_progress(current, total, message=_("Calculating checksum"))
			input.close()
			return check.hexdigest()
		except OSError as bad:
			if(len(bad.args) > 2):
				print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
				self.errors.append([bad.args[2], bad.args[1]])
			else:
				print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
				self.errors.append([source, bad.args[1]])
		return None

	''' Grabs checksum for fileobj type object '''
	def get_checksum_for_file(self, source):
		MAX_BUF = 16*1024
		current = 0
		total = source.size
		try:
			check = hashlib.sha1()
			while True:
				if(not self.operating):
					return None
				read = source.read(MAX_BUF)
				if(not read):
					break
				check.update(read)
				current += len(read)
				self.update_restore_progress(current, total, message=_("Calculating checksum"))
			source.close()
			return check.hexdigest()
		except Exception, detail:
			self.errors.append([source, str(detail)])
			print detail
		return None
		
	''' Update the restore progress bar '''
	def update_restore_progress(self, current, total, message=None):
		current = float(current)
		total = float(total)
		fraction = float(current / total)
		gtk.gdk.threads_enter()
		self.wTree.get_widget("progressbar_restore").set_fraction(fraction)
		if(message is not None):
			self.wTree.get_widget("progressbar_restore").set_text(message)
		else:
			self.wTree.get_widget("progressbar_restore").set_text(str(int(fraction *100)) + "%")
		gtk.gdk.threads_leave()

	''' prepare the restore, reads the .mintbackup file if present '''
	def prepare_restore(self):
		if(self.restore_archive):
			# restore archives.
			if(self.tar is not None):
				gtk.gdk.threads_enter()
				self.wTree.get_widget("notebook1").set_current_page(7)
				self.wTree.get_widget("button_forward").hide()
				self.wTree.get_widget("button_apply").show()
				gtk.gdk.threads_leave()
				return
			gtk.gdk.threads_enter()
			self.wTree.get_widget("main_window").set_sensitive(False)
			self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
			gtk.gdk.threads_leave()
			self.conf = mINIFile()
			try:
				self.tar = tarfile.open(self.restore_source, "r")
				mintfile = self.tar.getmember(".mintbackup")
				if(mintfile is None):
					print "Processing a backup not created with this tool"
					self.conf.description = _("(Not created with the Backup Tool)")
					self.conf.file_count = -1
				else:
					mfile = self.tar.extractfile(mintfile)
					self.conf.load_from_list(mfile.readlines())
					mfile.close()
				
				gtk.gdk.threads_enter()
				self.wTree.get_widget("label_overview_description_value").set_label(self.conf.description)
				self.wTree.get_widget("button_back").set_sensitive(True)
				self.wTree.get_widget("button_forward").hide()
				self.wTree.get_widget("button_apply").show()
				self.wTree.get_widget("notebook1").set_current_page(7)
				gtk.gdk.threads_leave()

			except Exception, detail:
				print detail
		else:
			# Restore from directory
			self.conf = mINIFile()
			try:
				mfile = os.path.join(self.restore_source, ".mintbackup")
				if(not os.path.exists(mfile)):
					print "Processing a backup not created with this tool"
					self.conf.description = _("(Not created with the Backup Tool)")
					self.conf.file_count = -1
				else:
					self.conf.load_from_file(mfile)

				gtk.gdk.threads_enter()
				self.wTree.get_widget("label_overview_description_value").set_label(self.conf.description)
				self.wTree.get_widget("button_back").set_sensitive(True)
				self.wTree.get_widget("button_forward").hide()
				self.wTree.get_widget("button_apply").show()
				self.wTree.get_widget("notebook1").set_current_page(7)
				gtk.gdk.threads_leave()
				
			except Exception, detail:
				print detail
		gtk.gdk.threads_enter()
		self.wTree.get_widget("label_overview_source_value").set_label(self.restore_source)
		self.wTree.get_widget("label_overview_dest_value").set_label(self.restore_dest)
		self.wTree.get_widget("main_window").set_sensitive(True)
		self.wTree.get_widget("main_window").window.set_cursor(None)
		gtk.gdk.threads_leave()
		
	''' extract file from archive '''
	def extract_file(self, source, dest, record):
		MAX_BUF = 512
		current = 0
		total = record.size
		errflag = False
		while True:
			if(not self.operating):
				errflag = True
				break
			read = source.read(MAX_BUF)
			if(not read):
				break
			dest.write(read)
			current += len(read)
			self.update_restore_progress(current, total)
		source.close()
		if(errflag):
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

	''' Restore from archive '''
	def restore(self):
		self.preserve_perms = True
		self.preserve_times = True
		self.postcheck = True
		gtk.gdk.threads_enter()
		self.wTree.get_widget("button_apply").hide()
		self.wTree.get_widget("button_forward").hide()
		self.wTree.get_widget("button_back").hide()
		gtk.gdk.threads_leave()
		
		del_policy = self.wTree.get_widget("combobox_restore_del").get_active()
		gtk.gdk.threads_enter()
		pbar = self.wTree.get_widget("progressbar_restore")
		pbar.set_text(_("Calculating..."))
		label = self.wTree.get_widget("label_restore_status_value")
		label.set_label(_("Calculating..."))
		gtk.gdk.threads_leave()

		# restore from archive
		self.error = None
		if(self.restore_archive):	
			os.chdir(self.restore_dest)
			sztotal = self.conf.file_count
			total = float(sztotal)
			if(total == -1):
				tmp = len(self.tar.getmembers())
				szttotal = str(tmp)
				total = float(tmp)
			current_file = 0
			MAX_BUF = 1024
			for record in self.tar.getmembers():
				if(not self.operating):
					break
				if(record.name == ".mintbackup"):
					# skip mintbackup file
					continue
				gtk.gdk.threads_enter()
				label.set_label(record.name)
				gtk.gdk.threads_leave()
				if(record.isdir()):
					target = os.path.join(self.restore_dest, record.name)
					if(not os.path.exists(target)):
						try:
							os.mkdir(target)
							os.chown(target, record.uid, record.gid)
							os.chmod(target, record.mode)
							os.utime(target, (record.mtime, record.mtime))
						except Exception, detail:
							print detail
							self.errors.append([target, str(detail)])
				if(record.isreg()):
					target = os.path.join(self.restore_dest, record.name)
					dir = os.path.split(target)
					if(not os.path.exists(dir[0])):
						try:
							os.makedirs(dir[0])
						except Exception, detail:
							print detail
							self.errors.append([dir[0], str(detail)])
					gtk.gdk.threads_enter()
					self.wTree.get_widget("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
					gtk.gdk.threads_leave()
					try:
						if(os.path.exists(target)):
							if(del_policy == 1):
								# source size != dest size
								file1 = record.size
								file2 = os.path.getsize(target)
								if(file1 != file2):
									os.remove(target)
									gz = self.tar.extractfile(record)
									out = open(target, "wb")
									self.extract_file(gz, out, record)
								else:
									self.update_restore_progress(0, 1, message=_("Skipping identical file"))
							elif(del_policy == 2):
								# source time != dest time
								file1 = record.mtime
								file2 = os.path.getmtime(target)
								if(file1 != file2):
									os.remove(target)
									gz = self.tar.extractfile(record)
									out = open(target, "wb")
									self.extract_file(gz, out, record)
								else:
									self.update_restore_progress(0, 1, message=_("Skipping identical file"))
							elif(del_policy == 3):
								# checksums
								gz = self.tar.extractfile(record)
								file1 = self.get_checksum_for_file(gz)
								file2 = self.get_checksum(target)
								if(file1 not in file2):
									os.remove(target)
									out = open(target, "wb")
									gz.close()
									gz = self.tar.extractfile(record)
									self.extract_file(gz, out, record)
								else:
									self.update_restore_progress(0, 1, message=_("Skipping identical file"))
							elif(del_policy == 4):
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
					except Exception, detail:
						print detail
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
			if(total == -1):
				for top,dirs,files in os.walk(top=self.restore_source,onerror=None, followlinks=self.follow_links):
					pbar.pulse()
					for f in files:
						if(not self.operating):
							break
						total += 1
				sztotal = str(total)
				total = float(total)
			for top,dirs,files in os.walk(top=self.restore_source,topdown=False,onerror=None,followlinks=self.follow_links):
				if(not self.operating):
					break
				for f in files:
					if ".mintbackup" in f:
						continue
					rpath = os.path.join(top, f)
					path = os.path.relpath(rpath)
					target = os.path.join(self.restore_dest, path)	
					dir = os.path.split(target)
					if(not os.path.exists(dir[0])):
						try:
							os.makedirs(dir[0])	
						except Exception, detail:
							print detail
							self.errors.append([dir[0], str(detail)])							
					current_file = current_file + 1
					gtk.gdk.threads_enter()
					label.set_label(path)
					gtk.gdk.threads_leave()
					self.wTree.get_widget("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
					try:
						if(os.path.exists(target)):
							if(del_policy == 1):
								# source size != dest size
								file1 = os.path.getsize(rpath)
								file2 = os.path.getsize(target)
								if(file1 != file2):
									os.remove(target)
									self.copy_file(rpath, target, restore=True, sourceChecksum=None)
								else:
									self.update_restore_progress(0, 1, message=_("Skipping identical file"))
							elif(del_policy == 2):
								# source time != dest time
								file1 = os.path.getmtime(rpath)
								file2 = os.path.getmtime(target)
								if(file1 != file2):
									os.remove(target)
									self.copy_file(rpath, target, restore=True, sourceChecksum=None)
								else:
									self.update_restore_progress(0, 1, message=_("Skipping identical file"))
							elif(del_policy == 3):
								# checksums (check size first)
								if(os.path.getsize(rpath) == os.path.getsize(target)):
									file1 = self.get_checksum(rpath)
									file2 = self.get_checksum(target)
									if(file1 not in file2):
										os.remove(target)
										self.copy_file(rpath, target, restore=True, sourceChecksum=file1)
									else:
										self.update_restore_progress(0, 1, message=_("Skipping identical file"))
								else:
									os.remove(target)
									self.copy_file(rpath, target, restore=True, sourceChecksum=None)
							elif(del_policy == 4):
								# always delete
								os.remove(target)
								self.copy_file(rpath, target, restore=True, sourceChecksum=None)
						else:
							self.copy_file(rpath, target, restore=True, sourceChecksum=None)
						current_file += 1
					except Exception, detail:
						print detail
						self.errors.append([rpath, str(detail)])
					del f
					if(self.preserve_times or self.preserve_perms):
						# loop back over the directories now to reset the a/m/time
						for d in dirs:
							rpath = os.path.join(top, d)
							path = os.path.relpath(rpath)
							target = os.path.join(self.restore_dest, path)
							self.clone_dir(rpath, target)
							del d
		if(current_file < total):
			self.error = _("Warning: Some filed were not restored, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}
		if(len(self.errors) > 0):
			gtk.gdk.threads_enter()
			self.wTree.get_widget("label_restore_finished_value").set_label(_("An error occured during the restoration"))
			img = self.iconTheme.load_icon("dialog-error", 48, 0)
			self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
			self.wTree.get_widget("treeview_restore_errors").set_model(self.errors)
			self.wTree.get_widget("win_restore_errors").show_all()
			self.wTree.get_widget("notebook1").next_page()
			gtk.gdk.threads_leave()
		else:
			if(not self.operating):
				gtk.gdk.threads_enter()
				img = self.iconTheme.load_icon("dialog-warning", 48, 0)
				self.wTree.get_widget("label_restore_finished_value").set_label(_("The restoration was aborted"))
				self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
			else:
				gtk.gdk.threads_enter()
				label.set_label("Done")
				pbar.set_text("Done")
				self.wTree.get_widget("label_restore_finished_value").set_label(_("The restoration completed successfully"))
				img = self.iconTheme.load_icon("dialog-information", 48, 0)
				self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
		self.operating = False
		
		''' load the package list '''
	def load_packages(self):
		gtk.gdk.threads_enter()
		model = gtk.ListStore(bool, str, str)
		model.set_sort_column_id(1, gtk.SORT_ASCENDING)
		self.wTree.get_widget("treeview_packages").set_model(model)
		self.wTree.get_widget("main_window").set_sensitive(False)
		self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		gtk.gdk.threads_leave()
		try:
			p = subprocess.Popen("aptitude search ~M", shell=True, stdout=subprocess.PIPE)
			self.blacklist = list()
			for l in p.stdout:
				l = l.rstrip("\r\n")
				l = l.split(" ")
				self.blacklist.append(l[2])
			bl = open("/usr/lib/linuxmint/mintBackup/software-selections.list", "r")
			for l in bl.readlines():
				if(l.startswith("#")):
					# ignore comments
					continue
				l = l.rstrip("\r\n")
				self.blacklist.append(l)
			bl.close()
		except Exception, detail:
			print detail
		cache = apt.Cache()
		for pkg in cache:
			if(pkg.installed):
				if(self.is_manual_installed(pkg.name) == True):
					desc = "<big>" + pkg.name + "</big>\n<small>" + pkg.installed.summary.replace("&", "&amp;") + "</small>"
					gtk.gdk.threads_enter()
					model.append([True, pkg.name, desc])
					gtk.gdk.threads_leave()
		gtk.gdk.threads_enter()
		self.wTree.get_widget("main_window").set_sensitive(True)
		self.wTree.get_widget("main_window").window.set_cursor(None)
		gtk.gdk.threads_leave()
	
	''' Is the package manually installed? '''
	def is_manual_installed(self, pkgname):
		for b in self.blacklist:
			if(pkgname == b):
				return False
		return True
		
	''' toggled (update model)'''
	def toggled_cb(self, ren, path, treeview):
		model = treeview.get_model()
		iter = model.get_iter(path)
		if (iter != None):
			checked = model.get_value(iter, 0)
			model.set_value(iter, 0, (not checked))

	''' for the packages treeview '''
	def celldatafunction_checkbox(self, column, cell, model, iter):
		checked = model.get_value(iter, 0)
		cell.set_property("active", checked)

	''' Show filechooser for package backup '''
	def show_package_choose(self, w):
		dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SAVE, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_SAVE, gtk.RESPONSE_OK))
		dialog.set_current_folder(home)
		dialog.set_select_multiple(False)
		if dialog.run() == gtk.RESPONSE_OK:			
			self.package_dest = dialog.get_filename()
			self.wTree.get_widget("entry_package_dest").set_text(self.package_dest)
		dialog.destroy()

	''' "backup" the package selection '''
	def backup_packages(self):
		pbar = self.wTree.get_widget("progressbar_packages")
		lab = self.wTree.get_widget("label_current_package_value")
		gtk.gdk.threads_enter()
		pbar.set_text(_("Calculating..."))
		lab.set_label(_("Calculating..."))
		gtk.gdk.threads_leave()
		model = self.wTree.get_widget("treeview_packages").get_model()
		total = 0
		count = 0
		for row in model:
			if(not self.operating or self.error is not None):
				break
			if(not row[0]):
				continue
			total += 1
		pbar.set_text("%d / %d" % (count, total))
		try:
			filetime = strftime("%Y-%m-%d-%H%M-package.list", localtime())
			filename = "software_selection_%s@%s" % (commands.getoutput("hostname"), filetime)
			out = open(os.path.join(self.package_dest, filename), "w")
			for row in model:
				if(not self.operating or self.error is not None):
					break
				if(row[0]):
					count += 1
					out.write("%s\t%s\n" % (row[1], "install"))
					gtk.gdk.threads_enter()
					pbar.set_text("%d / %d" % (count, total))
					pbar.set_fraction(float(count / total))
					lab.set_label(row[1])
					gtk.gdk.threads_leave()
			out.close()
			os.system("chmod a+rx " + self.package_dest) 
			os.system("chmod a+rw " + os.path.join(self.package_dest, filename))
		except Exception, detail:
			self.error = str(detail)
			
		if(self.error is not None):
			gtk.gdk.threads_enter()
			self.wTree.get_widget("label_packages_done_value").set_label(_("An error occured during the backup:") + "\n" + self.error)
			img = self.iconTheme.load_icon("dialog-error", 48, 0)
			self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
			self.wTree.get_widget("notebook1").next_page()
			gtk.gdk.threads_leave()
		else:
			if(not self.operating):
				gtk.gdk.threads_enter()
				img = self.iconTheme.load_icon("dialog-warning", 48, 0)
				self.wTree.get_widget("label_packages_done_value").set_label(_("The backup was aborted"))
				self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
			else:
				gtk.gdk.threads_enter()
				lab.set_label("Done")
				pbar.set_text("Done")
				self.wTree.get_widget("label_packages_done_value").set_label(_("Your software selection was backed up succesfully"))
				img = self.iconTheme.load_icon("dialog-information", 48, 0)
				self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
		gtk.gdk.threads_enter()
		self.wTree.get_widget("button_apply").hide()
		self.wTree.get_widget("button_back").hide()
		gtk.gdk.threads_leave()
		self.operating = False

	''' check validity of file'''
	def load_package_list_cb(self, w):
		self.package_source = w.get_filename()
		# magic info, i.e. we ignore files what don't have this.
		try:
			source = open(self.package_source, "r")
			re = source.readlines()
			error = False
			for line in re:
				line = line.rstrip("\r\n")
				if(not line.endswith("\tinstall")):
					error = True
					break
			source.close()
			if(error):
				MessageDialog(_("Backup Tool"), _("The specified file is not a valid software selection"), gtk.MESSAGE_ERROR).show()
				#self.wTree.get_widget("scroller_packages").hide()
				self.wTree.get_widget("button_forward").set_sensitive(False)
				return
			else:
				self.wTree.get_widget("button_forward").set_sensitive(True)
		except Exception, detail:
			print detail
			MessageDialog(_("Backup Tool"), _("An error occurred while accessing the file"), gtk.MESSAGE_ERROR).show()

	''' load package list into treeview '''
	def load_package_list(self):
		gtk.gdk.threads_enter()
		self.wTree.get_widget("button_forward").hide()
		self.wTree.get_widget("button_apply").show()
		self.wTree.get_widget("button_apply").set_sensitive(True)
		self.wTree.get_widget("main_window").set_sensitive(False)
		self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		model = gtk.ListStore(bool,str,bool,str)
		self.wTree.get_widget("treeview_package_list").set_model(model)
		gtk.gdk.threads_leave()
		try:
			source = open(self.package_source, "r")
			cache = apt.Cache()
			for line in source.readlines():
				if(line.startswith("#")):
					# ignore comments
					continue
				line = line.rstrip("\r\n")
				line = line.split("\t")[0]
				inst = True
				if(cache.has_key(line)):
					pkg = cache[line]
					if(not pkg.isInstalled):
						desc = pkg.candidate.summary.replace("&", "&amp;")
						line = "<big>" + line + "</big>\n<small>" + desc + "</small>"
					else:
						inst = False
						line = "<big>" + line + "</big>\n<small>" + _("Could not locate the package") + "</small>"

					gtk.gdk.threads_enter()
					model.append([inst, line, inst, pkg.name])
					gtk.gdk.threads_leave()
			source.close()
		except Exception, detail:
			print detail
			MessageDialog(_("Backup Tool"), _("An error occurred while accessing the file"), gtk.MESSAGE_ERROR).show()
		gtk.gdk.threads_enter()
		self.wTree.get_widget("main_window").set_sensitive(True)
		self.wTree.get_widget("main_window").window.set_cursor(None)
		if(len(model) == 0):
			self.wTree.get_widget("button_forward").hide()
			self.wTree.get_widget("button_back").hide()
			self.wTree.get_widget("button_apply").hide()
			self.wTree.get_widget("notebook1").set_current_page(16)
		else:
			self.wTree.get_widget("notebook1").set_current_page(15)
			self.wTree.get_widget("button_forward").set_sensitive(True)
		gtk.gdk.threads_leave()
		
	''' Installs the package selection '''
	def install_packages(self):
		# launch synaptic..
		gtk.gdk.threads_enter()
		self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		self.wTree.get_widget("main_window").set_sensitive(False)
		gtk.gdk.threads_leave()
		
		cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window", "--non-interactive", "--parent-window-id", str(self.wTree.get_widget("main_window").window.xid)]
		cmd.append("--progress-str")
		cmd.append("\"" + _("Please wait, this can take some time") + "\"")
		cmd.append("--finish-str")
		cmd.append("\"" + _("The installation is complete") + "\"")
		f = tempfile.NamedTemporaryFile()
		model = self.wTree.get_widget("treeview_package_list").get_model()
		for row in model:
			if(row[0]):
				f.write("%s\tinstall\n" % row[3])
		cmd.append("--set-selections-file")
		cmd.append("%s" % f.name)
		f.flush()
		comnd = subprocess.Popen(' '.join(cmd), shell=True)
		returnCode = comnd.wait()
		f.close()
		
		gtk.gdk.threads_enter()
		self.wTree.get_widget("main_window").window.set_cursor(None)
		self.wTree.get_widget("main_window").set_sensitive(True)
		self.wTree.get_widget("button_back").set_sensitive(True)
		self.wTree.get_widget("button_forward").set_sensitive(True)
		gtk.gdk.threads_leave()
		

		self.refresh(None)
	''' select/deselect all '''
	def set_selection(self, w, treeview, selection, check):
		model = treeview.get_model()
		for row in model:
			if(check):
				if row[2]:
					row[0] = selection
			else:
				row[0] = selection

	''' refresh package selection '''
	def refresh(self, w):
		# refresh package list
		thr = threading.Thread(group=None, name="mintBackup-packages", target=self.load_package_list, args=(), kwargs={})
		thr.start()

if __name__ == "__main__":
	gtk.gdk.threads_init()
	MintBackup()
	gtk.main()

