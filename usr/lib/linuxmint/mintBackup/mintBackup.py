#!/usr/bin/env python

# mintBackup - A GUI backup and restoration utility
# Author: Ikey Doherty <contactjfreak@googlemail.com>
# Several parts of this program originate from the original
# mintDesktop code by Clement Lefebvre <root@linuxmint.com>
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
	from time import strftime, gmtime, sleep
except Exception, detail:
	print "You do not have the required dependancies"

# i18n
gettext.install("messages", "/usr/lib/linuxmint/mintBackup/locale")

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

		# maximum jobs
		# TODO: Make this adjustable via the GUI
		self.MAX_JOBS = 10
		# blocking semaphore (thread safety)
		self.blocker = threading.Semaphore(value=self.MAX_JOBS)
		# count of present threads (limiter)
		self.tcount = 0
		# error?
		self.error = None
		
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

		self.wTree.get_widget("main_window").connect("destroy", gtk.main_quit)
		self.wTree.get_widget("main_window").set_title(_("Backup Tool"))
		self.wTree.get_widget("main_window").show_all()

		# open archive button, opens an archive... :P
		self.wTree.get_widget("button_open_archive").connect("clicked", self.open_archive_callback)

		# i18n - Page 0 (choose backup or restore)
		self.wTree.get_widget("label_wizard").set_markup(_("<big><b>Backup Tool</b></big>\nThis wizard will allow you to make a backup, or to\nrestore a previously created backup"))
		self.wTree.get_widget("radiobutton_backup").set_label(_("Create a new backup"))
		self.wTree.get_widget("radiobutton_restore").set_label(_("Restore an existing backup"))

		# i18n - Page 1 (choose backup directories)
		self.wTree.get_widget("label_backup_dirs").set_markup(_("<big><b>Backup Tool</b></big>\nYou now need to choose the source and destination\ndirectories for the backup"))
		self.wTree.get_widget("label_backup_source").set_label(_("Source:"))
		self.wTree.get_widget("label_backup_dest").set_label(_("Destination:"))
		self.wTree.get_widget("label_expander").set_label(_("Advanced options"))
		self.wTree.get_widget("label_compress").set_label(_("Output:"))
		self.wTree.get_widget("label_overwrite_dest").set_label(_("Overwrite:"))

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

		# i18n - Page 7 (Restore overview)
		self.wTree.get_widget("label_restore_overview").set_markup(_("<big><b>Backup Tool</b></big>\nWhen you are happy with the settings below\npress the Forward button to restore your backup"))
		self.wTree.get_widget("label_overview_source").set_markup(_("<b>Archive</b>"))
		self.wTree.get_widget("label_open_archive").set_label(_("Open"))

		# i18n - Page 8 (restore status)
		self.wTree.get_widget("label_restore_progress").set_markup(_("<big><b>Backup Tool</b></big>\nNow restoring your backup, this may take\nsome time so please be patient"))
		self.wTree.get_widget("label_restore_status").set_label(_("Current file:"))

		# i18n - Page 9 (restore complete)
		self.wTree.get_widget("label_restore_finished").set_markup(_("<big><b>Backup Tool</b></big>"))

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
		if(self.operating):
			# in the middle of a job, let the appropriate thread
			# handle the cancel
			self.operating = False
		else:
			# just quit :)
			gtk.main_quit()

	''' Next button '''
	def forward_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
		self.wTree.get_widget("button_back").set_sensitive(True)
		if(sel == 0):
			# start page
			if(self.wTree.get_widget("radiobutton_backup").get_active()):
				# go to backup wizard
				book.set_current_page(1)
			else:
				book.set_current_page(6)
		elif(sel == 1):
			# choose source/dest
			self.backup_source = self.wTree.get_widget("filechooserbutton_backup_source").get_filename()
			self.backup_dest = self.wTree.get_widget("filechooserbutton_backup_dest").get_filename()
			if(self.backup_source == self.backup_dest):
				MessageDialog(_("Backup Tool"), _("Your source and destination directories cannot be the same"), gtk.MESSAGE_WARNING).show()
				return
			book.set_current_page(2)
		elif(sel == 2):
			# show overview
			model = gtk.ListStore(str, str)
			model.append([_("<b>Source</b>"), self.backup_source])
			model.append([_("<b>Destination</b>"), self.backup_dest])
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
				book.set_current_page(7)
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

	''' Back button '''
	def back_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
		if(sel == 7 and len(sys.argv) == 2):
			self.wTree.get_widget("button_back").set_sensitive(False)
		if(sel == 6):
			book.set_current_page(0)
			self.wTree.get_widget("button_back").set_sensitive(False)
		else:
			sel = sel -1
			if(sel == 0):
				self.wTree.get_widget("button_back").set_sensitive(False)
			book.set_current_page(sel)

	''' Does the actual copying '''
	def backup(self):
		pbar = self.wTree.get_widget("progressbar1")
		label = self.wTree.get_widget("label_current_file_value")
		os.chdir(self.backup_source)
		label.set_label(_("Calculating..."))
		pbar.set_text(_("Calculating..."))

		# get a count of all the files
		total = 0
		for top,dirs,files in os.walk(self.backup_source):
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
		total = float(total)

		current_file = 0

		# deletion policy
		del_policy = self.wTree.get_widget("combobox_delete_dest").get_active()

		# find out compression format, if any
		sel = self.wTree.get_widget("combobox_compress").get_active()
		comp = self.wTree.get_widget("combobox_compress").get_model()[sel]
		try:
			if(comp[1] is not None):
				filetime = strftime("%Y-%m-%d-%H%M-backup", gmtime())
				filename = os.path.join(self.backup_dest, filetime + comp[2])
				tar = tarfile.open(filename, comp[1])
				for top,dirs,files in os.walk(self.backup_source):
					if(not self.operating or self.error is not None):
						break
					for d in dirs:
						rpath = os.path.join(top, d)
						path = os.path.relpath(rpath)
						if(not self.is_excluded(rpath)):
							current_file = current_file + 1
							fraction = float(current_file / total)
							gtk.gdk.threads_enter()
							pbar.set_fraction(fraction)
							label.set_label(path)
							pbar.set_text(str(current_file) + " / " + sztotal)
							gtk.gdk.threads_leave()
							# TODO: Read manually and add to tar
							tar.add(rpath, arcname=path, recursive=False, exclude=None)
					for f in files:
						rpath = os.path.join(top, f)
						path = os.path.relpath(rpath)
						if(not self.is_excluded(rpath)):
							current_file = current_file + 1
							fraction = float(current_file / total)
							gtk.gdk.threads_enter()
							pbar.set_fraction(fraction)
							label.set_label(path)
							pbar.set_text(str(current_file) + " / " +sztotal)
							gtk.gdk.threads_leave()
							tar.add(rpath, arcname=path, recursive=False, exclude=None)
				tar.close()
			else:
				# Copy to other directory, possibly on another device
				for top,dirs,files in os.walk(self.backup_source):
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
						fraction = float(current_file / total)
						gtk.gdk.threads_enter()
						pbar.set_fraction(fraction)
						label.set_label(path)
						pbar.set_text(str(current_file) + " / " + sztotal)
						gtk.gdk.threads_leave()
					
					for f in files:
						rpath = os.path.join(top, f)
						path = os.path.relpath(rpath)
						if(not self.is_excluded(rpath)):
							target = os.path.join(self.backup_dest, path)
							if(os.path.exists(target)):
								if(del_policy == 1):
									# source size > dest size
									file1 = os.path.getsize(rpath)
									file2 = os.path.getsize(target)
									if(file1 > file2):
										os.remove(target)
										self.t_copy_file(rpath, target)
								elif(del_policy == 2):
										# source size < dest size
									file1 = os.path.getsize(rpath)
									file2 = os.path.getsize(target)
									if(file1 < file2):
										os.remove(target)
										self.t_copy_file(rpath, target)
								elif(del_policy == 3):
									# source newer (less seconds from epoch)
									file1 = os.path.getmtime(rpath)
									file2 = os.path.getmtime(target)
									if(file1 < file2):
										os.remove(target)
										self.t_copy_file(rpath, target)
								elif(del_policy == 4):
									# checksums
									file1 = self.get_checksum(rpath)
									file2 = self.get_checksum(target)
									if(file1 not in file2):
										os.remove(target)
										self.t_copy_file(rpath, target)
								elif(del_policy == 5):
									# always delete
									os.remove(target)
									self.t_copy_file(rpath, target)
							else:
								self.t_copy_file(rpath, target)
								
						current_file = current_file + 1
						fraction = float(current_file / total)
						gtk.gdk.threads_enter()
						pbar.set_fraction(fraction)
						label.set_label(path)
						pbar.set_text(str(current_file) + " / " + sztotal)
						gtk.gdk.threads_leave()
						
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

	''' Utility method - copy file, also provides a quick way of aborting a copy, which
	    using modules doesn't allow me to do.. '''
	def copy_file(self, source, dest):
		try:
			# represents max buffer size
			BUF_MAX = 512 # so we don't get stuck on I/O ops
			errfile = None
			# We don't handle the errors :)
			# They will be handed by the backup thread appropriately
			finfo = os.stat(source)
			owner = finfo[stat.ST_UID]
			group = finfo[stat.ST_GID]
			src = open(source, 'rb')
			dst = open(dest, 'wb')
			while True:
				if(not self.operating or self.error is not None):
					# Abort!
					errfile = dest
					break
				read = src.read(BUF_MAX)
				if(read):
					dst.write(read)
				else:
					break
			src.close()
			if(errfile):
				# Remove aborted file (avoid corruption)
				dst.close()
				os.remove(errfile)
			else:
				# set permissions
				fd = dst.fileno()
				os.fchown(fd, owner, group)
				dst.flush()
				os.fsync(fd)
				dst.close()
				shutil.copystat(source, dest)
		except OSError as bad:
			if(len(bad.args) > 2):
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
			else:
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
		finally:
			self.tcount -= 1
			
	''' "Thread managed" copy... '''
	def t_copy_file(self, source, destination):
		try:
			self.blocker.acquire()
			while self.tcount >= self.MAX_JOBS:
				sleep(0.1)
			thread = threading.Thread(group=None, target=self.copy_file, name="mintBackup-copy", args=(source, destination), kwargs={})
			thread.start()
			self.tcount += 1
			self.blocker.release()
		except Exception, detail:
			self.error = str(detail)
			
	''' Grab the checksum for the input file and return it '''
	def get_checksum(self, source):
		MAX_BUF = 512
		try:
			check = hashlib.sha1()
			input = open(source, "rb")
			while True:
				if(not self.operating or self.error is not None):
					return None
				read = input.read(MAX_BUF)
				if(not read):
					break
				check.update(read)
			input.close()
			return check.hexdigest()
		except OSError as bad:
			if(len(bad.args) > 2):
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
			else:
				self.error = "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
		return None
		
	''' Open the relevant archive manager '''
	def open_archive_callback(self, widget):
		# TODO: Add code to find out which archive manager is available
		# for non gnome environments
		os.system("file-roller \"" + self.restore_source + "\" &")

	''' Restore from archive '''
	def restore(self):
		gtk.gdk.threads_enter()
		pbar = self.wTree.get_widget("progressbar_restore")
		pbar.set_text(_("Calculating..."))
		label = self.wTree.get_widget("label_restore_status_value")
		label.set_label(_("Calculating..."))
		gtk.gdk.threads_leave()

		self.error = None
		try:			
			tar = tarfile.open(self.restore_source, "r")
			members = tar.getmembers()
			sztotal = str(len(members))
			total = float(sztotal)
			current_file = 0
			MAX_BUF = 512
			for record in members:
				if(not self.operating):
					break
				current_file = current_file + 1
				fraction = float(current_file / total)
				gtk.gdk.threads_enter()
				label.set_label(record.name)
				pbar.set_fraction(fraction)
				pbar.set_text(str(current_file) + " / " + sztotal)
				gtk.gdk.threads_leave()
				#tar.extract(record, self.restore_dest)
				if(record.isdir()):
					target = os.path.join(self.restore_dest, record.name)
					if(not os.path.exists(target)):
						os.mkdir(target)
				if(record.isreg()):
					target = os.path.join(self.restore_dest, record.name)
					# todo: check existence of target and consult
					# overwrite rule
					gz = tar.extractfile(record)
					out = open(target, "wb")
					errflag = None
					while True:
						if(not self.operating):
							errflag = True
							break
						read = gz.read(MAX_BUF)
						if(not read):
							break
						out.write(read)
					gz.close()
					if(errflag):
						out.close()
						os.remove(target)
					else:
						# set permissions
						fd = out.fileno()
						os.fchown(fd, record.uid, record.gid)
						os.fchmod(fd, record.mode)
						out.flush()
						os.fsync(fd)
						out.close()
						os.utime(target, (record.mtime, record.mtime))
			tar.close()
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
if __name__ == "__main__":
	gtk.gdk.threads_init()
	MintBackup()
	gtk.main()
