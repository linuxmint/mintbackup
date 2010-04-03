try:
	import pygtk
	pygtk.require("2.0")
except Exception, detail:
	print "You do not have a recent version of GTK"

try:
	import os
	import commands
	import gtk
	import gtk.glade
	import gettext
	import subprocess
	import threading
	import tarfile
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
		dialog.set_icon_from_file("/usr/lib/linuxmint/mintBackup/icon_desktop.png")
		dialog.set_title(_("Backup Tool"))
		dialog.set_position(gtk.WIN_POS_CENTER)
	        dialog.run()
	        dialog.destroy()

''' The main class of the app '''
class MintBackup:

	''' New MintBackup '''
	def __init__(self):
		self.glade = 'main_window.glade'
		self.wTree = gtk.glade.XML(self.glade, 'main_window')

		# inidicates whether an operation is taking place.
		self.operating = False

		# set up backup page 1 (source/dest/options)
		# Displayname, [tarfile mode, file extension]
		comps = gtk.ListStore(str,str,str)
		comps.append(["Do not archive", None, None])
		comps.append(["Archive with no compression", "w", ".tar"])
		comps.append(["Archive and compress with bzip2", "w:bz2", ".tar.bz2"])
		comps.append(["Archive and compress with gzip", "w:gz", "tar.gz"])
		self.wTree.get_widget("combobox_compress").set_model(comps)
		self.wTree.get_widget("combobox_compress").set_active(0)

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
		self.wTree.get_widget("main_window").set_title("Backup Tool")
		self.wTree.get_widget("main_window").show_all()

		# open archive button, opens an archive... :P
		self.wTree.get_widget("button_open_archive").connect("clicked", self.open_archive_callback)

	''' Exclude file '''
	def add_file_exclude(self, widget):
		model = self.wTree.get_widget("treeview_excludes").get_model()
		dialog = gtk.FileChooserDialog("Backup Tool", None, gtk.FILE_CHOOSER_ACTION_OPEN, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
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
		dialog = gtk.FileChooserDialog("Backup Tool", None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
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
		# TODO: Status-checking, confirmation
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
			book.set_current_page(2)
		# TODO: Support all pages..
		elif(sel == 2):
			# show overview
			model = gtk.ListStore(str, str)
			model.append(["<b>Source</b>", self.backup_source])
			model.append(["<b>Destination</b>", self.backup_dest])
			# find compression format
			sel = self.wTree.get_widget("combobox_compress").get_active()
			comp = self.wTree.get_widget("combobox_compress").get_model()
			model.append(["<b>Compression</b>", comp[sel][0]])
			excludes = self.wTree.get_widget("treeview_excludes").get_model()
			for row in excludes:
				model.append(["<b>Exclude</b>", row[2]])
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
				MessageDialog("Backup Tool", "Please choose a file to restore from", gtk.MESSAGE_WARNING).show()
				return
			# test that file is indeed compressed.
			out = commands.getoutput("file \"" + self.restore_source + "\"")
			if("compressed" in out or "archive" in out):
				# valid archive, continue.
				self.wTree.get_widget("label_overview_source_value").set_label(self.restore_source)
				self.wTree.get_widget("label_overview_dest_value").set_label(self.restore_dest)
				book.set_current_page(7)
			else:
				MessageDialog("Backup Tool", "Please choose a valid archive file", gtk.MESSAGE_WARNING).show()
		elif(sel == 7):
			# start restoring :D
			self.wTree.get_widget("button_forward").set_sensitive(False)
			self.wTree.get_widget("button_back").set_sensitive(False)
			book.set_current_page(8)
			self.operating = True
			thread = threading.Thread(group=None, target=self.restore, name="mintBackup-restore", args=(), kwargs={})
			thread.start()
	''' Back button '''
	def back_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
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
		# We should catch errors.. i.e. subprocess's stderr
		label.set_label("Calculating...")
		pbar.set_text("Calculating...")
		cmd = "find . 2>/dev/null"
	#	for row in self.wTree.get_widget("treeview_excludes"):
	#		cmd = cmd + " | grep -v \"" + row[2] + "\""
	#	cmd = cmd + " | wc -l"
	#	sztotal = commands.getoutput(cmd)

		# get a count of all the files
		tout = subprocess.Popen("find .", shell=True, bufsize=256, stdout=subprocess.PIPE)
		total = 0
		for c in tout.stdout:
			c = c.rstrip("\r\n")
			path = os.path.relpath(c)
			rpath = os.path.join(self.backup_source, path)
			if(not self.is_excluded(rpath)):
				total = total +1
		sztotal = str(total)
		total = float(total)

		current_file = 0

		# find out compression format, if any
		sel = self.wTree.get_widget("combobox_compress").get_active()
		comp = self.wTree.get_widget("combobox_compress").get_model()[sel]
		try:
			out = subprocess.Popen("find . 2>/dev/null", shell=True, bufsize=256, stdout=subprocess.PIPE)
			if(comp[1] is not None):
				# Use tar/gzip, may change to tar/bz2 in the future
				# TODO: Use more intuitive file name (i.e. timestamp)
				filename = os.path.join(self.backup_dest, "backup" + comp[2])
				tar = tarfile.open(filename, comp[1])
				for f in out.stdout:
					if(not self.operating):
						break
					f = f.rstrip("\r\n")
					path = os.path.relpath(f)
					rpath = os.path.join(self.backup_source, path)
					if(not self.is_excluded(rpath)):
						current_file = current_file + 1
						fraction = float(current_file / total)

						gtk.gdk.threads_enter()
						pbar.set_fraction(fraction)
						label.set_label(f)
						pbar.set_text("File " + str(current_file) + " of " + sztotal + " files")
						gtk.gdk.threads_leave()
	
						tar.add(f, arcname=None,recursive=False,exclude=None)
				tar.close()
			else:
				# Copy to other directory, possibly on another device
				for f in out.stdout:
					if(not self.operating):
						break

					f = f.rstrip("\r\n")
					path = os.path.relpath(f)
					rpath = os.path.join(self.backup_source, path)
					# Don't deal with excluded files..
					if(not self.is_excluded(rpath)):
						if(os.path.isdir(path)):
							os.system("mkdir " + self.backup_dest + "/" + path)
						else:
							os.system("cp " + f + " " + self.backup_dest + "/" + path)

						current_file = current_file + 1
						fraction = float(current_file / total)

						gtk.gdk.threads_enter()
						pbar.set_fraction(fraction)
						label.set_label(f)
						pbar.set_text("File " + str(current_file) + " of " + sztotal + " files")
						gtk.gdk.threads_leave()
		except Exception, detail:
			# Should alert user..
			print detail
			
		#TODO: Check for errors..
		if(not self.operating):
			gtk.gdk.threads_enter()
			img = self.iconTheme.load_icon("dialog-warning", 48, 0)
			self.wTree.get_widget("label_finished_status").set_label("Backup was aborted")
			self.wTree.get_widget("image_finished").set_from_pixbuf(img)
			self.wTree.get_widget("notebook1").next_page()
			gtk.gdk.threads_leave()
		else:
			gtk.gdk.threads_enter()
			label.set_label("Done")
			img = self.iconTheme.load_icon("dialog-information", 48, 0)
			self.wTree.get_widget("label_finished_status").set_label("Backup completed without error")
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


	''' Open the relevant archive manager '''
	def open_archive_callback(self, widget):
		# TODO: Add code to find out which archive manager is available
		# for non gnome environments
		os.system("file-roller \"" + self.restore_source + "\" &")

	''' Restore from archive '''
	def restore(self):
		pbar = self.wTree.get_widget("progressbar_restore")
		pbar.set_text("Calculating...")
		label = self.wTree.get_widget("label_restore_status_value")
		label.set_label("Calculating...")

		try:			
			tar = tarfile.open(self.restore_source, "r")
			members = tar.getmembers()
			sztotal = str(len(members))
			total = float(sztotal)
			current_file = 0
			for record in members:
				current_file = current_file + 1
				fraction = float(current_file / total)
				gtk.gdk.threads_enter()
				label.set_label(record.name)
				pbar.set_fraction(fraction)
				pbar.set_text("File " + str(current_file) + " of " + sztotal + " files")
				gtk.gdk.threads_leave()
				tar.extract(record, self.restore_dest)
			tar.close()
		except Exception, detail:
			# warn the user.
			print detail
			
		gtk.gdk.threads_enter()
		label.set_label("Done")
		pbar.set_text("Done")
		gtk.gdk.threads_leave()
if __name__ == "__main__":
	gtk.gdk.threads_init()
	MintBackup()
	gtk.main()
