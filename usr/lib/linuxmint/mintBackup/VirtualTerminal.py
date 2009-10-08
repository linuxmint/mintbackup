#!/usr/bin/env python
#
#      VirtualTerminal.py
#
#      Copyright 2007 Edward Andrew Robinson <earobinson@gmail>
#
#      This program is free software; you can redistribute it and/or modify
#      it under the terms of the GNU General Public License as published by
#      the Free Software Foundation; either version 2 of the License, or
#      (at your option) any later version.
#
#      This program is distributed in the hope that it will be useful,
#      but WITHOUT ANY WARRANTY; without even the implied warranty of
#      MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#      GNU General Public License for more details.
#
#      You should have received a copy of the GNU General Public License
#      along with this program; if not, write to the Free Software
#      Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#

# Imports
import os
import vte
import gtk

class VirtualTerminal(vte.Terminal):
    def __init__(self):
        # Set up terminal
        vte.Terminal.__init__(self)

        self.connect('eof', self.child_done)
        self.connect('child-exited', self.child_done)

        self.connect('char-size-changed', self.activate_action, 'char-size-changed')
        #self.connect('child-exited', self.activate_action, 'child-exited')
        self.connect('commit', self.activate_action, 'commit')
        self.connect('contents-changed', self.activate_action, 'contents-changed')
        self.connect('cursor-moved', self.activate_action, 'cursor-moved')
        self.connect('decrease-font-size', self.activate_action, 'decrease-font-size')
        self.connect('deiconify-window', self.activate_action, 'deiconify-window')
        self.connect('emulation-changed', self.activate_action, 'emulation-changed')
        self.connect('encoding-changed', self.activate_action, 'encoding-changed')
        #self.connect('eof', self.activate_action, 'eof')
        self.connect('icon-title-changed', self.activate_action, 'icon-title-changed')
        self.connect('iconify-window', self.activate_action, 'iconify-window')
        self.connect('increase-font-size', self.activate_action, 'increase-font-size')
        self.connect('lower-window', self.activate_action, 'lower-window')
        self.connect('maximize-window', self.activate_action, 'maximize-window')
        self.connect('move-window', self.activate_action, 'move-window')
        self.connect('raise-window', self.activate_action, 'raise-window')
        self.connect('refresh-window', self.activate_action, 'refresh-window')
        self.connect('resize-window', self.activate_action, 'resize-window')
        self.connect('restore-window', self.activate_action, 'restore-window')
        self.connect('selection-changed', self.activate_action, 'selection-changed')
        self.connect('status-line-changed', self.activate_action, 'status-line-changed')
        self.connect('text-deleted', self.activate_action, 'text-deleted')
        self.connect('text-inserted', self.activate_action, 'text-inserted')
        self.connect('text-modified', self.activate_action, 'text-modified')
        self.connect('text-scrolled', self.activate_action, 'text-scrolled')
        self.connect('window-title-changed', self.activate_action, 'window-title-changed')

    def activate_action(self, action, string, opt1=None, opt2=None):
        print 'Action ' + action.get_name() + ' activated ' + string

    def child_done(self, terminal):
        print 'child done'
        self.thread_running = False

    def run_command(self, command_string):
            #return
        self.thread_running = True
        spaces = ''
        for ii in range(80 - len(command_string) - 2):
            spaces = spaces + ' '
        self.feed('$ ' + str(command_string) + spaces)

        command = command_string.split(' ')
        pid =  self.fork_command(command=command[0], argv=command, directory=os.getcwd())

        while self.thread_running:
            #time.sleep(.01)
            gtk.main_iteration()
