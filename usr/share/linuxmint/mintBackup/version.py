#!/usr/bin/env python

import apt
import sys

try:
	cache = apt.Cache()	
	pkg = cache["mintbackup"]
	print pkg.installed.version
except:
	pass


