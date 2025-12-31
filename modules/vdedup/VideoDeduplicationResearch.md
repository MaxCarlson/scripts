# **Advanced Architectural Analysis and Algorithmic Scoring Methodologies for Interactive Video Deduplication Systems**

## **1\. Introduction: The Complexity of Semantic Video Deduplication**

The exponential growth of digital video libraries, driven by ubiquitous high-definition recording devices and massive online content repositories, has precipitated a crisis in data management. As storage volumes expand into the petabyte range, the accumulation of redundant data becomes not merely a nuisance but a significant infrastructural liability. While identifying exact binary duplicates—files that are bit-for-bit identical—is a solved problem in computer science, utilizing cryptographic hashes like SHA-256, the challenge of *semantic* video deduplication remains a frontier of active research. This domain concerns itself with "near-duplicates": videos that differ in digital representation but share identical perceptual content.  
The scope of this challenge is vast. A single source video may spawn dozens of variations: transcoded versions with different codecs (H.264 vs. HEVC), resolution downscales (4K source to 720p proxy), container shifts (MKV to MP4), and, most complex of all, temporal subsets. The "subset problem"—identifying that a 5-minute clip is mathematically and visually contained within a 2-hour master recording—requires algorithms that move beyond global file signatures to analyze the temporal topology of media streams.  
This report presents an exhaustive architectural audit and enhancement strategy for vdedup, a specialized software repository designed to tackle these challenges. Based on a detailed analysis of the provided codebase, including pipeline.py, audio.py, phash.py, and the interactive termdash user interface, we construct a comprehensive scoring methodology that balances positive signal detection against negative noise filtering. Furthermore, we architect a robust technical solution for a "Synchronized Grid Preview" feature, leveraging Inter-Process Communication (IPC) to transform the tool from a passive reporter into an active, human-in-the-loop verification workbench.

### **1.2 Controlled Datasets for Supervised Tuning**

Robust scoring research requires reproducible corpora of *known* duplicates and non-duplicates. The repository includes two companion utilities:

1. `modules/vdedup/tests/generate_media_dataset.py` — deterministically samples Creative Commons content via yt-dlp, driven by a published seed bank. Each seed produces a `seed_<id>/dataset_manifest.json` detailing all derived variants (downscales, upscales, random subset clips, and synthetic negatives).
2. `modules/vdedup/tests/evaluate_media_dataset.py` — executes the full pipeline against any generated dataset (single seed or entire root) and reports precision/recall, TP/FP/FN counts, plus the exact file pairs responsible for mistakes.

Researchers can iterate as follows:

```bash
python modules/vdedup/tests/generate_media_dataset.py \
    --seed-list default --sources 6 --subset-count 3

python modules/vdedup/tests/evaluate_media_dataset.py \
    --dataset modules/vdedup/tests/media_dataset \
    --metadata-score 0.6 --q4-threshold 14
```

Because the seeds and queries are recorded inside each manifest, every experiment is reproducible—a prerequisite for supervised threshold tuning and regression tracking.

### **1.1 The Imperative for Human-in-the-Loop Verification**

Despite advances in perceptual hashing (pHash) and feature extraction, algorithmic certainty in video deduplication often asymptotes below 100%. "False positives" are catastrophic in archival contexts; automatically deleting a unique video because an algorithm mistook a black frame sequence for a duplicate of another video is unacceptable. "False negatives" result in wasted storage.  
The vdedup system addresses this uncertainty through a sophisticated Terminal User Interface (TUI). As evidenced by the provided visual artifacts (Images 1, 2, and 3), the interface evolves from a high-level summary of duplicate groups to a granular, file-level inspection view. The user's request to implement a grid-based playback system (triggered via the O key) represents the critical "last mile" of this workflow. It acknowledges that while algorithms can shortlist candidates with high probability, only simultaneous, synchronized visual comparison can provide the absolute certainty required for destructive operations (deletion).

## **2\. Architectural Audit of the vdedup Repository**

The vdedup repository is architected as a progressive filtration pipeline, a design pattern essential for processing terabyte-scale datasets. A naive approach—comparing every video against every other video using expensive feature extraction—would result in $O(N^2)$ complexity with a prohibitively high constant time factor. vdedup mitigates this by employing a cascade of filters, where each stage eliminates non-duplicates using increasingly expensive but more accurate methods.

### **2.1 Core Module Analysis: scripts/modules/vdedup/**

The vdedup directory houses the business logic, separated into distinct concerns: pipeline orchestration, hashing mechanics, data modeling, and caching.

#### **2.1.1 The Pipeline Orchestrator (pipeline.py)**

