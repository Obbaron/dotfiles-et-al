#!/usr/bin/env python3
# configure.py - invoked by bootstrap.sh
import os
import sys
import shutil

if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
    sys.exit("configure.py is invoked by bootstrap.sh; run that instead")

tmpdir = sys.argv[1]  # absolute path to bootstrap's fetched root files
ref    = sys.argv[2] if len(sys.argv) > 2 else None
repo   = sys.argv[3] if len(sys.argv) > 3 else None
args   = sys.argv[4:]  # the user's original args

try:
    # TODO:
    print(f"[configure.py] tmpdir = {tmpdir}")
    print(f"[configure.py] ref    = {ref}")
    print(f"[configure.py] repo   = {repo}")
    print(f"[configure.py] args   = {args}")
    print(f"[configure.py] root files present = {sorted(os.listdir(tmpdir))}")

finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
