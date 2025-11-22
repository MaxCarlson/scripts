# Interactive Duplicate Viewing & Analysis System

## Overview

A comprehensive interactive TUI for browsing, analyzing, and managing duplicate groups discovered by vdedup. This system allows real-time exploration of duplicate sets with detailed comparison metrics and stage-specific match information.

---

## Phase 1: Basic Interactive Duplicate Browser

### 1.1 Real-Time Duplicate Group Display
**Status**: TODO
**Priority**: HIGH

**Description**: As duplicates are found during scanning, allow users to switch view to browse discovered groups.

**Implementation**:

1. **Keyboard Trigger**:
   - Press `V` (View) key during scan to switch to duplicate browser
   - Press `ESC` or `V` again to return to pipeline progress view
   - Duplicate browser updates in real-time as new groups are discovered

2. **Data Structure**:
   ```python
   @dataclass
   class DuplicateGroup:
       group_id: str                    # e.g., "sha256:abc123..." or "phash:group_001"
       stage_found: str                 # "Q1 Size", "Q2 SHA256", "Q3 Metadata", "Q4 pHash"
       master: FileMeta                 # Winner/keeper file
       duplicates: List[FileMeta]       # Loser files
       match_info: MatchInfo            # How match was determined
       timestamp_found: float           # When group was discovered

   @dataclass
   class MatchInfo:
       stage: str                       # "Q2 SHA256", "Q4 pHash", etc.
       match_type: str                  # "exact", "visual", "metadata", "size"
       confidence: float                # 0.0-1.0 (1.0 = exact match)

       # Stage-specific details
       size_bytes: Optional[int]        # For Q1
       hash_value: Optional[str]        # For Q2
       metadata_diff: Optional[Dict]    # For Q3
       phash_distance: Optional[int]    # For Q4 (Hamming distance)
       phash_threshold: Optional[int]   # Threshold used
       frame_matches: Optional[List[int]]  # Which frames matched
   ```

3. **Display Format** (termdash InteractiveList):
   ```
   ┌─ Duplicate Groups (892 files in 331 groups) ──────────────┐
   │ → [+] sha256:abc123... (Q2 SHA256) - 3 duplicates         │
   │   [+] phash:group_001 (Q4 pHash 85%) - 5 duplicates       │
   │   [+] size:1234567890 (Q1 Size) - 2 duplicates            │
   │   [-] metadata:h264_1080p (Q3 Metadata) - 4 duplicates    │
   │       ├─ [MASTER] video_original.mp4 (1.2 GB, 01:32:45)   │
   │       ├─ video_copy1.mp4 (1.2 GB, +0s, bitrate: -5%)      │
   │       ├─ video_copy2.mp4 (1.1 GB, -3s, bitrate: -12%)     │
   │       └─ video_lowres.mp4 (800 MB, +1s, bitrate: -35%)    │
   └────────────────────────────────────────────────────────────┘
   ```

**Files to Modify**:
- `pipeline.py`: Add callback to report groups as they're discovered
- `progress.py`: Store duplicate groups in real-time
- Create new `duplicate_viewer.py`: Interactive browser using termdash
- `video_dedupe.py`: Add keyboard handler to switch views

**Acceptance Criteria**:
- [✓] Press `V` during scan to view duplicates
- [✓] Groups appear in real-time as discovered
- [✓] Master file marked with [MASTER] tag
- [✓] Collapse/expand groups with Enter key
- [✓] Return to progress view with ESC/V

---

### 1.2 Hierarchical Navigation (Master/Duplicates)
**Status**: TODO
**Priority**: HIGH

**Description**: Treat duplicate groups as hierarchical structures where master is top-level and duplicates are children.

**Interaction Model**:

1. **Collapsed Group** (default):
   ```
   [+] sha256:abc123... (Q2 SHA256) - 3 duplicates
   ```
   - Shows group ID, stage found, duplicate count
   - Master file info in summary