The pipeline.py module acts as the central nervous system. It defines a multi-stage process (Q1 through Q7) that rigorously winnows the dataset.

* **Q1 (Size Bucketing):** Historically, deduplication tools often used file size as a primary key. However, analyzing CRITICAL\_FIXES.md reveals a pivotal architectural correction. Originally, unique file sizes might have been discarded. The corrected logic establishes Q1 as an *optimization hint* rather than a hard filter. This distinction is vital: visual duplicates (e.g., a raw AVI versus a compressed MP4) will rarely share a file size. By grouping identical sizes for fast-track processing while passing *all* files to subsequent visual stages, the pipeline avoids the "perfect match fallacy," ensuring that re-encoded duplicates are not prematurely discarded.  
* **Q2 (Cryptographic Hashing):** This stage employs a "fast-fail" strategy. A partial hash (reading only the head, tail, and middle segments of a file) identifies potential exact duplicates. Only files with colliding partial hashes are subjected to a full SHA-256 or BLAKE3 hash. This minimizes disk I/O, which is often the bottleneck in large scans.  
* **Q3 (Metadata Clustering):** Candidates are clustered by duration, resolution, and container. The vdedup implementation recognizes the fuzziness of video metadata; duration matching typically requires a tolerance (e.g., $\\pm 2$ seconds) to account for differences in muxing overhead or timestamp precision.  
* **Q4 (Perceptual Hashing & Subset Detection):** This is the computational core. Utilizing the phash.py module, the system decodes video frames into visual hashes. The integration of sequence\_matcher.py indicates a sophisticated temporal analysis. Rather than comparing a single global hash, the system treats a video as a *sequence* of frame hashes. It then searches for "diagonal streaks" in the similarity matrix—contiguous runs of matching frames that indicate one video is a temporal subset of another.

#### **2.1.2 Audio Fingerprinting Mechanics (audio.py)**

The audio.py module implements a custom audio fingerprinting solution tailored for robustness against transcoding artifacts. The code analysis reveals a distinct emphasis on signal purity over high-frequency fidelity, optimizing for matching rather than playback.

* **Signal Normalization via FFmpeg:** The function compute\_audio\_fingerprint invokes ffmpeg to create a normalized raw audio stream.  
  * **Mono Downmixing:** The \-ac 1 flag forces stereo or surround streams into a single channel. This is crucial because a duplicate video might drop a channel or mix 5.1 down to stereo; comparing mono signatures neutralizes these variances.  
  * **Resampling Strategy:** The code enforces a sample rate between 2,000 and 16,000 Hz (default 8,000 Hz). By discarding frequencies above 4 kHz (the Nyquist limit for 8 kHz sampling), the fingerprinter ignores high-frequency hiss or compression artifacts that often differ between encodings, focusing instead on the fundamental frequencies of speech and music.  
* **Windowing and Entropy:** The audio stream is sliced into temporal windows (default 3.0 seconds). Crucially, the code includes a chunk.strip(b"\\x00") check. This entropy filter discards digital silence. Without this, two completely different videos that both start with 5 seconds of silence would generate identical hashes for the silent period, leading to false positives.  
* **Hashing:** Each valid window is hashed using **BLAKE2b** (8-byte digest). This transforms the complex waveform data into a compact, mathematically comparable integer sequence.

#### **2.1.3 Cache Persistence Architecture (cache.py)**

The HashCache class employs a JSONL (JSON Lines) strategy.

* **Append-Only Integrity:** By writing each cache entry as a new line, the system mitigates data corruption risks associated with process interruptions. If the scan crashes, previous entries remain valid.  
* **Heterogeneous Storage:** The cache schema is polymorphic, storing sha256 strings, video\_meta dictionaries, and phash integer tuples in the same structure.  
* **Temporal Validity:** The \_key derivation uses (path, size, mtime). The inclusion of a tolerance check for mtime (modification time) handles cross-filesystem anomalies where timestamps might drift by a second (e.g., FAT32 vs. NTFS precision).

### **2.2 Interactive Visualization Layer: scripts/modules/termdash**

The termdash module, and specifically report\_viewer.py, constitutes the view layer of the application. It translates the abstract graph of duplicate relationships into a navigable list.

* **State Management:** The UI transitions between distinct states: "Group List" (Image 2\) and "Group Detail" (Image 3). This implies a state machine that tracks the currently focused node. When a user selects a master video, the view "drills down," retrieving the list of associated "loser" files (duplicates) from the GroupResults object.  
* **Selection Logic:** The UI implements a toggle mechanism (\[x\] vs \[ \]). This binary state determines which files are passed to the action handlers (e.g., deletion or, in our case, grid preview).  
* **Hierarchical Rendering:** The code references "hierarchical rendering," essential for visualizing the parent-child relationship between a "Master" video and its "Subset" clips. The master acts as the root of a local tree, with duplicates as leaves.

