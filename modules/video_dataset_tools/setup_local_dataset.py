#!/usr/bin/env python3
"""Setup dataset from existing local videos."""

import json
import shutil
from pathlib import Path

videos_dir = Path(__file__).parent / "videos"
output_dir = Path(__file__).parent / "testing"

# Get all video files
videos = sorted(videos_dir.glob("*.mp4"))
print(f"Found {len(videos)} videos")

# Create output structure
original_dir = output_dir / "original"
original_dir.mkdir(parents=True, exist_ok=True)

keys = []
id_map = {}

for idx, video_path in enumerate(videos, start=1):
    key = f"master-video-{idx}"
    keys.append(key)
    id_map[key] = f"local://{video_path.name}"

    # Copy to original dir
    dest = original_dir / f"{key}{video_path.suffix}"
    if not dest.exists():
        try:
            print(f"Copying {video_path.name[:50]}... -> {dest.name}")
        except UnicodeEncodeError:
            print(f"Copying [special chars] -> {dest.name}")
        shutil.copy2(video_path, dest)

# Write mapping.txt
mapping_file = output_dir / "mapping.txt"
mapping_file.write_text("\n".join(keys) + "\n", encoding="utf-8")

# Write id_map.json
id_map_file = output_dir / "id_map.json"
id_map_file.write_text(json.dumps(id_map, indent=2), encoding="utf-8")

print(f"\nCreated {len(keys)} masters in {original_dir}")
print(f"mapping.txt: {mapping_file}")
print(f"id_map.json: {id_map_file}")