2. **Expanded Group** (press Enter on collapsed):
   ```
   [-] sha256:abc123... (Q2 SHA256) - 3 duplicates
       ├─ [MASTER] video_original.mp4 (1.2 GB, 01:32:45)
       ├─ video_copy1.mp4 (1.2 GB, +0s)
       ├─ video_copy2.mp4 (1.1 GB, -3s)
       └─ video_lowres.mp4 (800 MB, +1s)
   ```
   - Master always listed first with [MASTER] tag
   - Duplicates sorted by similarity score (descending)
   - Time/size diffs shown relative to master

3. **Navigation**:
   - `↑/↓` or `j/k`: Move selection
   - `Enter`: Toggle expand/collapse
   - `Space`: Mark/unmark for custom actions
   - `i`: Show detailed info (context-dependent, see below)

**Files to Create**:
- `duplicate_viewer.py`: Main viewer logic
- Extend termdash `InteractiveList` to support tree-like structures

**Acceptance Criteria**:
- [✓] Groups collapsed by default
- [✓] Enter toggles expand/collapse
- [✓] Master always first in expanded view
- [✓] Duplicates show relative diffs
- [✓] Keyboard navigation works smoothly

---

### 1.3 Context-Aware Detail Views ('i' key)
**Status**: TODO
**Priority**: HIGH

**Description**: Pressing 'i' shows different detail screens depending on context.

**Scenarios**:

#### 1.3.1 'i' on Collapsed Group (Special Group Info)
Shows comprehensive duplicate group analysis screen:

```
┌─ Duplicate Group Details ─────────────────────────────────────────────────┐
│ Group ID: sha256:abc123def456...                                          │
│ Stage: Q2 SHA256 (Exact Match)                                            │
│ Found: 2024-01-15 14:32:18                                                │
│ Total Files: 4 (1 master + 3 duplicates)                                  │
│ Space Reclaimable: 2.3 GB                                                 │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│ ┌─ File Comparison ──────────────────────────────────────────────────────┐│
│ │ File                     Size      Duration   Bitrate   Match Info    ││
│ │ ─────────────────────── ──────── ────────── ────────── ───────────────││
│ │ [M] video_original.mp4  1.20 GB  01:32:45   1800 kbps (master)        ││
│ │     video_copy1.mp4     1.20 GB  01:32:45   1800 kbps SHA256: 100%    ││
│ │                                   (+0s)      (+0%)                      ││
│ │     video_copy2.mp4     1.15 GB  01:32:42   1750 kbps SHA256: 100%    ││
│ │                                   (-3s)      (-2.8%)                    ││
│ │     video_lowres.mp4    800 MB   01:32:46   1170 kbps SHA256: 100%    ││
│ │                                   (+1s)      (-35%)                     ││
│ └────────────────────────────────────────────────────────────────────────┘│
│                                                                            │
│ ┌─ Match Details ────────────────────────────────────────────────────────┐│
│ │ Stage: Q2 SHA256                                                       ││
│ │ Match Type: Exact binary duplicate                                     ││
│ │ Confidence: 100%                                                       ││
│ │ Hash: abc123def456789...                                               ││
│ │ Algorithm: SHA-256                                                     ││
│ └────────────────────────────────────────────────────────────────────────┘│
│                                                                            │
│ Press ESC to close, 'd' to delete duplicates, 'm' to change master        │
└────────────────────────────────────────────────────────────────────────────┘
```

**Color Coding**:
- Duration diff: `[green]+Xs[/green]` (longer), `[red]-Xs[/red]` (shorter)
- Size diff: Same color scheme
- Bitrate diff: Same color scheme
- Master row: Highlighted/bold

**Data Displayed**:
- **File Comparison Table**:
  - File name (master marked with [M])
  - Absolute size for master, relative diff for duplicates
  - Absolute duration for master, time diff for duplicates
  - Absolute bitrate for master, percentage diff for duplicates
  - Match info (how this file was matched to master)

