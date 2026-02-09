# Backup and restore flatpaks on top of system packages

import subprocess
import os
import sys
import re
import tempfile
import shutil
import json

class FlatpakHandler:

    def __init__(self, backup_path):
        self.backup_path = backup_path
        self.flatpak_list = []
        self.flatpak_info = {}

    def get_flatpak_list(self):
        try:
            output = subprocess.check_output(['flatpak', 'list', '--app', '--columns=application'], universal_newlines=True)
            self.flatpak_list = output.strip().split('\n')
        except subprocess.CalledProcessError as e:
            print(f"Error getting flatpak list: {e}")
            self.flatpak_list = []

    def get_flatpak_info(self):
        for app in self.flatpak_list:
            try:
                output = subprocess.check_output(['flatpak', 'info', app, '--show-details', '--json'], universal_newlines=True)
                info = json.loads(output)
                self.flatpak_info[app] = info
            except subprocess.CalledProcessError as e:
                print(f"Error getting info for {app}: {e}")

    def backup_flatpaks(self):
        if not os.path.exists(self.backup_path):
            os.makedirs(self.backup_path)
        with open(os.path.join(self.backup_path, 'flatpaks.json'), 'w') as f:
            json.dump(self.flatpak_info, f, indent=4)

    def restore_flatpaks(self):
        flatpaks_file = os.path.join(self.backup_path, 'flatpaks.json')
        if not os.path.exists(flatpaks_file):
            print("No flatpaks backup found.")
            return
        with open(flatpaks_file, 'r') as f:
            flatpak_info = json.load(f)
        for app, info in flatpak_info.items():
            try:
                subprocess.check_call(['flatpak', 'install', '-y', info['ref']])
            except subprocess.CalledProcessError as e:
                print(f"Error restoring {app}: {e}")