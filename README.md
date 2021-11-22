# Mintbackup

The Backup Tool, mintbackup, makes it easy to save and restore backups of files within the home directory.

![Mintbackup](https://user-images.githubusercontent.com/19881231/123512269-33a43900-d68f-11eb-8060-013d03489718.png)

## Build
Get source code
```
git clone https://github.com/linuxmint/mintbackup
cd mintbackup
```
Install dependencies
```
dpkg-checkbuilddeps
# Install these dependencies
```
Build
```
dpkg-buildpackage --no-sign
```
Install
```
cd ..
sudo dpkg -i mintbackup*.deb
```

## Translations
Please use Launchpad to translate Mintbackup: https://translations.launchpad.net/linuxmint/latest/.

The PO files in this project are imported from there.

## License
- Code: GPLv2