- **Match Details Panel**:
  - Stage where group was created
  - Match type (exact, visual, metadata, size)
  - Confidence score
  - Stage-specific metrics:
    - Q1: Size in bytes
    - Q2: SHA-256 hash
    - Q3: Metadata differences
    - Q4: pHash Hamming distance, threshold, frame match count

#### 1.3.2 'i' on Expanded Group Master
Shows standard file detail view (same as non-duplicate files):

```
┌─ File Details: video_original.mp4 ─────────────────────────────────────────┐
│ Path: /mnt/videos/archive/video_original.mp4                              │
│ Size: 1.20 GB (1,234,567,890 bytes)                                       │
│ Modified: 2024-01-10 15:30:22                                             │
│ Created: 2024-01-10 15:28:15                                               │
├────────────────────────────────────────────────────────────────────────────┤
│ ┌─ Video Metadata ──────────────────────────────────────────────────────┐ │
│ │ Duration: 01:32:45 (5565 seconds)                                     │ │
│ │ Resolution: 1920x1080 (1080p)                                         │ │
│ │ Codec: h264 (High Profile)                                            │ │
│ │ Container: mp4                                                         │ │
│ │ Bitrate: 1800 kbps                                                    │ │
│ │ Frame Rate: 29.97 fps                                                 │ │
│ │ Audio: aac, 2 channels, 128 kbps                                      │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│ ┌─ Duplicate Group Info ────────────────────────────────────────────────┐ │
│ │ This file is the MASTER of a duplicate group                          │ │
│ │ Group: sha256:abc123... (Q2 SHA256)                                   │ │
│ │ Duplicates: 3 files (2.3 GB reclaimable)                              │ │
│ │ Press 'g' to view full duplicate group                                │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│ Press ESC to close, 'o' to open file, 'p' to open parent folder           │
└────────────────────────────────────────────────────────────────────────────┘
```

#### 1.3.3 'i' on Individual Duplicate File (in expanded group)
Shows file details + duplicate-specific info:

```
┌─ File Details: video_copy2.mp4 ────────────────────────────────────────────┐
│ Path: /mnt/videos/backup/video_copy2.mp4                                  │
│ Size: 1.15 GB (1,150,000,000 bytes) [-84.6 MB vs master]                  │
│ Modified: 2024-01-12 09:15:33                                             │
│ Created: 2024-01-12 09:12:10                                               │
├────────────────────────────────────────────────────────────────────────────┤
│ ┌─ Video Metadata ──────────────────────────────────────────────────────┐ │
│ │ Duration: 01:32:42 (5562s) [-3s vs master]                            │ │
│ │ Resolution: 1920x1080 (same as master)                                │ │
│ │ Codec: h264 (High Profile, same as master)                            │ │
│ │ Container: mp4 (same as master)                                       │ │
│ │ Bitrate: 1750 kbps [-2.8% vs master]                                  │ │
│ │ Frame Rate: 29.97 fps (same as master)                                │ │
│ │ Audio: aac, 2 channels, 128 kbps (same as master)                     │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│ ┌─ Duplicate Match Info ────────────────────────────────────────────────┐ │
│ │ Status: DUPLICATE (marked for deletion)                               │ │
│ │ Master: video_original.mp4                                             │ │
│ │ Group: sha256:abc123... (Q2 SHA256)                                   │ │
│ │ Match: Exact binary duplicate (SHA-256: 100%)                         │ │
│ │ Reason for loss: Lower bitrate than master                            │ │
│ │ Press 'g' to view full duplicate group                                │ │
│ │ Press 'P' to promote this file to master                              │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│ Press ESC to close, 'o' to open file, 'K' to keep (remove from duplicates)│
└────────────────────────────────────────────────────────────────────────────┘
```

**Files to Create**:
- `duplicate_detail_view.py`: Group comparison screen
- `file_detail_view.py`: Standard file detail view (reusable)
- Extend these views with duplicate-aware context

**Acceptance Criteria**:
- [✓] 'i' on collapsed group → group comparison screen
- [✓] 'i' on master in expanded view → file detail with group info
- [✓] 'i' on duplicate → file detail with match info
- [✓] Color-coded diffs (green/red for +/-)
- [✓] All metadata comparisons shown
- [✓] Match info includes stage and confidence