## **3\. Theoretical Framework for Similarity Scoring**

The user's request for a "researching report for scoring positively and negatively" touches on the fundamental challenge of deduplication: distinguishing signal from noise. A robust scoring algorithm cannot rely on a single metric; it must synthesize multiple evidence streams. We propose a composite confidence score, $C\_{final}$, derived from a weighted ensemble of positive indicators (evidence of sameness) and negative penalties (evidence of difference).

### **3.1 Positive Scoring Factors (Evidence of Identity)**

Positive factors contribute additively to the confidence score. They represent features that are statistically unlikely to match by random chance.

#### **3.1.1 Perceptual Visual Correlation ($S\_{visual}$)**

Standard cryptographic hashes are brittle; changing one bit changes the entire hash. Perceptual hashes (pHash) are continuous; similar images produce close hashes.

* **Algorithm:** Discrete Cosine Transform (DCT) based hashing. The image is resized to $32 \\times 32$, converted to grayscale, and processed via DCT. The low-frequency components (which represent the structural "shape" of the image) form the hash.  
* **Metric:** Normalized Hamming Distance. If $H\_A$ and $H\_B$ are the binary hash strings of two frames, the distance $D \= \\text{popcount}(H\_A \\oplus H\_B)$.  
* **Scoring Function:** $S\_{visual} \= 1 \- \\frac{D}{L}$, where $L$ is the hash length. A score of 1.0 implies identity; 0.8 implies strong similarity (e.g., re-encoded JPEG artifacts).

#### **3.1.2 Acoustic Fingerprint Alignment ($S\_{audio}$)**

Visuals can be heavily altered (color grading, cropping, watermarking) while audio often remains untouched.

* **Mechanism:** Comparison of the BLAKE2b integer sequences generated by audio.py.  
* **Metric:** Sequence Similarity Ratio. Using the Levenshtein distance or Longest Common Subsequence (LCS) algorithm on the audio hash tuples.  
* **Significance:** Audio matching is a "high-confidence anchor." It is extremely rare for two unrelated videos to share the exact same 3-second sequence of audio waveforms unless they are derived from the same source.

#### **3.1.3 Temporal Topology Match ($S\_{temporal}$)**

For subset detection, the *structure* of matches is as important as the matches themselves.

* **Mechanism:** Diagonal Streak Detection. If we construct a similarity matrix $M$ where $M\_{i,j} \= 1$ if Frame $A\_i \\approx Frame B\_j$, a true video overlap manifests as a diagonal line ($M\_{i,j}, M\_{i+1,j+1}, M\_{i+2,j+2}...$).  
* **Scoring:** The length of the longest continuous diagonal streak relative to the total duration. A 1000-frame continuous streak is definitive proof of duplication, whereas 1000 scattered matches might be coincidence.

### **3.2 Negative Scoring Factors (The "Veto" Penalties)**

Negative factors act as multipliers or penalties, reducing the confidence score when "suspicious" patterns are detected. These are critical for filtering false positives.

#### **3.2.1 The Low-Entropy Penalty ($P\_{entropy}$)**

* **Problem:** "Black Frame" False Positives. Many videos fade to black or contain title cards with solid backgrounds. A perceptual hash of a black frame is often a string of zeros. If Video A and Video B both have 10 seconds of silence/blackness, a naive algorithm will flag them as duplicates.  
* **Detection:** Calculate the pixel variance $\\sigma^2$ of the thumbnail before hashing. If $\\sigma^2 \< \\tau$ (threshold), tag the frame as "Low Information."  
* **Penalty:** If a match sequence consists primarily (\>50%) of Low Information frames, apply a severe penalty ($P\_{entropy} \\approx 0$).

#### **3.2.2 The Letterbox Veto ($P\_{aspect}$)**

* **Problem:** Converting 4:3 content to 16:9 often involves adding black bars (pillarboxing). A global pHash includes these black bars in the signature, causing the hash to diverge significantly from the original crop, potentially leading to a False Negative or a low score. Conversely, identifying the black bars as "content" can lead to False Positives between two different letterboxed videos.  
* **Mitigation:** Edge detection logic. If the system detects static borders, it should compute a secondary hash on the *center crop*. Significant divergence between the Full Hash match and the Center Crop match triggers a penalty or a "requires manual review" flag.

