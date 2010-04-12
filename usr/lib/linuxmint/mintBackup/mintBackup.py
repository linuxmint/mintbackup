#!/usr/bin/env python

# mintBackup - A GUI backup and restoration utility
# Author: Ikey Doherty <contactjfreak@googlemail.com>
# Several parts of this program originate from the original
# mintBackup code by Clement Lefebvre <root@linuxmint.com>
# Those parts are the "MessageDialog" class, the add_folder_exclude,
# remove_exclude and add_file_exclude methods (although somewhat modified)

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

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
except Exception, detail:
	print "You do not have the required dependencies"

# i18n
gettext.install("messages", "/usr/lib/linuxmint/mintBackup/locale")

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
				tmp = " ".join(l[1:]).rstrip("\r\n")
				setattr(self, l[0], tmp)
		elif(line.find("=")):
			l = line.split("=")
			if(len(l) >= 2):
				tmp = " ".join(l[1:]).rstrip("\r\n")
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
class MessageDialog:

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
		self.preserve_perms = False
		# preserve times?
		self.preserve_times = False
		# post-check files?
		self.postcheck = True
		# follow symlinks?
		self.follow_links = False
		# error?
		self.error = None
		# tarfile
		self.tar = None
		self.backup_source = ""

		# page 0
		self.wTree.get_widget("button_backup_files").connect("clicked", self.wizard_buttons_cb, 1)
		self.wTree.get_widget("button_restore_files").connect("clicked", self.wizard_buttons_cb, 6)
		self.wTree.get_widget("button_backup_packages").connect("clicked", self.wizard_buttons_cb, 10)
		
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
		overs.append([_("Source file larger than destination")])
		overs.append([_("Source file smaller than destination")])
		overs.append([_("Source file newer than destination")])
		overs.append([_("Checksum mismatch")])
		overs.append([_("Always")])
		self.wTree.get_widget("combobox_delete_dest").set_model(overs)
		self.wTree.get_widget("combobox_delete_dest").set_active(0)

		# advanced options
		self.wTree.get_widget("checkbutton_integrity").set_active(True)
		self.wTree.get_widget("checkbutton_integrity").connect("clicked", self.handle_checkbox)
		self.wTree.get_widget("checkbutton_perms").connect("clicked", self.handle_checkbox)
		self.wTree.get_widget("checkbutton_times").connect("clicked", self.handle_checkbox)
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
		column = gtk.TreeViewColumn("Excluded paths", ren)
		column.add_attribute(ren, "text", 0)
		self.wTree.get_widget("treeview_excludes").append_column(column)
		self.wTree.get_widget("treeview_excludes").set_model(gtk.ListStore(str, gtk.gdk.Pixbuf, str))
		self.wTree.get_widget("button_add_file").connect("clicked", self.add_file_exclude)
		self.wTree.get_widget("button_add_folder").connect("clicked", self.add_folder_exclude)
		self.wTree.get_widget("button_remove_exclude").connect("clicked", self.remove_exclude)

		# set up overview page
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn("Type", ren)
		column.add_attribute(ren, "markup", 0)
		self.wTree.get_widget("treeview_overview").append_column(column)
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn("Detail", ren)
		column.add_attribute(ren, "text", 1)
		self.wTree.get_widget("treeview_overview").append_column(column)

		# nav buttons
		self.wTree.get_widget("button_back").connect("clicked", self.back_callback)
		self.wTree.get_widget("button_forward").connect("clicked", self.forward_callback)
		self.wTree.get_widget("button_cancel").connect("clicked", self.cancel_callback)

		self.wTree.get_widget("button_back").hide()
		self.wTree.get_widget("button_forward").hide()
		self.wTree.get_widget("main_window").connect("destroy", self.cancel_callback)
		self.wTree.get_widget("main_window").set_title(_("Backup Tool"))
		self.wTree.get_widget("main_window").show()

		# open archive button, opens an archive... :P
		self.wTree.get_widget("button_open_archive").connect("clicked", self.open_archive_callback)
		self.wTree.get_widget("filechooserbutton_restore_source").connect("file-set", self.check_reset_file)
		self.wTree.get_widget("combobox_restore_del").set_model(overs)
		self.wTree.get_widget("combobox_restore_del").set_active(0)
		
		# pagr 10 (packages list)
		self.wTree.get_widget("button_package_dest").connect("clicked", self.show_package_choose)
		t = self.wTree.get_widget("treeview_packages")
		tog = gtk.CellRendererToggle()
		tog.connect("toggled", self.toggled_cb)
		c1 = gtk.TreeViewColumn("Store?", tog, active=0)
		c1.set_cell_data_func(tog, self.celldatafunction_checkbox)
		t.append_column(c1)
		c2 = gtk.TreeViewColumn("Name", gtk.CellRendererText(), markup=2)
		t.append_column(c2)
		
		# i18n - Page 0 (choose backup or restore)
		self.wTree.get_widget("label_wizard").set_markup(_("<big><b>Backup Tool</b></big>\nThis wizard will allow you to make a backup, or to\nrestore a previously created backup"))
		#self.wTree.get_widget("radiobutton_backup").set_label(_("Create a new backup"))
		#self.wTree.get_widget("radiobutton_restore").set_label(_("Restore an existing backup"))

		# i18n - Page 1 (choose backup directories)
		self.wTree.get_widget("label_backup_dirs").set_markup(_("<big><b>Backup Tool</b></big>\nYou now need to choose the source and destination\ndirectories for the backup"))
		self.wTree.get_widget("label_backup_source").set_label(_("Source:"))
		self.wTree.get_widget("label_backup_dest").set_label(_("Destination:"))
		self.wTree.get_widget("label_backup_desc").set_label(_("Description:"))
		self.wTree.get_widget("label_expander").set_label(_("Advanced options"))
		self.wTree.get_widget("label_compress").set_label(_("Output:"))
		self.wTree.get_widget("label_overwrite_dest").set_label(_("Overwrite:"))
		self.wTree.get_widget("checkbutton_integrity").set_label(_("Confirm integrity"))
		self.wTree.get_widget("checkbutton_links").set_label(_("Follow symlinks"))
		self.wTree.get_widget("checkbutton_perms").set_label(_("Preserve permissions"))
		self.wTree.get_widget("checkbutton_times").set_label(_("Preserve timestamps"))

		# i18n - Page 2 (choose files/directories to exclude)
		self.wTree.get_widget("label_exclude_dirs").set_markup(_("<big><b>Backup Tool</b></big>\nIf you wish to exclude any files or directories from being\nbacked up by this wizard, please add them to the list below.\nAll files and directories listed here will NOT be backed up."))
		self.wTree.get_widget("label_add_file").set_label(_("Exclude files"))
		self.wTree.get_widget("label_add_folder").set_label(_("Exclude directories"))
		self.wTree.get_widget("label_remove").set_label(_("Remove"))

		# i18n - Page 3 (backup overview)
		self.wTree.get_widget("label_backup_overview").set_markup(_("<big><b>Backup Tool</b></big>\nPlease review your options below.\nWhen you are happy with your choice click\nthe Forward button to continue."))

		# i18n - Page 4 (backing up status)
		self.wTree.get_widget("label_backing_up").set_markup(_("<big><b>Backup Tool</b></big>\nCurrently backing up. This may take some time."))
		self.wTree.get_widget("label_current_file").set_label(_("Current file:"))

		# i18n - Page 5 (backup complete)
		self.wTree.get_widget("label_finished").set_markup(_("<big><b>Backup Tool</b></big>"))

		# i18n - Page 6 (Restore locations)
		self.wTree.get_widget("label_restore_wizard").set_markup(_("<big><b>Backup Tool</b></big>\nPlease select the backup you wish to restore\nand its destination below"))
		self.wTree.get_widget("label_restore_source").set_label(_("Archive:"))
		self.wTree.get_widget("label_restore_dest").set_label(_("Destination:"))
		self.wTree.get_widget("label_restore_advanced").set_label(_("Advanced options"))
		self.wTree.get_widget("label_restore_overwrite").set_label(_("Overwrite:"))

		# i18n - Page 7 (Restore overview)
		self.wTree.get_widget("label_restore_overview").set_markup(_("<big><b>Backup Tool</b></big>\nWhen you are happy with the settings below\npress the Forward button to restore your backup"))
		self.wTree.get_widget("label_overview_source").set_markup(_("<b>Archive:</b>"))
		self.wTree.get_widget("label_overview_description").set_markup(_("<b>Description:</b>"))
		self.wTree.get_widget("label_open_archive").set_label(_("Open"))

		# i18n - Page 8 (restore status)
		self.wTree.get_widget("label_restore_progress").set_markup(_("<big><b>Backup Tool</b></big>\nNow restoring your backup, this may take\nsome time so please be patient"))
		self.wTree.get_widget("label_restore_status").set_label(_("Current file:"))

		# i18n - Page 9 (restore complete)
		self.wTree.get_widget("label_restore_finished").set_markup(_("<big><b>Backup Tool</b></big>"))

		# i18n - Page 10 (packages)
		self.wTree.get_widget("label_packages").set_markup(_("<big><b>Backup Tool</b></big>\nA list of manually installed packages is displayed below\nWhen you are happy with the selection press forward."))
		self.wTree.get_widget("label_save_as").set_label(_("Save as..."))
		
		# i18n - Page 11 (backing up packages)
		self.wTree.get_widget("label_packages_backup").set_markup(_("<big><b>Backup Tool</b></big>\nCurrently backing up your package selection\nPlease wait"))
		self.wTree.get_widget("label_current_package").set_label(_("Current package:"))
		
		# i18n - Page 12 (packages done)
		self.wTree.get_widget("label_packages_done").set_markup(_("<big><b>Backup Tool</b></big>"))

	''' handle the file-set signal '''
	def check_reset_file(self, w):
		fileset = w.get_filename()
		if(fileset not in self.backup_source):
			if(self.tar is not None):
				self.tar.close()
				self.tar = None
		self.backup_source = fileset
		
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
					message = MessageDialog(_("Invalid path"), filename + " " + _("is not located within your source directory. Not added."), gtk.MESSAGE_WARNING)
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
					message = MessageDialog(_("Invalid path"), filename + " " + _("is not located within your source directory. Not added."), gtk.MESSAGE_WARNING)
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
		
		if(param == 10):
			thr = threading.Thread(group=None, name="mintBackup-packages", target=self.load_packages, args=(), kwargs={})
			thr.start()
	''' Next button '''
	def forward_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
		self.wTree.get_widget("button_back").set_sensitive(True)
		if(sel == 1):
			# choose source/dest
			self.backup_source = self.wTree.get_widget("filechooserbutton_backup_source").get_filename()
			self.backup_dest = self.wTree.get_widget("filechooserbutton_backup_dest").get_filename()
			if(self.backup_source == self.backup_dest):
				MessageDialog(_("Backup Tool"), _("Your source and destination directories cannot be the same"), gtk.MESSAGE_WARNING).show()
				return
			book.set_current_page(2)
		elif(sel == 2):
			self.description = self.wTree.get_widget("entry_desc").get_text()
			# show overview
			model = gtk.ListStore(str, str)
			model.append([_("<b>Source</b>"), self.backup_source])
			model.append([_("<b>Destination</b>"), self.backup_dest])
			model.append([_("<b>Description</b>"), self.description])
			# find compression format
			sel = self.wTree.get_widget("combobox_compress").get_active()
			comp = self.wTree.get_widget("combobox_compress").get_model()
			model.append([_("<b>Compression</b>"), comp[sel][0]])
			# find overwrite rules
			sel = self.wTree.get_widget("combobox_delete_dest").get_active()
			over = self.wTree.get_widget("combobox_delete_dest").get_model()
			model.append([_("<b>Overwrite destination files</b>"), over[sel][0]])
			excludes = self.wTree.get_widget("treeview_excludes").get_model()
			for row in excludes:
				model.append([_("<b>Exclude</b>"), row[2]])
			self.wTree.get_widget("treeview_overview").set_model(model)
			book.set_current_page(3)
		elif(sel == 3):
			# start copying :D
			book.set_current_page(4)
			self.wTree.get_widget("button_forward").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			self.operating = True
			thread = threading.Thread(group=None, target=self.backup, name="mintBackup-copy", args=(), kwargs={})
			thread.start()
		elif(sel == 4):
			# show info page.
			self.wTree.get_widget("button_forward").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			book.set_current_page(5)
		elif(sel == 6):
			# sanity check the files (file --mimetype)
			self.restore_source = self.wTree.get_widget("filechooserbutton_restore_source").get_filename()
			self.restore_dest = self.wTree.get_widget("filechooserbutton_restore_dest").get_filename()
			if(not self.restore_source or self.restore_source == ""):
				MessageDialog(_("Backup Tool"), _("Please choose a file to restore from"), gtk.MESSAGE_WARNING).show()
				return
			# test that file is indeed compressed.
			out = commands.getoutput("file \"" + self.restore_source + "\"")
			if("compressed" in out or "archive" in out):
				# valid archive, continue.
				self.wTree.get_widget("label_overview_source_value").set_label(self.restore_source)
				self.wTree.get_widget("label_overview_dest_value").set_label(self.restore_dest)
				thread = threading.Thread(group=None, target=self.prepare_restore, name="mintBackup-prepare", args=(), kwargs={})
				thread.start()
			else:
				MessageDialog(_("Backup Tool"), _("Please choose a valid archive file"), gtk.MESSAGE_WARNING).show()
		elif(sel == 7):
			# start restoring :D
			self.wTree.get_widget("button_forward").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			book.set_current_page(8)
			self.operating = True
			thread = threading.Thread(group=None, target=self.restore, name="mintBackup-restore", args=(), kwargs={})
			thread.start()
		elif(sel == 8):
			# show last page(restore finished status)
			self.wTree.get_widget("button_forward").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			book.set_current_page(9)
		elif(sel == 10):
			# check package dest
			self.package_dest = self.wTree.get_widget("entry_package_dest").get_text()
			if(os.path.exists(self.package_dest)):
				mbox = MessageDialog(_("Backup Tool"), _("Specified file already exists"), gtk.MESSAGE_ERROR)
				mbox.show()
				return
			self.wTree.get_widget("button_back").set_sensitive(False)
			self.wTree.get_widget("button_forward").set_sensitive(False)
			book.set_current_page(11)
			# times like this i realise people dont use threads.. someone's gonna hate me :D
			self.operating = True
			thr = threading.Thread(group=None, target=self.backup_packages, name="mintBackup-packages", args=(), kwargs={})
			thr.start()
		elif(sel == 11):
			# show last page (backup packages done)
			self.wTree.get_widget("button_forward").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			book.set_current_page(12)

	''' Back button '''
	def back_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
		if(sel == 7 and len(sys.argv) == 2):
			self.wTree.get_widget("button_back").set_sensitive(False)
		if(sel == 6 or sel == 10):
			book.set_current_page(0)
			self.wTree.get_widget("button_back").set_sensitive(False)
			self.wTree.get_widget("button_back").hide()
			self.wTree.get_widget("button_forward").hide()
			if(self.tar is not None):
				self.tar.close()
				self.tar = None
		else:
			sel = sel -1
			if(sel == 0):
				self.wTree.get_widget("button_back").hide()
				self.wTree.get_widget("button_forward").hide()
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
		pbar = self.wTree.get_widget("progressbar1")
		label = self.wTree.get_widget("label_current_file_value")
		os.chdir(self.backup_source)
		label.set_label(_("Calculating..."))
		pbar.set_text(_("Calculating..."))

		# get a count of all the files
		total = 0
		for top,dirs,files in os.walk(top=self.backup_source,onerror=None, followlinks=self.follow_links):
			pbar.pulse()
			for d in dirs:
				if(not self.operating):
					break
				if(not self.is_excluded(os.path.join(top, d))):
					total += 1
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
		try:
			if(comp[1] is not None):
				filetime = strftime("%Y-%m-%d-%H%M-backup", localtime())
				filename = os.path.join(self.backup_dest, filetime + comp[2])
				tar = tarfile.open(name=filename, dereference=self.follow_links, mode=comp[1], bufsize=1024)
				mintfile = os.path.join(self.backup_dest, ".mintbackup")
				tar.add(mintfile, arcname=".mintbackup", recursive=False, exclude=None)
				for top,dirs,files in os.walk(top=self.backup_source, onerror=None, followlinks=self.follow_links):
					if(not self.operating or self.error is not None):
						break
					for d in dirs:
						rpath = os.path.join(top, d)
						path = os.path.relpath(rpath)
						if(not self.is_excluded(rpath)):
							current_file = current_file + 1
							gtk.gdk.threads_enter()
							label.set_label(path)
							gtk.gdk.threads_leave()
							self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
							tar.add(rpath, arcname=path, recursive=False, exclude=None)
					for f in files:
						rpath = os.path.join(top, f)
						path = os.path.relpath(rpath)
						if(not self.is_excluded(rpath)):
							current_file = current_file + 1
							gtk.gdk.threads_enter()
							label.set_label(path)
							gtk.gdk.threads_leave()
							self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
							underfile = TarFileMonitor(rpath, self.update_backup_progress)
							finfo = tar.gettarinfo(name=None, arcname=path, fileobj=underfile)
							tar.addfile(fileobj=underfile, tarinfo=finfo)
							underfile.close()
				tar.close()
				os.remove(mintfile)
			else:
				# Copy to other directory, possibly on another device
				for top,dirs,files in os.walk(top=self.backup_source,onerror=None,followlinks=self.follow_links):
					if(not self.operating or self.error is not None):
						break
					for d in dirs:
						# make directories
						rpath = os.path.join(top, d)
						path = os.path.relpath(rpath)
						target = os.path.join(self.backup_dest, path)
						if(not os.path.exists(target)):
							os.mkdir(target)
							
						current_file = current_file + 1
						gtk.gdk.threads_enter()
						label.set_label(path)
						gtk.gdk.threads_leave()
						self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
					for f in files:
						rpath = os.path.join(top, f)
						path = os.path.relpath(rpath)
						if(not self.is_excluded(rpath)):
							target = os.path.join(self.backup_dest, path)								
							current_file = current_file + 1
							gtk.gdk.threads_enter()
							label.set_label(path)
							gtk.gdk.threads_leave()
							self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
							if(os.path.exists(target)):
								if(del_policy == 1):
									# source size > dest size
									file1 = os.path.getsize(rpath)
									file2 = os.path.getsize(target)
									if(file1 > file2):
										os.remove(target)
										self.copy_file(rpath, target)
									else:
										self.wTree.get_widget("progressbar1").set_text(_("Skipping identical file"))
								elif(del_policy == 2):
										# source size < dest size
									file1 = os.path.getsize(rpath)
									file2 = os.path.getsize(target)
									if(file1 < file2):
										os.remove(target)
										self.copy_file(rpath, target)
									else:
										self.wTree.get_widget("progressbar1").set_text(_("Skipping identical file"))
								elif(del_policy == 3):
									# source newer (less seconds from epoch)
									file1 = os.path.getmtime(rpath)
									file2 = os.path.getmtime(target)
									if(file1 < file2):
										os.remove(target)
										self.copy_file(rpath, target)
									else:
										self.wTree.get_widget("progressbar1").set_text(_("Skipping identical file"))
								elif(del_policy == 4):
									# checksums
									file1 = self.get_checksum(rpath)
									file2 = self.get_checksum(target)
									if(file1 not in file2):
										os.remove(target)
										self.copy_file(rpath, target)
									else:
										self.wTree.get_widget("progressbar1").set_text(_("Skipping identical file"))
								elif(del_policy == 5):
									# always delete
									os.remove(target)
									self.copy_file(rpath, target)
							else:
								self.copy_file(rpath, target)
		except Exception, detail:
			self.error = str(detail)
		if(self.error is not None):
			gtk.gdk.threads_enter()
			img = self.iconTheme.load_icon("dialog-error", 48, 0)
			self.wTree.get_widget("label_finished_status").set_markup(_("An error occured during backup:\n") + self.error)
			self.wTree.get_widget("image_finished").set_from_pixbuf(img)
			self.wTree.get_widget("notebook1").next_page()
			gtk.gdk.threads_leave()
		else:
			if(not self.operating):
				gtk.gdk.threads_enter()
				img = self.iconTheme.load_icon("dialog-warning", 48, 0)
				self.wTree.get_widget("label_finished_status").set_label(_("Backup was aborted"))
				self.wTree.get_widget("image_finished").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
			else:
				gtk.gdk.threads_enter()
				label.set_label("Done")
				img = self.iconTheme.load_icon("dialog-information", 48, 0)
				self.wTree.get_widget("label_finished_status").set_label(_("Backup completed without error"))
				self.wTree.get_widget("image_finished").set_from_pixbuf(img)
				self.wTree.get_widget("button_forward").set_sensitive(True)
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
		self.wTree.get_widget("progressbar1").set_fraction(fraction)
		if(message is not None):
			self.wTree.get_widget("progressbar1").set_text(message)
		else:
			self.wTree.get_widget("progressbar1").set_text(str(int(fraction *100)) + "%")

	''' Utility method - copy file, also provides a quick way of aborting a copy, which
	    using modules doesn't allow me to do.. '''
	def copy_file(self, source, dest):
		try:
			# represents max buffer size
			BUF_MAX = 1024 # so we don't get stuck on I/O ops
			errfile = None
			src = open(source, 'rb')
			total = os.path.getsize(source)
			current = 0
			dst = open(dest, 'wb')
			while True:
				if(not self.operating or self.error is not None):
					# Abort!
					errfile = dest
					break
				read = src.read(BUF_MAX)
				if(read):
					dst.write(read)
					current += len(read)
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
				if(self.preserve_times):
					finfo = os.stat(source)
					atime = finfo[stat.ST_ATIME]
					mtime = finfo[stat.ST_MTIME]
					os.utime(dest, (atime, mtime))
				if(self.preserve_perms):
					# set permissions
					finfo = os.stat(source)
					owner = finfo[stat.ST_UID]
					group = finfo[stat.ST_GID]
					os.fchown(fd, owner, group)
					dst.flush()
					os.fsync(fd)
					dst.close()
					shutil.copystat(source, dest)
				else:
					dst.flush()
					os.fsync(fd)
					dst.close()

				if(self.postcheck):
					file1 = self.get_checksum(source)
					file2 = self.get_checksum(dest)
					if(file1 not in file2):
						self.error = "Checksum Mismatch: [" + file1 + "] [" + file1 + "]"
		except OSError as bad:
			if(len(bad.args) > 2):
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
			else:
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
			
	
	''' Grab the checksum for the input filename and return it '''
	def get_checksum(self, source):
		MAX_BUF = 512
		current = 0
		try:
			check = hashlib.sha1()
			input = open(source, "rb")
			total = os.path.getsize(source)
			while True:
				if(not self.operating or self.error is not None):
					return None
				read = input.read(MAX_BUF)
				if(not read):
					break
				check.update(read)
				current += len(read)
				self.update_backup_progress(current, total, message="Calculating checksum")
			input.close()
			return check.hexdigest()
		except OSError as bad:
			if(len(bad.args) > 2):
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
			else:
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
		return None

	''' Grabs checksum for fileobj type object '''
	def get_checksum_for_file(self, source):
		MAX_BUF = 512
		current = 0
		total = source.size
		try:
			check = hashlib.sha1()
			while True:
				if(not self.operating or self.error is not None):
					return None
				read = source.read(MAX_BUF)
				if(not read):
					break
				check.update(read)
				current += len(read)
				self.update_restore_progress(current, total, message="Calculating checksum")
			source.close()
			return check.hexdigest()
		except Exception, detail:
			self.error = str(detail)
		return None
		
	''' Open the relevant archive manager '''
	def open_archive_callback(self, widget):
		# TODO: Add code to find out which archive manager is available
		# for non gnome environments
		os.system("file-roller \"" + self.restore_source + "\" &")

	''' Update the restore progress bar '''
	def update_restore_progress(self, current, total, message=None):
		current = float(current)
		total = float(total)
		fraction = float(current / total)
		self.wTree.get_widget("progressbar_restore").set_fraction(fraction)
		if(message is not None):
			self.wTree.get_widget("progressbar_restore").set_text(message)
		else:
			self.wTree.get_widget("progressbar_restore").set_text(str(int(fraction *100)) + "%")

	''' prepare the restore, reads the .mintbackup file if present '''
	def prepare_restore(self):
		# TODO: check what type of restore is happening
		if(self.tar is not None):
			self.wTree.get_widget("notebook1").set_current_page(7)
			return
		self.wTree.get_widget("main_window").set_sensitive(False)
		self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		self.conf = mINIFile()
		try:
			self.tar = tarfile.open(self.restore_source, "r")
			mintfile = self.tar.getmember(".mintbackup")
			if(mintfile is None):
				self.error = "File is not a valid mintBackup archive. Aborting"
				self.wTree.get_widget("button_forward").set_sensitive(False)
				self.tar.close()
				MessageDialog("Backup Tool", self.error, gtk.MESSAGE_ERROR).show()
			else:
				mfile = self.tar.extractfile(mintfile)
				self.conf.load_from_list(mfile.readlines())
				mfile.close()
				self.wTree.get_widget("label_overview_description_value").set_label(self.conf.description)
				self.wTree.get_widget("button_back").set_sensitive(True)
				self.wTree.get_widget("notebook1").set_current_page(7)

		except Exception, detail:
			print detail
		self.wTree.get_widget("main_window").set_sensitive(True)
		self.wTree.get_widget("main_window").window.set_cursor(None)
		
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
		del_policy = self.wTree.get_widget("combobox_restore_del").get_active()
		gtk.gdk.threads_enter()
		pbar = self.wTree.get_widget("progressbar_restore")
		pbar.set_text(_("Calculating..."))
		label = self.wTree.get_widget("label_restore_status_value")
		label.set_label(_("Calculating..."))
		gtk.gdk.threads_leave()

		# restore from archive
		self.error = None
		try:			
			sztotal = self.conf.file_count
			total = float(sztotal)
			current_file = 0
			MAX_BUF = 512
			for record in self.tar.getmembers():
				if(not self.operating or self.error is not None):
					break
				if(record.name == ".mintbackup"):
					# skip mintbackup file
					continue
				current_file = current_file + 1
				gtk.gdk.threads_enter()
				label.set_label(record.name)
				gtk.gdk.threads_leave()
				if(record.isdir()):
					target = os.path.join(self.restore_dest, record.name)
					self.wTree.get_widget("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
					if(not os.path.exists(target)):
						os.mkdir(target)

				if(record.isreg()):
					target = os.path.join(self.restore_dest, record.name)
					# todo: check existence of target and consult
					# overwrite rule
					self.wTree.get_widget("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
					if(os.path.exists(target)):
						if(del_policy == 1):
							# source size > dest size
							file1 = record.size
							file2 = os.path.getsize(target)
							if(file1 > file2):
								os.remove(target)
								gz = self.tar.extractfile(record)
								out = open(target, "wb")
								self.extract_file(gz, out, record)
							else:
								self.wTree.get_widget("progressbar_restore").set_text(_("Skipping identical file"))
						elif(del_policy == 2):
							# source size < dest size
							file1 = record.size
							file2 = os.path.getsize(target)
							if(file1 < file2):
								os.remove(target)
								gz = self.tar.extractfile(record)
								out = open(target, "wb")
								self.extract_file(gz, out, record)
							else:
								self.wTree.get_widget("progressbar_restore").set_text(_("Skipping identical file"))
						elif(del_policy == 3):
								# source newer (less seconds from epoch)
								file1 = record.mtime
								file2 = os.path.getmtime(target)
								if(file1 < file2):
									os.remove(target)
									gz = self.tar.extractfile(record)
									out = open(target, "wb")
									self.extract_file(gz, out, record)
								else:
									self.wTree.get_widget("progressbar_restore").set_text(_("Skipping identical file"))
						elif(del_policy == 4):
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
								self.wTree.get_widget("progressbar_restore").set_text(_("Skipping identical file"))
						elif(del_policy == 5):
							# always delete
							os.remove(target)
							gz = self.tar.extractfile(record)
							out = open(target, "wb")
							self.extract_file(gz, out, record)
					else:
						gz = self.tar.extractfile(record)
						out = open(target, "wb")
						self.extract_file(gz, out, record)

			self.tar.close()
		except Exception, detail:
			self.error = str(detail)

		if(self.error is not None):
			gtk.gdk.threads_enter()
			self.wTree.get_widget("label_restore_finished_value").set_label(_("An error occured during restoration:\n") + self.error)
			img = self.iconTheme.load_icon("dialog-error", 48, 0)
			self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
			self.wTree.get_widget("notebook1").next_page()
			gtk.gdk.threads_leave()
		else:
			if(not self.operating):
				img = self.iconTheme.load_icon("dialog-warning", 48, 0)
				self.wTree.get_widget("label_restore_finished_value").set_label(_("Restoration was aborted"))
				self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
			else:
				gtk.gdk.threads_enter()
				label.set_label("Done")
				pbar.set_text("Done")
				self.wTree.get_widget("label_restore_finished_value").set_label(_("The following archive was successfully restored:\n") + self.restore_source)
				img = self.iconTheme.load_icon("dialog-information", 48, 0)
				self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
				self.wTree.get_widget("button_forward").set_sensitive(True)
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
			p = subprocess.Popen("apt search ~M", shell=True, stdout=subprocess.PIPE)
			self.blacklist = []
			for l in p.stdout:
				l = l.rstrip("\r\n")
				l = l.split(" ")
				self.blacklist.append(l[2])
		except Exception, detail:
			print detail
		cache = apt.Cache()
		for pkg in cache:
			if(pkg.installed):
				if(self.is_manual_installed(pkg.name)):
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
			if(pkgname in b):
				return True
		return False
		
	''' toggled (update model)'''
	def toggled_cb(self, ren, path):
		treeview = self.wTree.get_widget("treeview_packages")
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
		pbar.set_text(_("Calculating..."))
		lab.set_label(_("Calculating..."))
		
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
			out = open(self.package_dest, "w")
			for row in model:
				if(not self.operating or self.error is not None):
					break
				if(row[0]):
					count += 1
					out.write(row[1] + "\n")
					gtk.gdk.threads_enter()
					pbar.set_text("%d / %d" % (count, total))
					pbar.set_fraction(float(count / total))
					lab.set_label(row[1])
					gtk.gdk.threads_leave()
			out.close()
		except Exception, detail:
			self.error = str(detail)
			
		if(self.error is not None):
			gtk.gdk.threads_enter()
			self.wTree.get_widget("label_packages_done_value").set_label(_("An error occured during backup:\n") + self.error)
			img = self.iconTheme.load_icon("dialog-error", 48, 0)
			self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
			self.wTree.get_widget("notebook1").next_page()
			gtk.gdk.threads_leave()
		else:
			if(not self.operating):
				img = self.iconTheme.load_icon("dialog-warning", 48, 0)
				self.wTree.get_widget("label_packages_done_value").set_label(_("Packages backup aborted"))
				self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
				self.wTree.get_widget("notebook1").next_page()
				gtk.gdk.threads_leave()
			else:
				gtk.gdk.threads_enter()
				lab.set_label("Done")
				pbar.set_text("Done")
				self.wTree.get_widget("label_packages_done_value").set_label(_("Your package list was succesfully backed up"))
				img = self.iconTheme.load_icon("dialog-information", 48, 0)
				self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
				self.wTree.get_widget("button_forward").set_sensitive(True)
				gtk.gdk.threads_leave()
		self.operating = False
		
if __name__ == "__main__":
	gtk.gdk.threads_init()
	MintBackup()
	gtk.main()