---

## Phase 2: Advanced Duplicate Management

### 2.1 Keep All Files in Search Pool (Multi-Stage Matching)
**Status**: TODO
**Priority**: MEDIUM

**Description**: By default, vdedup removes files from search pool once matched in earlier stages (for speed). Add option to keep all files searchable across all stages to gather multi-stage match data.

**Current Behavior**:
```python
# In pipeline.py
# After Q2 exact matches found:
exact_match_paths = {file.path for group in q2_groups for file in group}
q3_candidates = [f for f in candidates if f.path not in exact_match_paths]
# Q3 only processes files NOT in Q2 matches
```

**New Behavior with `--keep-all-in-pool`**:
```python
# All files stay in pool
# But we track which stages matched them
for file in all_files:
    file.match_stages = []  # ["Q2 SHA256", "Q3 Metadata", "Q4 pHash"]
    file.match_groups = {}  # {stage: group_id}
```

**Implementation**:

1. **Add CLI Flag**:
   ```python
   p.add_argument("--keep-all-in-pool", action="store_true",
                  help="Keep all files in search pool across all stages (slower but more comprehensive)")
   ```

2. **Track Multi-Stage Matches**:
   ```python
   @dataclass
   class FileMeta:
       # ... existing fields ...
       match_history: List[StageMatch] = field(default_factory=list)

   @dataclass
   class StageMatch:
       stage: str                  # "Q2 SHA256"
       group_id: str              # Which group in that stage
       is_master: bool            # Is this file the master of that group?
       match_confidence: float    # 0.0-1.0
       match_details: Dict        # Stage-specific match info
   ```

3. **Winner Selection with Multi-Stage Data**:
   ```python
   def choose_winner_multi_stage(group: List[FileMeta]) -> FileMeta:
       """
       Choose winner considering matches from all stages.

       Priority:
       1. File matched in most stages (more confident match)
       2. File with highest average confidence across stages
       3. Standard quality heuristics (resolution, bitrate, etc.)
       """
       scores = {}
       for file in group:
           stage_count = len(file.match_history)
           avg_confidence = sum(m.confidence for m in file.match_history) / stage_count
           scores[file] = (stage_count, avg_confidence)

       return max(group, key=lambda f: scores[f])
   ```

4. **Display in UI**:
   ```
   [i] on duplicate shows:
   ┌─ Multi-Stage Match Info ────────────────────────────┐
   │ This file matched in 3 stages:                      │
   │ • Q2 SHA256: Exact (100%) - Group: sha256:abc123   │
   │ • Q3 Metadata: Match (95%) - Group: meta:h264_1080p│
   │ • Q4 pHash: Visual (87%) - Group: phash:001         │
   └──────────────────────────────────────────────────────┘
   ```

**Files to Modify**:
- `pipeline.py`: Add `--keep-all-in-pool` logic
- `models.py`: Add `match_history` field to `FileMeta`
- `grouping.py`: Update winner selection algorithm
- `duplicate_viewer.py`: Display multi-stage match info

**Acceptance Criteria**:
- [✓] `--keep-all-in-pool` flag keeps files in all stages
- [✓] Multi-stage matches tracked for each file
- [✓] Winner selection considers multi-stage confidence
- [✓] UI shows all stages where file matched
- [✓] Performance impact documented (expect 20-40% slower)

---

### 2.2 Re-Run Specific Stages on Duplicate Groups
**Status**: TODO
**Priority**: MEDIUM

**Description**: Allow running any pipeline stage against a specific duplicate group to gather additional match data or verify matches.

**Use Cases**:
- Group found in Q2 (exact hash) → re-run Q4 (pHash) to get visual similarity score
- Group found in Q3 (metadata) → re-run Q2 (hash) to check if truly identical
- Verify suspect matches with more thorough analysis

**Implementation**:

