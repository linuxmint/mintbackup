#!/usr/bin/python3

DOMAIN = "mintbackup"
PATH = "/usr/share/linuxmint/locale"

import os
import gettext
import sys
sys.path.append('/usr/lib/linuxmint/common')
import additionalfiles

os.environ['LANG'] = "en_US.UTF-8"
gettext.install(DOMAIN, PATH)

prefix = "[Desktop Entry]\n"

suffix = """Exec=mintbackup
Icon=/usr/lib/linuxmint/mintBackup/icon.svg
Terminal=false
Type=Application
Encoding=UTF-8
Categories=Application;System;Settings
NotShowIn=KDE;
"""

additionalfiles.generate(DOMAIN, PATH, "usr/share/applications/mintBackup.desktop", prefix, _("Backup Tool"), _("Make a backup of your home directory"), suffix)


prefix = "[Desktop Entry]\n"

suffix = """Exec=mintBackup
Icon=/usr/lib/linuxmint/mintBackup/icon.png
Terminal=false
Type=Application
Encoding=UTF-8
Categories=Application;System;Settings
NoDisplay=true
MimeType=application/x-backup;
"""

additionalfiles.generate(DOMAIN, PATH, "usr/share/applications/mintBackup_mime.desktop", prefix, _("Backup Tool"), _("Make a backup of your home directory"), suffix)


prefix = "[Desktop Entry]\n"

suffix = """Exec=mintBackup
Icon=/usr/lib/linuxmint/mintBackup/icon.png
Terminal=false
Type=Application
Encoding=UTF-8
Categories=Qt;KDE;System;
X-KDE-StartupNotify=false
OnlyShowIn=KDE;
"""

additionalfiles.generate(DOMAIN, PATH, "usr/share/applications/kde4/mintBackup.desktop", prefix, _("Backup Tool"), _("Make a backup of your home directory"), suffix, genericName=_("Make a backup of your home directory"))