#### **3.2.3 Audio/Visual Dissonance ($P\_{dissonance}$)**

* **Problem:** Dubbed content or music videos. Two videos might share the exact same visual track but different audio (e.g., a movie dubbed in French vs. English).  
* **Penalty:** If $S\_{visual} \> 0.9$ but $S\_{audio} \< 0.2$, the system should flag this as a "Visual-Only Duplicate" rather than a full duplicate. This is crucial because the user likely wants to keep both language versions.

### **3.3 Composite Confidence Formula**

We propose the following scoring model to aggregate these factors:

$$C\_{final} \= \\left( \\alpha \\cdot S\_{visual} \+ \\beta \\cdot S\_{audio} \+ \\gamma \\cdot S\_{temporal} \\right) \\times (1 \- P\_{entropy}) \\times (1 \- P\_{dissonance})$$  
Where coefficients $\\alpha, \\beta, \\gamma$ sum to 1.0 and prioritize the most reliable signals (typically $\\gamma \> \\alpha \> \\beta$ due to the high certainty of temporal streaks).

## **4\. Technical Architecture of the Grid Preview System**

The implementation of the O key feature requires transforming vdedup from a file analyzer into a multimedia orchestrator. We leverage mpv for this task due to its powerful IPC (Inter-Process Communication) capabilities and CLI-driven geometry control.

### **4.1 Window Geometry and Layout Mathematics**

To render a "grid," we cannot rely on the operating system's window manager, which typically cascades or maximizes windows arbitrarily. We must explicitly calculate and enforce window coordinates.  
Assumption: A standard 1920x1080 display resolution.  
Objective: Tile up to 4 videos (Master \+ 3 Duplicates) in a 2x2 matrix.

| Quadrant | X Coordinate | Y Coordinate | Width | Height |
| :---- | :---- | :---- | :---- | :---- |
| Top-Left | 0 | 0 | $W\_{screen}/2$ | $H\_{screen}/2$ |
| Top-Right | $W\_{screen}/2$ | 0 | $W\_{screen}/2$ | $H\_{screen}/2$ |
| Bottom-Left | 0 | $H\_{screen}/2$ | $W\_{screen}/2$ | $H\_{screen}/2$ |
| Bottom-Right | $W\_{screen}/2$ | $H\_{screen}/2$ | $W\_{screen}/2$ | $H\_{screen}/2$ |

The mpv flag for this is \--geometry={width}x{height}+{x}+{y}. For example, the Top-Right window on a 1080p screen would use \--geometry=960x540+960+0.2

### **4.2 Synchronization via JSON-IPC**

Merely launching the videos is insufficient; they must play in sync. This is complicated by the "Subset" problem. If Duplicate B starts at timestamp 00:05:00 of Master A, launching both at 00:00:00 will result in temporal misalignment.  
**The Offset Algorithm:**

1. **Retrieve Match Metadata:** The sequence\_matcher.py module identifies the match\_start\_index for both files. Let $T\_{master}$ be the timestamp where the match begins in the master, and $T\_{dupe}$ be the timestamp in the duplicate.  
2. **Calculate Launch Parameters:**  
   * Master Launch: \--start={T\_{master}}  
   * Duplicate Launch: \--start={T\_{dupe}}  
3. **Real-Time Sync (IPC):** To keep them synced if the user seeks or pauses, we must establish a control loop.  
   * Each mpv instance is launched with \--input-ipc-server=/tmp/mpv\_socket\_{N}.  
   * A Python controller script (running within vdedup) connects to the Master's socket.  
   * Upon detecting a seek event or pause event in the Master, the controller iterates through all Slave sockets and sends the corresponding JSON command: {"command": \["seek", "{current\_time \+ offset}", "absolute"\]}.

### **4.3 Audio Conflict Resolution**

Playing four audio streams simultaneously renders the preview useless. The requirement is "only one audio at most playing."  
**Implementation Strategy:**

1. **Default State:** The Master instance is launched normally. All Duplicate instances are launched with the \--mute=yes flag.3  
2. **Dynamic Switching:** Using the IPC channel, the user can toggle focus. If the user clicks or selects a Duplicate window, the controller script sends {"command": \["set\_property", "mute", false\]} to that instance and true to all others. This ensures acoustic clarity while maintaining visual synchronicity.4

### **4.4 Proposed Implementation Logic for \_launch\_multi\_preview**

The following logic maps the requirements into a coherent function structure for report\_viewer.py.

Python