1. **Interactive Command** (in duplicate viewer):
   ```
   Press 'R' on selected group:
   ┌─ Re-Run Stage ───────────────────────────────────┐
   │ Select stage to run on this group:              │
   │ → Q2 SHA256 (Full Hash)                         │
   │   Q3 Metadata (ffprobe)                         │
   │   Q4 pHash (Visual Similarity)                  │
   │   Q6 Audio (Audio Fingerprint)                  │
   │                                                  │
   │ Press Enter to run, ESC to cancel               │
   └──────────────────────────────────────────────────┘
   ```

2. **Stage Runner**:
   ```python
   async def run_stage_on_group(
       group: DuplicateGroup,
       stage: str,
       cfg: PipelineConfig,
       cache: HashCache
   ) -> Dict[str, Any]:
       """
       Run specific pipeline stage on all files in group.

       Returns enriched match data for the group.
       """
       files = [group.master] + group.duplicates

       if stage == "Q2 SHA256":
           hashes = await hash_files(files, cache)
           return {
               "all_identical": len(set(hashes.values())) == 1,
               "hashes": hashes
           }

       elif stage == "Q4 pHash":
           phashes = await compute_phashes(files, cfg, cache)
           distances = compute_hamming_distances(phashes)
           return {
               "distances": distances,
               "max_distance": max(distances.values()),
               "avg_distance": sum(distances.values()) / len(distances)
           }

       # ... other stages
   ```

3. **Update Group with Results**:
   ```python
   group.supplemental_stages = {
       "Q4 pHash": {
           "avg_distance": 3,
           "max_distance": 8,
           "all_similar": True,
           "run_timestamp": time.time()
       }
   }
   ```

4. **Display Results**:
   ```
   ┌─ Stage Re-Run Results ───────────────────────────┐
   │ Stage: Q4 pHash                                  │
   │ Run Time: 2024-01-15 16:45:30                    │
   │                                                  │
   │ Results:                                         │
   │ • All files visually similar: Yes               │
   │ • Average Hamming distance: 3 bits              │
   │ • Maximum distance: 8 bits (below threshold)    │
   │ • Confidence: 95%                                │
   │                                                  │
   │ Conclusion: Visual match confirms this group    │
   │                                                  │
   │ Press 's' to save results, ESC to close         │
   └──────────────────────────────────────────────────┘
   ```

**Files to Create**:
- `stage_runner.py`: Isolated stage execution
- Integrate with `duplicate_viewer.py`

**Acceptance Criteria**:
- [✓] 'R' key on group shows stage selection menu
- [✓] Selected stage runs on all group files
- [✓] Results displayed in detail view
- [✓] Results saved to group metadata
- [✓] Progress shown during stage execution
- [✓] Cache used/updated appropriately

---

### 2.3 Master Promotion & Sub-Masters
**Status**: TODO
**Priority**: LOW (Future Enhancement)

**Description**: Support promoting any duplicate to master, and handle cases where files match each other but not the current master (sub-master concept).

**Master Promotion**:
```
Press 'P' on any duplicate file:
┌─ Promote to Master ──────────────────────────────────┐
│ Current Master: video_original.mp4                   │
│                 1.20 GB, 01:32:45, 1800 kbps         │
│                                                      │
│ New Master:     video_copy2.mp4                     │
│                 1.15 GB, 01:32:42, 1750 kbps         │
│                                                      │
│ Reason: (Enter reason or press Enter to skip)       │
│ ┌──────────────────────────────────────────────────┐ │
│ │ Better quality encoding                          │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ Press Y to confirm, N to cancel                     │
└──────────────────────────────────────────────────────┘
```

**Sub-Master Concept**:
```
When --keep-all-in-pool is enabled and files match each other but not master:

Group: sha256:abc123...
├─ [MASTER] video_original.mp4
│   └─ video_copy1.mp4 (matches master: SHA256 100%)
└─ [SUB-MASTER] video_reencoded.mp4 (matches master: pHash 82%)
    ├─ video_reencoded_v2.mp4 (matches sub-master: SHA256 100%)
    └─ video_reencoded_v3.mp4 (matches sub-master: SHA256 100%)

In this case:
- Master represents the "original" lineage
- Sub-master represents a "re-encoded" lineage
- Both lineages are in same group due to visual similarity
- But sub-master group members are exact copies of each other
```

