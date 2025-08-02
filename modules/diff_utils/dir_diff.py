#!/usr/bin/env python3
"""
Module: dir_diff.py
Description: Implements the core functionality of a directory diff tool that
compares two directories (src vs. dest) based on structure, file content,
and metadata. It supports ignore filters, checksum caching, time tolerance,
and multiple operation modes (diff, sync, copy, delete).
"""

import os
import fnmatch
import hashlib
import shutil
import time
from cross_platform.debug_utils import write_debug
from cross_platform.file_system_manager import FileSystemManager

class DirectoryDiff:
    def __init__(self, src, dest, options):
        self.src = os.path.abspath(src)
        self.dest = os.path.abspath(dest)
        self.options = options
        self.fs_manager = FileSystemManager()
        self.checksum_cache = {}
        self.src_structure = {}
        self.dest_structure = {}
        self.diff_result = {
            "src_only": [],
            "dest_only": [],
            "common": [],
            "content_diff": [],
            "metadata_diff": []
        }
        write_debug(f"Initialized DirectoryDiff with src: {self.src} and dest: {self.dest}", channel="Debug")

    def scan_directory(self, base_dir):
        write_debug(f"Scanning directory: {base_dir}", channel="Debug")
        file_dict = {}
        follow_links = self.options.get("follow_symlinks", False)
        for root, dirs, files in os.walk(base_dir, followlinks=follow_links):
            rel_dir = os.path.relpath(root, base_dir)
            if rel_dir == ".":
                rel_dir = ""
            # Add directories to the dictionary
            for d in dirs:
                rel_path = os.path.join(rel_dir, d)
                file_dict[rel_path] = {"is_dir": True}
            # Add files with metadata
            for f in files:
                rel_path = os.path.join(rel_dir, f)
                full_path = os.path.join(root, f)
                try:
                    stat = os.stat(full_path)
                    file_dict[rel_path] = {
                        "is_dir": False,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "path": full_path
                    }
                except Exception as e:
                    write_debug(f"Error accessing file {full_path}: {e}", channel="Error")
        return file_dict

    def apply_ignore_filters(self, file_dict):
        ignore_patterns = self.options.get("ignore_patterns", [])
        if ignore_patterns:
            filtered = {}
            for path, info in file_dict.items():
                skip = False
                for pattern in ignore_patterns:
                    if fnmatch.fnmatch(path, pattern):
                        skip = True
                        break
                if not skip:
                    filtered[path] = info
            write_debug(f"Applied ignore filters. Items before: {len(file_dict)}, after: {len(filtered)}", channel="Debug")
            return filtered
        return file_dict

    def compute_checksum(self, file_path, algorithm="md5"):
        # Return cached checksum if available
        if file_path in self.checksum_cache:
            return self.checksum_cache[file_path]
        try:
            h = hashlib.new(algorithm)
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    h.update(chunk)
            checksum = h.hexdigest()
            self.checksum_cache[file_path] = checksum
            return checksum
        except Exception as e:
            write_debug(f"Error computing checksum for {file_path}: {e}", channel="Error")
            return None

    def compare_structures(self):
        self.src_structure = self.apply_ignore_filters(self.scan_directory(self.src))
        self.dest_structure = self.apply_ignore_filters(self.scan_directory(self.dest))
        src_set = set(self.src_structure.keys())
        dest_set = set(self.dest_structure.keys())
        self.diff_result["src_only"] = sorted(list(src_set - dest_set))
        self.diff_result["dest_only"] = sorted(list(dest_set - src_set))
        self.diff_result["common"] = sorted(list(src_set & dest_set))
        write_debug(f"Comparison complete. Src only: {len(self.diff_result['src_only'])}, "
                    f"Dest only: {len(self.diff_result['dest_only'])}, Common: {len(self.diff_result['common'])}", channel="Information")

    def compare_files(self):
        checksum_algo = self.options.get("checksum", "md5")
        time_tolerance = float(self.options.get("time_tolerance", 0))
        for rel_path in self.diff_result["common"]:
            src_info = self.src_structure[rel_path]
            dest_info = self.dest_structure[rel_path]
            # If both are directories, skip file content comparison
            if src_info.get("is_dir") and dest_info.get("is_dir"):
                continue
            # If one is a directory and one is a file, mark as difference
            if src_info.get("is_dir") != dest_info.get("is_dir"):
                self.diff_result["content_diff"].append(rel_path)
                continue
            # Compare content using checksum
            src_checksum = self.compute_checksum(src_info["path"], algorithm=checksum_algo)
            dest_checksum = self.compute_checksum(dest_info["path"], algorithm=checksum_algo)
            if src_checksum != dest_checksum:
                self.diff_result["content_diff"].append(rel_path)
            # Compare metadata if the option is enabled
            if self.options.get("compare_metadata", False):
                # Check file sizes first
                if src_info.get("size") != dest_info.get("size"):
                    self.diff_result["metadata_diff"].append(rel_path)
                # Compare modification times within a tolerance (in seconds)
                mtime_diff = abs(src_info.get("mtime", 0) - dest_info.get("mtime", 0))
                if mtime_diff > time_tolerance:
                    if rel_path not in self.diff_result["metadata_diff"]:
                        self.diff_result["metadata_diff"].append(rel_path)

    def generate_report(self):
        report = []
        report.append("=== Directory Diff Report ===")
        report.append(f"Source Directory: {self.src}")
        report.append(f"Destination Directory: {self.dest}")
        report.append("")
        report.append("---- Summary Statistics ----")
        report.append(f"Total items in source: {len(self.src_structure)}")
        report.append(f"Total items in destination: {len(self.dest_structure)}")
        report.append(f"Items only in source: {len(self.diff_result['src_only'])}")
        report.append(f"Items only in destination: {len(self.diff_result['dest_only'])}")
        report.append(f"Common items: {len(self.diff_result['common'])}")
        report.append(f"Files with content differences: {len(self.diff_result['content_diff'])}")
        report.append(f"Files with metadata differences: {len(self.diff_result['metadata_diff'])}")
        report.append("")
        report.append("---- Detailed Differences ----")
        if self.diff_result["src_only"]:
            report.append("Items only in source:")
            for item in self.diff_result["src_only"]:
                report.append(f"  {item}")
        if self.diff_result["dest_only"]:
            report.append("Items only in destination:")
            for item in self.diff_result["dest_only"]:
                report.append(f"  {item}")
        if self.diff_result["content_diff"]:
            report.append("Files with content differences:")
            for item in self.diff_result["content_diff"]:
                report.append(f"  {item}")
        if self.diff_result["metadata_diff"]:
            report.append("Files with metadata differences:")
            for item in self.diff_result["metadata_diff"]:
                report.append(f"  {item}")
        return "\n".join(report)

    def perform_actions(self):
        """
        Perform file operations based on the selected mode:
          - sync: Copy missing items from src to dest.
          - copy: Update files in dest that differ from src.
          - delete: Delete source items that match those in destination.
        Respects dry-run and interactive options.
        """
        mode = self.options.get("mode", "diff").lower()
        dry_run = self.options.get("dry_run", False)
        interactive = self.options.get("interactive", False)

        if mode == "sync":
            # Copy missing items from source to destination.
            for rel_path in self.diff_result["src_only"]:
                src_path = os.path.join(self.src, rel_path)
                dest_path = os.path.join(self.dest, rel_path)
                write_debug(f"[SYNC] Would copy {src_path} to {dest_path}", channel="Information")
                if not dry_run:
                    dest_dir = os.path.dirname(dest_path)
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.copy2(src_path, dest_path)
        elif mode == "copy":
            # For common items that differ in content, update the destination.
            for rel_path in self.diff_result["content_diff"]:
                src_path = os.path.join(self.src, rel_path)
                dest_path = os.path.join(self.dest, rel_path)
                write_debug(f"[COPY] Would update {dest_path} from {src_path}", channel="Information")
                if not dry_run:
                    shutil.copy2(src_path, dest_path)
        elif mode == "delete":
            # Delete source items that are verified to be identical in destination.
            for rel_path in self.diff_result["common"]:
                src_info = self.src_structure[rel_path]
                dest_info = self.dest_structure[rel_path]
                # Only delete if both are files and checksums match
                if not src_info.get("is_dir") and not dest_info.get("is_dir"):
                    src_checksum = self.compute_checksum(src_info["path"])
                    dest_checksum = self.compute_checksum(dest_info["path"])
                    if src_checksum == dest_checksum:
                        prompt = f"Delete {os.path.join(self.src, rel_path)}? [y/N]: " if interactive else "y"
                        response = input(prompt) if interactive else "y"
                        if response.lower() == "y":
                            write_debug(f"[DELETE] Deleting {os.path.join(self.src, rel_path)}", channel="Information")
                            if not dry_run:
                                try:
                                    os.remove(src_info["path"])
                                except Exception as e:
                                    write_debug(f"Error deleting {src_info['path']}: {e}", channel="Error")
                # For directories, you might want to add extra logic.
        else:
            write_debug("No file operations performed. Mode is 'diff'.", channel="Information")

    def run(self):
        write_debug("Running DirectoryDiff...", channel="Information")
        self.compare_structures()
        self.compare_files()
        report = self.generate_report()
        write_debug(report, channel="Information")
        # If an operation mode other than diff was selected, perform file actions.
        if self.options.get("mode", "diff").lower() in ["sync", "copy", "delete"]:
            self.perform_actions()
        return report

# (Additional name-based comparison functions could be added here.)
