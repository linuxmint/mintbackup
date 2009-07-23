#!/usr/bin/env python

# mintBackup (Clement Lefebvre root@linuxmint.com)
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; Version 2
# of the License.
#


import sys

try:
     import pygtk
     pygtk.require("2.0")
except:
      pass
try:
    import gtk
    import gtk.glade
    import os
    import commands
    import threading
    import datetime
    import gettext
    from user import home
except:
    print "You do not have all the dependencies!"
    sys.exit(1)

gtk.gdk.threads_init()
from subprocess import Popen, PIPE


architecture = commands.getoutput("uname -a")
if (architecture.find("x86_64") >= 0):
	import ctypes
	libc = ctypes.CDLL('libc.so.6')
	libc.prctl(15, 'mintBackup', 0, 0, 0)	
else:
	import dl
	libc = dl.open('/lib/libc.so.6')
	libc.call('prctl', 15, 'mintBackup', 0, 0, 0)

# i18n
gettext.install("messages", "/usr/lib/linuxmint/mintBackup/locale")

class PerformBackup(threading.Thread):

	def __init__(self, wTree):
		threading.Thread.__init__(self)		
		self.wTree = wTree		
		timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
		self.filename = "home_" + timestamp
		os.chdir(home)

	def run(self):
		try:			
			#Tell the GUI we're busy
			gtk.gdk.threads_enter()
			self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))		
			self.wTree.get_widget("main_window").set_sensitive(False)
			self.statusbar = self.wTree.get_widget("statusbar")
			self.context_id = self.statusbar.get_context_id("mintBackup")
			self.statusbar.push(self.context_id, _("Archiving your home directory..."))
			gtk.gdk.threads_leave()
	
			#Perform the backup			
			model = self.wTree.get_widget("treeview").get_model()		
			treeiter = model.get_iter_first()
			excludeList = ""
			while (treeiter != None):
				exclude = model.get_value(treeiter, 0)
				#tar doesn't like absolute paths (I know.. tell me about it..) so we need a dirty hack here.
				exclude = exclude[len(home)+1:]
				if (exclude.find(" ")):
					exclude = "'" + exclude + "'"
				excludeList = excludeList + " --exclude=" + exclude
				treeiter = model.iter_next(treeiter)

			hiddenmodel = self.wTree.get_widget("treeview_hidden").get_model()		
			hiddentreeiter = hiddenmodel.get_iter_first()
			hiddenList = ""
			while (hiddentreeiter != None):
				selected = hiddenmodel.get_value(hiddentreeiter, 0)
				hidden = hiddenmodel.get_value(hiddentreeiter, 1)
				if (selected == "true"):
					hiddenList = hiddenList + " " + hidden
				hiddentreeiter = hiddenmodel.iter_next(hiddentreeiter)
			retval = os.system("tar cvWf " + self.filename + ".backup" + excludeList + " *" + hiddenList )
			if (retval != 0):
				raise Exception("tar cvWf " + self.filename + ".backup" + excludeList + " *" + hiddenList + " --> " + str(retval))

			gtk.gdk.threads_enter()
			message = MessageDialog(_("Backup successful"), _("Your home directory was successfully backed-up into") + " " + self.filename + ".backup", gtk.MESSAGE_INFO)
	    		message.show()	
			gtk.gdk.threads_leave()

			#Tell the GUI we're back
			gtk.gdk.threads_enter()
			self.wTree.get_widget("main_window").window.set_cursor(None)		
			self.wTree.get_widget("main_window").set_sensitive(True)
			self.statusbar.push(self.context_id, "")
			gtk.gdk.threads_leave()

			gtk.main_quit()

		except Exception, detail:			
			gtk.gdk.threads_enter()
			message = MessageDialog(_("Backup failed"), _("An error occurred during the backup:") + " " + str(detail), gtk.MESSAGE_ERROR)
	    		message.show()			
			gtk.gdk.threads_leave()	
			gtk.main_quit()

