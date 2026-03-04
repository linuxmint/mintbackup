import subprocess
import os
import json

class FlatpakHandler:

    def __init__(self, backup_dir):
        self.backup_dir = backup_dir
        self.file_path = os.path.join(self.backup_dir, "flatpaks.json")

    def backup(self):
        data = {
            "apps": [],
            "remotes": []
        }

        # Get remotes
        try:
            output = subprocess.check_output(
                ['flatpak', 'remotes', '--columns=name,url'],
                universal_newlines=True
            )
            for line in output.strip().split('\n'):
                if not line:
                    continue
                name, url = line.split('\t')
                data["remotes"].append({
                    "name": name,
                    "url": url
                })
        except Exception as e:
            print(f"Flatpak remote error: {e}")

        # Get apps
        try:
            output = subprocess.check_output(
                ['flatpak', 'list', '--app',
                 '--columns=application,origin,branch,arch,installation'],
                universal_newlines=True
            )

            for line in output.strip().split('\n'):
                if not line:
                    continue

                app_id, origin, branch, arch, installation = line.split('\t')

                data["apps"].append({
                    "app_id": app_id,
                    "origin": origin,
                    "branch": branch,
                    "arch": arch,
                    "installation": installation
                })

        except Exception as e:
            print(f"Flatpak list error: {e}")

        # Write to files

        os.makedirs(self.backup_dir, exist_ok=True)

        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=4)

    def restore(self):
        if not os.path.exists(self.file_path):
            return

        with open(self.file_path, "r") as file:
            data = json.load(file)

        # Restore remotes first
        for remote in data.get("remotes", []):
            subprocess.call([
                "flatpak", "remote-add",
                "--if-not-exists",
                remote["name"],
                remote["url"]
            ])

        # Restore apps
        for app in data.get("apps", []):
            cmd = [
                "flatpak", "install", "-y"
            ]

            # Use the same installation scope as in the backup
            installation = app.get("installation")
            if installation == "user":
                cmd.append("--user")
            elif installation == "system":
                cmd.append("--system")
            elif installation:
                # Named installation (as returned by flatpak list --columns=...,installation)
                cmd.append("--installation")
                cmd.append(installation)

            # If an architecture was recorded, pass it through to flatpak
            arch = app.get("arch")
            if arch:
                cmd.append(f"--arch={arch}")

            cmd.extend([
                app["origin"],
                f"{app['app_id']}//{app['branch']}"])

            subprocess.call(cmd)
