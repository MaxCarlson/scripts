#!/usr/bin/env python3
"""
convert_repo_to_pdf.py

Convert an MDX-based repo into one PDF using Pandoc + Tectonic.

This enhanced script includes progress tracking, verbose output, and automatic
cleanup of intermediate files.

Usage:
    python convert_repo_to_pdf.py \
        --source /path/to/Prompt-Engineering-Guide \
        --output Prompt-Engineering-Guide.pdf \
        [--margin 1in] [--toc] [--verbose]

Prerequisites:
- Python 3.8+ (for shlex.join)
- Pandoc on your PATH
- Tectonic installed (`pkg install tectonic` in Termux)
- tqdm library (`pip install tqdm`)
"""

import argparse
import os
import re
import subprocess
import sys
import shlex
from tqdm import tqdm

def strip_imports(mdx_path, md_path):
    """
    Strips MDX import lines from a file and writes the result as plain Markdown.
    
    Args:
        mdx_path (str): Path to the source .mdx file.
        md_path (str): Path to the destination .md file.
    """
    pattern = re.compile(r"^import .* from .*$")
    with open(mdx_path, 'r', encoding='utf-8') as fin, \
         open(md_path, 'w', encoding='utf-8') as fout:
        for line in fin:
            if not pattern.match(line):
                fout.write(line)

def find_mdx_files(root_dir):
    """
    Yields all .mdx file paths found recursively under a root directory.
    
    Args:
        root_dir (str): The directory to start searching from.
    
    Yields:
        str: The full path to an .mdx file.
    """
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.lower().endswith('.mdx'):
                yield os.path.join(dirpath, fname)

def main():
    parser = argparse.ArgumentParser(
        description="Convert an MDX repo to a single PDF via Tectonic",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-s', '--source', required=True,
                        help='Root directory of the MDX repository')
    parser.add_argument('-o', '--output', default='output.pdf',
                        help='Output PDF filename')
    parser.add_argument('--margin', default='1in',
                        help='Page margin for PDF (e.g., "1in", "2.5cm")')
    parser.add_argument('--toc', action='store_true',
                        help='Include a table of contents in the PDF')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output for debugging')
    parser.add_argument('--no-cleanup', action='store_true',
                        help='Do not delete intermediate .md files after conversion')
    args = parser.parse_args()

    # 1. Find all MDX files to get a total count for the progress bar
    all_mdx_files = list(find_mdx_files(args.source))

    if not all_mdx_files:
        print(f"Error: No .mdx files found in '{args.source}'", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Found {len(all_mdx_files)} .mdx files to process.")

    generated_md_files = []
    total_bytes_processed = 0
    try:
        # 2. Strip imports and create temporary .md files with progress tracking
        with tqdm(all_mdx_files, desc="Converting .mdx to .md", unit="file", ncols=100) as pbar:
            for mdx_path in pbar:
                short_name = os.path.basename(mdx_path)
                pbar.set_description(f"Processing {short_name}")

                md_path = mdx_path[:-4] + '.md'
                strip_imports(mdx_path, md_path)
                generated_md_files.append(md_path)

                # Update progress with file size
                file_size = os.path.getsize(mdx_path)
                total_bytes_processed += file_size
                pbar.set_postfix_str(f"{total_bytes_processed / (1024*1024):.2f} MB")

        generated_md_files.sort()

        # 3. Build the Pandoc command
        cmd = [
            'pandoc',
            '--pdf-engine=tectonic',
            '-V', f'geometry:margin={args.margin}'
        ]
        if args.toc:
            cmd.append('--toc')
        
        cmd.extend(generated_md_files)
        cmd.extend(['-o', args.output])

        if args.verbose:
            # shlex.join is the robust way to display a command for copy-pasting
            print("\nRunning Pandoc command:\n" + shlex.join(cmd))

        # 4. Run Pandoc, capturing output for better error reporting
        print(f"\nGenerating PDF with Pandoc/Tectonic... (This may take a while)")
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if res.returncode != 0:
            print(f'❌ Pandoc failed with exit code {res.returncode}', file=sys.stderr)
            print("\n--- Pandoc STDOUT ---", file=sys.stderr)
            print(res.stdout, file=sys.stderr)
            print("\n--- Pandoc STDERR ---", file=sys.stderr)
            print(res.stderr, file=sys.stderr)
            sys.exit(res.returncode)

        print(f'✅ PDF generated successfully at: {args.output}')

    finally:
        # 5. Clean up the intermediate .md files
        if not args.no_cleanup and generated_md_files:
            if args.verbose:
                print("\nCleaning up intermediate .md files...")
            for md_file in generated_md_files:
                try:
                    os.remove(md_file)
                except OSError as e:
                    print(f"Warning: Could not remove temporary file {md_file}: {e}", file=sys.stderr)

if __name__ == '__main__':
    main()