class PerformRestore(threading.Thread):

	def __init__(self, wTree):
		threading.Thread.__init__(self)		
		self.wTree = wTree
		self.overwrite_checkbox = self.wTree.get_widget("overwrite_checkbox").get_active()			

	def run(self):
		try:			
			#Tell the GUI we're busy
			gtk.gdk.threads_enter()
			self.wTree.get_widget("restore_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))		
			self.wTree.get_widget("restore_window").set_sensitive(False)
			self.statusbar = self.wTree.get_widget("statusbar_restore")
			self.context_id = self.statusbar.get_context_id("mintBackup")
			self.statusbar.push(self.context_id, _("Copying the backup file into your home directory..."))
			gtk.gdk.threads_leave()
	
			user_name = os.environ.get('USER')
			retval = os.system("mv /tmp/" + user_name + "/mintBackup/backup.tar " + home + "/")
			if (retval != 0):
				raise Exception("mv /tmp/" + user_name + "/mintBackup/backup.tar " + home + "/" + " --> " + str(retval))
			os.chdir(home)

			#Tell the GUI we're moving on to the next thing.. 
			gtk.gdk.threads_enter()
			self.statusbar.push(self.context_id, _("Extracting the content of the backup into your home directory..."))
			gtk.gdk.threads_leave()
	
			if (self.overwrite_checkbox == True):
				retval = os.system("tar xvf backup.tar")
				if (retval != 0):
					raise Exception("tar xvf backup.tar" + " --> " + str(retval))
			else:
				retval = os.system("tar kxvf backup.tar")
				if (retval != 0):
					raise Exception("tar kxvf backup.tar" + " --> " + str(retval))
			
			os.system("chown -R " + user_name + ":" + user_name + " " + home)
			
			#Tell the GUI we're moving on to the next thing.. 
			gtk.gdk.threads_enter()
			self.statusbar.push(self.context_id, _("Cleaning up..."))
			gtk.gdk.threads_leave()
		
			os.system("rm -f backup.tar")

			gtk.gdk.threads_enter()
			message = MessageDialog(_("Restoration successful"), _("Your backup was successfully restored"), gtk.MESSAGE_INFO)
	    		message.show()	
			gtk.gdk.threads_leave()

			#Tell the GUI we're back
			gtk.gdk.threads_enter()
			self.wTree.get_widget("restore_window").window.set_cursor(None)		
			self.wTree.get_widget("restore_window").set_sensitive(True)
			self.statusbar.push(self.context_id, "")
			gtk.gdk.threads_leave()

			gtk.main_quit()

		except Exception, detail:
			os.system("rm -f backup.tar")
			gtk.gdk.threads_enter()
			message = MessageDialog(_("Restoration failed"), _("An error occurred while restoring the backup archive:") + " " + str(detail), gtk.MESSAGE_ERROR)
	    		message.show()	
			gtk.gdk.threads_leave()	
			gtk.main_quit()

class performBeforeRestore(threading.Thread):

	def __init__(self, wTree, filename):
		threading.Thread.__init__(self)		
		self.wTree = wTree	
		self.filename = filename			

	def run(self):
		try:			
			#Tell the GUI we're busy
			gtk.gdk.threads_enter()
			self.wTree.get_widget("restore_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))		
			self.wTree.get_widget("restore_window").set_sensitive(False)
			self.statusbar = self.wTree.get_widget("statusbar_restore")
			self.context_id = self.statusbar.get_context_id("mintBackup")
			self.statusbar.push(self.context_id, _("Opening the backup archive..."))
			gtk.gdk.threads_leave()
			
			user_name = os.environ.get('USER')
			os.system("mkdir -p /tmp/" + user_name + "/mintBackup")
			os.system("rm -rf /tmp/" + user_name + "/mintBackup/*")

			retval = os.system("cp " + self.filename + " /tmp/" + user_name + "/mintBackup/backup.tar")
			if (retval != 0):
				raise Exception("cp " + self.filename + " /tmp/" + user_name + "/mintBackup/backup.tar" + " --> " + str(retval))		

			os.chdir("/tmp/" + user_name + "/mintBackup/")
		
			retval = os.system("tar xvf backup.tar")
			if (retval != 0):
				raise Exception("tar xvf backup.tar" + " --> " + str(retval))		
				
			#Tell the GUI we're back
			gtk.gdk.threads_enter()
			self.wTree.get_widget("restore_window").window.set_cursor(None)		
			self.wTree.get_widget("restore_window").set_sensitive(True)
			self.statusbar.push(self.context_id, "")
			gtk.gdk.threads_leave()

		except Exception, detail:		
			gtk.gdk.threads_enter()			
			message = MessageDialog(_("Read error"), _("An error occurred while opening the backup:") + " " + str(detail), gtk.MESSAGE_ERROR)
	    		message.show()	
			gtk.gdk.threads_leave()	
			gtk.main_quit()

class MessageDialog:
	def __init__(self, title, message, style):
		self.title = title
		self.message = message
		self.style = style

	def show(self):
		
		dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, self.style, gtk.BUTTONS_OK, self.message)
		dialog.set_icon_from_file("/usr/lib/linuxmint/mintBackup/icon.png")
		dialog.set_title("mintBackup")
		dialog.set_position(gtk.WIN_POS_CENTER)
	        dialog.run()
	        dialog.destroy()		

class mintBackupWindow:
    """This is the main class for the application"""

    def __init__(self):
	#Set the Glade file
        self.gladefile = "/usr/lib/linuxmint/mintBackup/mintBackup.glade"
        self.wTree = gtk.glade.XML(self.gladefile,"main_window")
	self.wTree.get_widget("main_window").connect("destroy", gtk.main_quit)
	self.wTree.get_widget("cancel_button").connect("clicked", gtk.main_quit)
	self.wTree.get_widget("apply_button").connect("clicked", self.performBackup)
	self.wTree.get_widget("add_file_button").connect("clicked", self.addFileExclude)
	self.wTree.get_widget("add_folder_button").connect("clicked", self.addFolderExclude)
	self.wTree.get_widget("remove_button").connect("clicked", self.removeExclude)

	#i18n
	self.wTree.get_widget("label4").set_text(_("Excluded paths"))
	self.wTree.get_widget("label5").set_text(_("Hidden paths"))
	self.wTree.get_widget("label1").set_text(_("Exclude files"))
	self.wTree.get_widget("label3").set_text(_("Exclude folders"))
	self.wTree.get_widget("label2").set_text(_("Backup"))

	self.tree = self.wTree.get_widget("treeview")
	self.column = gtk.TreeViewColumn(_("Excluded Files and Directories"))
        self.tree.append_column(self.column)
        self.renderer = gtk.CellRendererText()
        self.column.pack_start(self.renderer, True)
        self.column.add_attribute(self.renderer, 'text', 0)
        self.tree.set_search_column(0)
        self.column.set_sort_column_id(0)
        self.tree.set_reorderable(True)

	self.model = gtk.ListStore(str)
	
	self.tree.set_model(self.model)

	self.tree.get_selection().set_mode(gtk.SELECTION_MULTIPLE)

	self.tree.show()

	self.hiddentree = self.wTree.get_widget("treeview_hidden")
	self.cr = gtk.CellRendererToggle()
	self.cr.connect("toggled", self.toggled, self.hiddentree)
	self.column1 = gtk.TreeViewColumn(_("Included"), self.cr)
	self.column1.set_cell_data_func(self.cr, self.celldatafunction_checkbox)
	self.column1.set_sort_column_id(0)
	self.hiddentree.append_column(self.column1)
	self.hiddencolumn = gtk.TreeViewColumn(_("Included hidden directories"))
        self.hiddentree.append_column(self.hiddencolumn)
        self.hiddenrenderer = gtk.CellRendererText()
        self.hiddencolumn.pack_start(self.hiddenrenderer, True)
        self.hiddencolumn.add_attribute(self.hiddenrenderer, 'text', 1)
        self.hiddentree.set_search_column(1)
        self.hiddencolumn.set_sort_column_id(1)
        self.hiddentree.set_reorderable(True)
	self.hiddenmodel = gtk.ListStore(str, str)
	self.hiddentree.set_model(self.hiddenmodel)
	self.hiddentree.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
	self.hiddentree.show()

	os.chdir(home)
	directories = os.listdir(home)
	for directory in directories:
		directories.sort()
		if directory[0] == ".":
			self.hiddenmodel.append(["false", directory])

	#If Network is there, exclude it
	if (os.path.exists(home + "/Network")):
		self.model.append([home + "/Network"])


    def celldatafunction_checkbox(self, column, cell, model, iter):
        cell.set_property("activatable", True)
	checked = model.get_value(iter, 0)
	if (checked == "true"):
		cell.set_property("active", True)
	else:
		cell.set_property("active", False)

    def toggled(self, renderer, path, treeview):
    	model = treeview.get_model()
    	iter = model.get_iter(path)
    	if (iter != None):
	    checked = model.get_value(iter, 0)
	    if (checked == "true"):
		model.set_value(iter, 0, "false")
	    else:
		model.set_value(iter, 0, "true")


    def addFileExclude(self, widget):
	dialog = gtk.FileChooserDialog("mintBackup", None, gtk.FILE_CHOOSER_ACTION_OPEN, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
	dialog.set_current_folder(home)
	dialog.set_select_multiple(True)
	if dialog.run() == gtk.RESPONSE_OK:
		filenames = dialog.get_filenames()
		for filename in filenames:					
			self.model.append([filename])
	dialog.destroy()

    def addFolderExclude(self, widget):
	dialog = gtk.FileChooserDialog("mintBackup", None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
	dialog.set_current_folder(home)
	dialog.set_select_multiple(True)
	if dialog.run() == gtk.RESPONSE_OK:
		filenames = dialog.get_filenames()					
		for filename in filenames:
			if (not filename.find(home)):
				self.model.append([filename])
			else:
				message = MessageDialog(_("Invalid path"), filename + " " + _("is not located within your home directory. Not added."), gtk.MESSAGE_WARNING)
	    			message.show()
	dialog.destroy()

    def removeExclude(self, widget):
	selection = self.tree.get_selection()
	selected_rows = selection.get_selected_rows()[1]
	# don't you just hate python? :) Here's another hack for python not to get confused with its own paths while we're deleting multiple stuff. 
	# actually.. gtk is probably to blame here. 
	args = [(self.model.get_iter(path)) for path in selected_rows] 
	for iter in args:
            self.model.remove(iter)

    def performBackup(self, widget):
	backup = PerformBackup(self.wTree)
	backup.start()	

class mintRestoreWindow:

    def __init__(self, filename):
	self.filename = filename

	#Set the Glade file
        self.gladefile = "/usr/lib/linuxmint/mintBackup/mintBackup.glade"
        self.wTree = gtk.glade.XML(self.gladefile,"restore_window")
	self.wTree.get_widget("restore_window").connect("destroy", gtk.main_quit)
	self.wTree.get_widget("cancel_button2").connect("clicked", gtk.main_quit)
	self.wTree.get_widget("restore_button").connect("clicked", self.performRestore)
	self.wTree.get_widget("view_content_button").connect("clicked", self.viewContent)

	#i18n
	self.wTree.get_widget("txt_name2").set_text(_("<big><b>Load data into your home directory</b></big>"))
	self.wTree.get_widget("txt_name2").set_use_markup(True)
	self.wTree.get_widget("txt_guidance2").set_text(_("Restore your personal data from this backup"))
	self.wTree.get_widget("overwrite_checkbox").set_label(_("Overwrite existing files"))
	self.wTree.get_widget("label15").set_text(_("Restore"))
	self.wTree.get_widget("label12").set_text(_("View content"))

	beforeRestore = performBeforeRestore(self.wTree, self.filename)
	beforeRestore.start()

    def performRestore(self, widget):
	restore = PerformRestore(self.wTree)
	restore.start()	

    def viewContent(self, widget):
	user_name = os.environ.get('USER')
	os.system("file-roller /tmp/" + user_name + "/mintBackup/backup.tar &")
	
if __name__ == "__main__":
	if (len(sys.argv) != 2):
    		mainwin = mintBackupWindow()
    		gtk.main()
    	else:
		mainwin = mintRestoreWindow(sys.argv[1])
		gtk.main()

