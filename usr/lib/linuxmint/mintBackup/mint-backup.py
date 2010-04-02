try:
	import pygtk
	pygtk.require("2.0")
except Exception, detail:
	print "You do not have a recent version of GTK"

try:
	import gtk
	import gtk.glade
except Exception, detail:
	print "You do not have the required dependancies"

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
		# TODO: Check present page - disable buttons
		self.wTree.get_widget("notebook1").next_page()

	''' Back button '''
	def back_callback(self, widget):
		self.wTree.get_widget("notebook1").prev_page()

if __name__ == "__main__":
	MintBackup()
	gtk.main()
