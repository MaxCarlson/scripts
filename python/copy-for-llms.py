"""
Copy files based on specified name patterns and lists from an input folder to an output folder.

This script searches for files within a specified input folder, matching files based on a list of names 
and/or patterns, and copies them to a specified output folder. The script allows filtering files based 
on their extensions and can also ignore files with specified extensions when using patterns.

Usage:
    python copy_files.py -i <input_folder> -o <output_folder> -f <file_list> -p <pattern_list> -x <check_extensions_list> -e <ignore_extensions_list>

Examples:
    python copy_files.py -i /home/user/project -o /home/user/output -f "file1, file2" -p "java,cpp,partialFileName" -x ".txt,.java" -e ".mm,.c,.json"

Options:
    -i, --input-folder: Specifies the input folder where the script will search for files.
    -o, --output-folder: Specifies the output folder where the copied files will be placed.
    -f, --files: A comma-separated list of specific file names to copy.
    -p, --pattern: A comma-separated list of patterns to match in file names.
    -x, --check-extensions: A comma-separated list of extensions to allow. Only files with these extensions will be copied.
    -e, --ignore-ext: A comma-separated list of extensions to ignore when matching patterns. Files with these extensions will not be copied if they match the patterns.

Notes:
    - File names and patterns should be comma-separated without spaces unless the file names or patterns themselves contain spaces.
    - The script will preserve the relative paths of the copied files by adding them as prefixes to the file names.
    - Both the check extensions and ignore extensions lists should be provided without leading dots, as the script will handle them appropriately.
"""

# -type f \( -name "*.cpp" -o -name "*.h" -o -name "*.java" \) -exec bash -c 'for file; do echo -e "$(basename "$file")\t\t$(realpath --relative-to="/path/to/your/folder" "$file")"; done' bash {} + > output.txt

# Solitaire, RemoteConfig, JavascriptInterface, BrainiumApp, PauseManager, Native, ThreadHelper, jniLibraryIds, jniCallback, Renderer, Stats, UserTextureManager, Android, Main, Renderer, GLESBuffer, 
# GLESAttribute.h, GameView.cpp, Stats.h, GLES2IndexBuffer.cpp, GameStatView.h, Graphics.h, GameState.cpp, GLESFrameBuffer.h, RenderNode.h, TextureView.cpp, GLESBaseVertexBuffer.h, GLESObject.h, Texture.h, gl.h, GLES, App, Texture, Vert, TaskPool, Dirty, 
# Econ., CallbackGuard, performOnNextUpdate, Schedule


import argparse
import os
import shutil
import re

def main():
    parser = argparse.ArgumentParser(description="Copy files based on name patterns and lists.")
    parser.add_argument("-i", "--input-folder", required=True, help="Input folder to search for files.")
    parser.add_argument("-o", "--output-folder", required=True, help="Output folder to copy files to.")
    parser.add_argument("-f", "--files", help="Comma-separated list of file names to copy.")
    parser.add_argument("-p", "--pattern", help="Comma-separated list of patterns to match in file names.")
    parser.add_argument("-x", "--check-extensions", help="Comma-separated list of extensions to allow.")
    parser.add_argument("-e", "--ignore-ext", help="Comma-separated list of extensions to ignore when matching patterns.")

    args = parser.parse_args()

    input_folder = args.input_folder
    output_folder = args.output_folder
    files_to_copy = [file.strip() for file in args.files.split(",")] if args.files else []
    patterns_to_match = [pattern.strip() for pattern in args.pattern.split(",")] if args.pattern else []
    check_extensions = {ext.strip().lstrip('.') for ext in args.check_extensions.split(",")} if args.check_extensions else set()
    ignore_extensions = {ext.strip().lstrip('.') for ext in args.ignore_ext.split(",")} if args.ignore_ext else set()

    os.makedirs(output_folder, exist_ok=True)

    files_copied = 0

    def generate_prefixed_filename(relative_path, filename):
        """Generate a new filename with the relative path as a prefix."""
        relative_path = relative_path.replace(os.sep, "_")  # Replace path separators with underscores
        return f"{relative_path}_{filename}"

    def copy_file(source_path, relative_path, filename):
        """Copies a single file to the destination, with the relative path as a prefix to the filename."""
        nonlocal files_copied
        prefixed_filename = generate_prefixed_filename(relative_path, filename)
        destination_path = os.path.join(output_folder, prefixed_filename)
        try:
            shutil.copy2(source_path, destination_path)
            print(f"Copied: {source_path} to {destination_path}")
            files_copied += 1
        except Exception as e:
            print(f"Failed to copy {source_path} to {destination_path}: {e}")

    def extension_allowed(file):
        """Check if the file extension is in the allowed list if provided."""
        if check_extensions:
            file_extension = os.path.splitext(file)[1].lstrip('.')
            return file_extension in check_extensions
        return True

    if files_to_copy:
        for file_name in files_to_copy:
            for root, _, files in os.walk(input_folder):
                for file in files:
                    if os.path.splitext(file)[0] == file_name and extension_allowed(file):
                        relative_path = os.path.relpath(root, input_folder)
                        copy_file(os.path.join(root, file), relative_path, file)

    if patterns_to_match:
        for pattern in patterns_to_match:
            regex = re.compile(pattern)
            for root, _, files in os.walk(input_folder):
                for file in files:
                    file_extension = os.path.splitext(file)[1].lstrip('.')
                    if regex.search(file) and file_extension not in ignore_extensions and extension_allowed(file):
                        relative_path = os.path.relpath(root, input_folder)
                        copy_file(os.path.join(root, file), relative_path, file)

    print(f"Copied {files_copied} files to {output_folder}")

if __name__ == "__main__":
    main()