def \_launch\_multi\_preview(selected\_files, screen\_res=(1920, 1080)):  
    """  
    Orchestrates the grid launch of mpv players.  
    selected\_files: List of dicts containing 'path', 'match\_offset', 'is\_master'  
    """  
    import subprocess  
      
    \# Grid definitions for 2x2 layout  
    half\_w, half\_h \= screen\_res // 2, screen\_res // 2  
    positions \= \[  
        (0, 0), (half\_w, 0),  
        (0, half\_h), (half\_w, half\_h)  
    \]  
      
    ipc\_sockets \=  
    processes \=  
      
    for i, file\_data in enumerate(selected\_files\[:4\]): \# Limit to 4  
        \# 1\. Geometry Calculation  
        x, y \= positions\[i\]  
        geometry\_arg \= f"--geometry={half\_w}x{half\_h}+{x}+{y}"  
          
        \# 2\. IPC Setup  
        socket\_path \= f"/tmp/vdedup\_ipc\_{i}"  
        ipc\_sockets.append(socket\_path)  
          
        \# 3\. Audio & Sync Configuration  
        cmd \= \[  
            "mpv",  
            file\_data\['path'\],  
            geometry\_arg,  
            f"--start={file\_data\['match\_offset'\]}", \# Critical for subset sync  
            f"--input-ipc-server={socket\_path}",  
            "--hr-seek=yes", \# Precise seeking  
            "--title=vdedup\_preview"  
        \]  
          
        \# Master gets audio; others muted  
        if not file\_data\['is\_master'\]:  
            cmd.append("--mute=yes")  
          
        \# 4\. Process Launch  
        p \= subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  
        processes.append(p)  
          
    return processes, ipc\_sockets

This implementation directly satisfies the requirement for a grid layout, synchronized start times based on match offsets, and single-source audio playback.

## **5\. Performance and Scalability Analysis**

Implementing these features introduces specific load considerations.

* **CPU/GPU Decoding:** Decoding 4 concurrent video streams (especially 4K HEVC) is resource-intensive. vdedup should check for hardware acceleration support (--hwdec=auto in mpv) to offload this to the GPU. Without this, the grid preview may stutter, desynchronizing the visual comparison.  
* **Disk I/O:** Reading 4 streams simultaneously from a spinning hard disk (HDD) will likely cause thrashing and buffer underruns. The system should ideally pre-buffer or check if the source media is on SSD storage. If on HDD, the system might restrict the grid to 2 videos (side-by-side) to preserve playback fluidity.

## **6\. Future Directions: Semantic and Deep Learning Integration**

The current pHash and audio fingerprinting methods represent the state-of-the-art in *algorithmic* deduplication. However, the next frontier lies in *semantic* deduplication.

* **Deep Learning Embeddings:** Replacing DCT-based pHash with CNN-based feature vectors (e.g., using a ResNet-50 backbone) would allow the system to identify duplicates that have undergone severe transformations (e.g., camcorded copies, heavy cropping, or "reaction videos" where the original content is a small picture-in-picture overlay).  
* **Text Spotting (OCR):** Integrating Optical Character Recognition to read embedded text (subtitles, chyron banners). If two videos share unique textual strings at identical timestamps, the confidence score for duplication approaches 100%, regardless of visual noise.

## **7\. Conclusion**

The vdedup repository constitutes a robust framework for video deduplication, distinguished by its multi-stage pipeline and rigorous handling of complex scenarios like subset detection. The addition of the "Synchronized Grid Preview" is a high-value enhancement that bridges the gap between automated probability and human verification.  
By implementing the grid system using mpv's geometry and IPC features, and by adopting the proposed Composite Confidence Score—which rigorously penalizes low-entropy false positives while rewarding temporal structural alignment—the system can achieve a level of precision suitable for archival-grade data management. This synthesis of algorithmic rigor (backend hashing) and ergonomic verification (frontend grid preview) positions vdedup as a premiere solution in the multimedia management domain.

#### **Works cited**

1. mpv(1) \- Arch manual pages, accessed December 31, 2025, [https://man.archlinux.org/man/mpv.1](https://man.archlinux.org/man/mpv.1)  
2. How do I mute videos by default in MPV \- Ask Ubuntu, accessed December 31, 2025, [https://askubuntu.com/questions/1434815/how-do-i-mute-videos-by-default-in-mpv](https://askubuntu.com/questions/1434815/how-do-i-mute-videos-by-default-in-mpv)  
3. How can I control mpv in command line? \- Unix & Linux Stack Exchange, accessed December 31, 2025, [https://unix.stackexchange.com/questions/664728/how-can-i-control-mpv-in-command-line](https://unix.stackexchange.com/questions/664728/how-can-i-control-mpv-in-command-line)
