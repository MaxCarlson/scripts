#!/usr/bin/env python3
"""
convert_repo_to_pdf.py

Convert an MDX repo into one PDF via Pandoc, with real-time progress and stats.

Usage:
  python convert_repo_to_pdf.py \
    --source /path/to/repo \
    --output repo.pdf \
    [--engine pdflatex|xelatex|tectonic] \
    [--margin 1in] [--toc] [--verbose]

Prerequisites:
- Python 3.7+
- Pandoc on PATH
- Tectonic or TeX Live (for pdflatex/xelatex)
- tqdm (`pip install tqdm`)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from tqdm import tqdm

def strip_imports(mdx, md):
    pat = re.compile(r"^import .* from .*$")
    with open(mdx, 'r', encoding='utf-8') as src, open(md, 'w', encoding='utf-8') as dst:
        for line in src:
            if not pat.match(line):
                dst.write(line)

def find_mdx(root):
    for dp, _, fnames in os.walk(root):
        for f in fnames:
            if f.lower().endswith('.mdx'):
                yield os.path.join(dp, f)

def main():
    p = argparse.ArgumentParser(
        description="Convert an MDX repo to a single PDF with progress stats",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    p.add_argument('-s', '--source', required=True, help='Root directory of MDX repo')
    p.add_argument('-o', '--output', default='output.pdf', help='Output PDF file')
    p.add_argument('--engine', choices=['pdflatex','xelatex','tectonic'], default='pdflatex',
                   help='PDF engine to use')
    p.add_argument('--margin', default='1in', help='Page margin (e.g., 1in)')
    p.add_argument('--toc', action='store_true', help='Include table of contents')
    p.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    args = p.parse_args()

    # Verify engine
    if not shutil.which(args.engine):
        print(f"Error: PDF engine '{args.engine}' not found", file=sys.stderr)
        sys.exit(1)

    mdx_files = sorted(find_mdx(args.source))
    if not mdx_files:
        print("Error: No .mdx files found.", file=sys.stderr)
        sys.exit(1)

    generated_md = []
    total_bytes = 0

    # Preprocess files with progress bar
    for mdx in tqdm(mdx_files, desc="Preprocessing MDX files", unit="file", ncols=80):
        md = mdx[:-4] + '.md'
        strip_imports(mdx, md)
        generated_md.append(md)
        total_bytes += os.path.getsize(mdx)
        tqdm.write(f"Processed {mdx}: {(total_bytes/(1024*1024)):.2f} MB total")

    # Build pandoc command
    cmd = ['pandoc', '-s', f'--pdf-engine={args.engine}']
    if args.toc:
        cmd.append('--toc')
    cmd += ['-V', f'geometry:margin={args.margin}']
    cmd += generated_md + ['-o', args.output]

    if args.verbose:
        print("\nRunning Pandoc command:\n" + " ".join(cmd))

    # Execute pandoc
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        print(line, end='')
    proc.wait()
    if proc.returncode != 0:
        print(f"Pandoc failed with code {proc.returncode}", file=sys.stderr)
        sys.exit(proc.returncode)

    print(f"PDF generated at {args.output}")

    # Cleanup
    for md in generated_md:
        try:
            os.remove(md)
        except Exception:
            pass

if __name__ == '__main__':
    main()
