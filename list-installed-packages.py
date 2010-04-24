#!/usr/bin/python

import apt

cache = apt.Cache()
packages = sorted(cache.keys())
for package in packages:
	pkg = cache[package]
	if pkg.isInstalled:
		print package