**Implementation** (Future):
- Track parent/child relationships in match graph
- Allow hierarchical group structure
- Display as nested tree in UI

---

## Phase 3: Enhanced Filtering & Actions

### 3.1 Filter Duplicate Groups
**Status**: TODO
**Priority**: MEDIUM

**Description**: Filter visible duplicate groups by various criteria.

**Filter Options**:
```
Press 'f' to open filter menu:
┌─ Filter Groups ──────────────────────────────────────┐
│ Stage Found:                                         │
│   [x] Q1 Size                                        │
│   [x] Q2 SHA256                                      │
│   [x] Q3 Metadata                                    │
│   [x] Q4 pHash                                       │
│                                                      │
│ Match Confidence:                                    │
│   [ ] Exact only (100%)                              │
│   [x] High (90-100%)                                 │
│   [x] Medium (70-90%)                                │
│   [ ] Low (<70%)                                     │
│                                                      │
│ Group Size:                                          │
│   Min files: [2  ]  Max files: [999]                 │
│                                                      │
│ Space Savings:                                       │
│   Min reclaimable: [100 MB  ]                        │
│                                                      │
│ Press Enter to apply, ESC to cancel                 │
└──────────────────────────────────────────────────────┘
```

---

### 3.2 Bulk Actions on Groups
**Status**: TODO
**Priority**: MEDIUM

**Description**: Perform actions on multiple selected groups.

**Actions**:
- `Space`: Mark/unmark group
- `A`: Mark all visible groups
- `U`: Unmark all
- `D`: Delete all duplicates in marked groups
- `E`: Export marked groups to report
- `X`: Exclude marked groups (false positives)

---

## Phase 4: Visualization & Analytics

### 4.1 Duplicate Statistics Dashboard
**Status**: TODO
**Priority**: LOW

**Description**: Summary dashboard showing duplicate distribution.

**Display**:
```
┌─ Duplicate Analysis ─────────────────────────────────┐
│ Total Groups: 331                                    │
│ Total Duplicates: 892 files                         │
│ Space Reclaimable: 45.3 GB                          │
│                                                      │
│ By Stage:                                            │
│   Q1 Size:     12 groups (  24 files,  1.2 GB)      │
│   Q2 SHA256:  215 groups ( 645 files, 38.5 GB)      │
│   Q3 Metadata: 84 groups ( 168 files,  4.1 GB)      │
│   Q4 pHash:    20 groups (  55 files,  1.5 GB)      │
│                                                      │
│ By Confidence:                                       │
│   Exact (100%):     227 groups                       │
│   High (90-99%):     84 groups                       │
│   Medium (70-89%):   20 groups                       │
│                                                      │
│ Largest Groups:                                      │
│   1. sha256:abc... - 15 duplicates (8.2 GB)         │
│   2. phash:xyz...  - 12 duplicates (3.4 GB)         │
│   3. meta:def...   -  9 duplicates (2.1 GB)         │
└──────────────────────────────────────────────────────┘
```

---

## Implementation Checklist

### Phase 1: Basic Interactive Browser
- [ ] 1.1 Real-time duplicate group display
  - [ ] Data structures (DuplicateGroup, MatchInfo)
  - [ ] Press 'V' to switch to viewer
  - [ ] Real-time updates as groups found
  - [ ] Integration with pipeline.py
- [ ] 1.2 Hierarchical navigation
  - [ ] Collapse/expand groups
  - [ ] Master/duplicate tree structure
  - [ ] Keyboard navigation (↑↓jk, Enter, Space)
- [ ] 1.3 Context-aware detail views
  - [ ] 'i' on collapsed group → comparison screen
  - [ ] 'i' on master → file detail + group info
  - [ ] 'i' on duplicate → file detail + match info
  - [ ] Color-coded diffs (green/red)
  - [ ] Match metadata display

