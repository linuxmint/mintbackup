try:
	import pygtk
	pygtk.require("2.0")
except Exception, detail:
	print "You do not have a recent version of GTK"

try:
	import gtk
	import gtk.glade
	import gettext
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

		# set up exclusions page
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn("Excluded paths", ren)
		column.add_attribute(ren, "text", 0)
		self.wTree.get_widget("treeview_excludes").append_column(column)
		self.wTree.get_widget("treeview_excludes").set_model(gtk.ListStore(str))
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
					model.append([filename[len(self.backup_source)+1:]])
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
					model.append([filename[len(self.backup_source)+1:]])
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
		gtk.main_quit()

	''' Next button '''
	def forward_callback(self, widget):
		book = self.wTree.get_widget("notebook1")
		sel = book.get_current_page()
		# TODO: Check present page - disable buttons
		if(sel == 0):
			# start page
			if(self.wTree.get_widget("radiobutton_backup").get_active()):
				# go to backup wizard
				book.set_current_page(1)
			else:
				# TODO: Implement restore wizard..
				MessageDialog("Backup Tool", "Restoration mode not yet implemented", gtk.MESSAGE_ERROR).show()
				book.set_current_page(0)
		elif(sel == 1):
			# choose source/dest
			self.backup_source = self.wTree.get_widget("filechooserbutton_backup_source").get_filename()
			if(not self.backup_source or self.backup_source == ""):
				# moan
				MessageBox("Backup Tool", "Please select a valid backup source", gtk.MESSAGE_ERROR).show()
				book.set_current_page(1)
			else:
				book.set_current_page(2)
			self.backup_dest = self.wTree.get_widget("filechooserbutton_backup_dest").get_filename()
			if(not self.backup_dest or self.backup_dest == ""):
				# moan
				book.set_current_page(1)
			else:
				book.set_current_page(2)
		# TODO: Support all pages..
		elif(sel == 2):
			# show overview
			model = gtk.ListStore(str, str)
			model.append(["<b>Source</b>", self.backup_source])
			model.append(["<b>Destination</b>", self.backup_dest])
			excludes = self.wTree.get_widget("treeview_excludes").get_model()
			for row in excludes:
				model.append(["<b>Exclude</b>", row[0]])
			self.wTree.get_widget("treeview_overview").set_model(model)
			book.set_current_page(3)

	''' Back button '''
	def back_callback(self, widget):
		self.wTree.get_widget("notebook1").prev_page()

if __name__ == "__main__":
	MintBackup()
	gtk.main()
