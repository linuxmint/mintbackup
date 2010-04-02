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

		# set up treeview
		ren = gtk.CellRendererText()
		column = gtk.TreeViewColumn("Excluded paths", ren)
		column.add_attribute(ren, "text", 0)
		self.wTree.get_widget("treeview1").append_column(column)
		self.wTree.get_widget("treeview1").set_model(gtk.ListStore(str))

		notebook = self.wTree.get_widget("notebook1")

		# nav buttons
		self.wTree.get_widget("button_back").connect("clicked", self.back_callback)
		self.wTree.get_widget("button_forward").connect("clicked", self.forward_callback)
		self.wTree.get_widget("button_cancel").connect("clicked", self.cancel_callback)

		self.wTree.get_widget("main_window").connect("destroy", gtk.main_quit)
		self.wTree.get_widget("main_window").set_title("Backup Tool")
		self.wTree.get_widget("main_window").show_all()

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

	''' Back button '''
	def back_callback(self, widget):
		self.wTree.get_widget("notebook1").prev_page()

if __name__ == "__main__":
	MintBackup()
	gtk.main()