### Phase 2: Advanced Management
- [ ] 2.1 Multi-stage matching
  - [ ] `--keep-all-in-pool` flag
  - [ ] Track match_history per file
  - [ ] Multi-stage winner selection
  - [ ] Display all stages in UI
- [ ] 2.2 Re-run stages on groups
  - [ ] 'R' key to select stage
  - [ ] Stage runner implementation
  - [ ] Display results
  - [ ] Save to group metadata
- [ ] 2.3 Master promotion (future)
  - [ ] 'P' key to promote
  - [ ] Sub-master concept
  - [ ] Hierarchical match graph

### Phase 3: Filtering & Actions
- [ ] 3.1 Filter groups
  - [ ] Filter by stage
  - [ ] Filter by confidence
  - [ ] Filter by size/space
- [ ] 3.2 Bulk actions
  - [ ] Mark/unmark groups
  - [ ] Bulk delete
  - [ ] Export/exclude

### Phase 4: Visualization
- [ ] 4.1 Statistics dashboard
  - [ ] Group distribution
  - [ ] Space analysis
  - [ ] Largest groups

---

## Files to Create/Modify

### New Files:
- `modules/vdedup/duplicate_viewer.py` - Main interactive viewer
- `modules/vdedup/duplicate_detail_view.py` - Group comparison screen
- `modules/vdedup/file_detail_view.py` - File detail screen (reusable)
- `modules/vdedup/stage_runner.py` - Isolated stage execution
- `modules/vdedup/match_graph.py` - Track multi-stage relationships (future)

### Modified Files:
- `modules/vdedup/pipeline.py` - Report groups in real-time, --keep-all-in-pool
- `modules/vdedup/models.py` - Add match_history, DuplicateGroup
- `modules/vdedup/grouping.py` - Multi-stage winner selection
- `modules/vdedup/progress.py` - Store duplicate groups, keyboard handler
- `modules/vdedup/video_dedupe.py` - Add CLI flags, integrate viewer

### Dependencies:
- `termdash.interactive_list` - Already used, extend for tree structures
- `rich` - For color-coded diffs and formatting
- Existing vdedup modules (cache, hashers, probe, etc.)

---

## Notes

### Performance Considerations:
- Real-time updates: Batch group additions (every 100ms) to avoid UI flicker
- `--keep-all-in-pool`: Expect 20-40% performance hit (document clearly)
- Stage re-runs: Show progress, use cache aggressively
- Large group rendering: Virtualize list if >1000 groups

### User Experience:
- Default to collapsed groups (cleaner view)
- Master always first (consistent expectation)
- Color code diffs consistently (green=more, red=less)
- Clear visual distinction between master and duplicates
- Keyboard shortcuts should be intuitive and documented in footer

### Future Enhancements:
- Export custom report formats (CSV, HTML)
- Integration with file managers (open in explorer)
- Duplicate preview (video thumbnails/posters)
- Automatic master selection policy configuration
- Machine learning for winner selection (learn from user choices)

---

## Testing Plan

### Unit Tests:
- [ ] DuplicateGroup creation and serialization
- [ ] MatchInfo calculation for each stage type
- [ ] Multi-stage match tracking
- [ ] Winner selection algorithms
- [ ] Filter logic

### Integration Tests:
- [ ] Real-time group updates during scan
- [ ] Keyboard navigation across all views
- [ ] Stage re-run on actual video files
- [ ] Master promotion workflow

### Manual Testing:
- [ ] UI responsiveness with 100+ groups
- [ ] UI responsiveness with 1000+ groups
- [ ] Color rendering on different terminals
- [ ] Keyboard shortcuts on different platforms

---

## Documentation Updates Needed

- [ ] Update EXPLAINED.md with interactive viewer workflow
- [ ] Add duplicate viewer screenshots to README
- [ ] Document all keyboard shortcuts
- [ ] Update CLI help text for new flags
- [ ] Add examples for common workflows
