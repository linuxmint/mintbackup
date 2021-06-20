# Mintbackup

The Backup Tool, mintbackup, makes it easy to save and restore backups of files within the home directory.

![](https://repository-images.githubusercontent.com/378609911/d3148800-d1c6-11eb-89f6-22b5e2d8e170)

## Build
Get source code
```
git clone https://github.com/linuxmint/mintbackup
cd mintbackup
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
