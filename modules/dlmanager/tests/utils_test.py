# -*- coding: utf-8 -*-
import os
from dlmanager.utils import normalize_path_for_remote

def test_normalize_cygwin_drive_backslash():
    p = "C:\\Users\\Max\\Downloads"
    out = normalize_path_for_remote(p, "windows-cygwin")
    assert out == "/cygdrive/c/Users/Max/Downloads"

def test_normalize_cygwin_drive_forwardslash():
    p = "D:/Data/Work"
    out = normalize_path_for_remote(p, "windows-cygwin")
    assert out == "/cygdrive/d/Data/Work"

def test_normalize_linux_nochange():
    p = "/home/max/data"
    out = normalize_path_for_remote(p, "linux")
    assert out == p

def test_auto_nochange():
    p = "relative/path"
    out = normalize_path_for_remote(p, "auto")
    assert out == p
