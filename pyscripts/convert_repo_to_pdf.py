#!/usr/bin/env python3
"""
convert_repo_to_pdf.py

Convert a multi-language MDX repo into one PDF using Pandoc and Tectonic.

This script is optimized for robustness, handling Unicode characters by using
a CJK-compatible font and the xelatex engine mode. It also includes
real-time logging, resource path correction, and SSL/TLS handling.

Usage:
    # 1. Install a CJK font (see instructions in script header).
    # 2. Run the script:
    python convert_repo_to_pdf.py \
        --source /path/to/repo \
        --output repo.pdf \
        --strip-yaml --toc --verbose \
        --main-font "Noto Sans CJK KR" \
        --no-tls-verify

Prerequisites:
- Python 3.8+
- tqdm (`pip install tqdm`)
- Pandoc on PATH (`pkg install pandoc`)
- Tectonic installed (`pkg install tectonic`)
- A CJK font installed in Termux (`~/.termux/font.ttf`)
"""

import argparse
import os
import re
import subprocess
import sys
import shlex
from tqdm import tqdm

def preprocess_file(mdx_path, md_path, strip_yaml_front_matter):
    """
    Strips MDX imports and, if requested, any line that could be
    misinterpreted as a document separator by pandoc.
    """
    import_pattern = re.compile(r"^import .* from .*$")
    separator_pattern = re.compile(r"^\s*---\s*$")

    with open(mdx_path, 'r', encoding='utf-8') as fin, \
         open(md_path, 'w', encoding='utf-8') as fout:
        for line in fin:
            if import_pattern.match(line):
                continue
            if strip_yaml_front_matter and separator_pattern.match(line):
                continue
            fout.write(line)

def find_mdx_files(root_dir):
    """Yields all .mdx file paths found recursively under a root directory."""
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.lower().endswith('.mdx'):
                yield os.path.join(dirpath, fname)

def run_pandoc(file_list, output_path, source_dir, args):
    """Builds and executes the Pandoc command with real-time output."""
    # Use xelatex engine for superior Unicode and font support
    cmd = ['pandoc', '--pdf-engine=xelatex']
    
    cmd.extend(['--resource-path', source_dir])
    
    if args.no_tls_verify:
        cmd.append('--tls-no-verify')
        
    # Set the main font for the document to one that supports CJK characters
    if args.main_font:
        cmd.extend(['-V', f'mainfont={args.main_font}'])
        # Also set sans and mono fonts for consistency in headings and code blocks
        cmd.extend(['-V', f'sansfont={args.main_font}'])
        cmd.extend(['-V', f'monofont=Noto Sans Mono']) # A good mono font

    cmd.extend(['-V', f'geometry:margin={args.margin}'])
    if args.toc:
        cmd.append('--toc')
    
    cmd.extend(file_list)
    cmd.extend(['-o', output_path])

    if args.verbose:
        print("\nRunning Pandoc command:\n" + shlex.join(cmd))

    print("\n--- Generating PDF with Pandoc/Tectonic (real-time log) ---")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
    
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
            
    return_code = process.poll()

    print("--- Pandoc process finished ---")
    if return_code != 0:
        print(f'❌ Pandoc failed with exit code {return_code}', file=sys.stderr)
        sys.exit(return_code)

    print(f'✅ PDF generated successfully at: {output_path}')


def main():
    parser = argparse.ArgumentParser(
        description="Convert an MDX repo to a single PDF using Pandoc/Tectonic.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-s', '--source', required=True, help='Root directory of the MDX repository')
    parser.add_argument('-o', '--output', default='output.pdf', help='Output PDF filename')
    
    parser.add_argument('--margin', default='1in', help='Page margin for PDF (e.g., "1in", "2.5cm").')
    parser.add_argument('--strip-yaml', action='store_true', help='Strip YAML front matter and horizontal rules. Highly recommended.')
    parser.add_argument('--no-tls-verify', action='store_true', help='Disable SSL/TLS certificate verification for downloading remote images.')
    parser.add_argument('--main-font', default='Noto Sans CJK KR', help='Main font to use for PDF rendering. Must support all characters in the repo.')

    parser.add_argument('--toc', action='store_true', help='Include a table of contents.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output for debugging')
    parser.add_argument('--no-cleanup', action='store_true', help='Do not delete intermediate .md files after conversion')
    args = parser.parse_args()

    all_mdx_files = sorted(list(find_mdx_files(args.source)))

    if not all_mdx_files:
        print(f"Error: No .mdx files found in '{args.source}'", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Found {len(all_mdx_files)} .mdx files to process.")

    generated_md_files = []
    total_bytes_processed = 0
    try:
        with tqdm(all_mdx_files, desc="Preprocessing files", unit="file", ncols=100) as pbar:
            for mdx_path in pbar:
                short_name = os.path.basename(mdx_path)
                pbar.set_description(f"Processing {short_name}")

                md_path = mdx_path[:-4] + '.md'
                preprocess_file(mdx_path, md_path, args.strip_yaml)
                generated_md_files.append(md_path)

                file_size = os.path.getsize(mdx_path)
                total_bytes_processed += file_size
                pbar.set_postfix_str(f"{total_bytes_processed / (1024*1024):.2f} MB")

        run_pandoc(generated_md_files, args.output, args.source, args)

    finally:
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
