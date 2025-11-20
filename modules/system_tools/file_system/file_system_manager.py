import os
from ..core.system_utils import SystemUtils
from ..core.debug_utils import write_debug

class FileSystemManager(SystemUtils):
    """
    Provides cross-platform file system utilities.
    Includes operations for creating directories, deleting directories,
    and listing files within a directory.
    """

    def create_directory(self, path: str) -> bool:
        """
        Creates a directory at the specified path if it does not already exist.
        Returns True if the directory was created or already exists, False on error.
        """
        try:
            os.makedirs(path, exist_ok=True)
            write_debug(f"Directory created or already exists: {path}", channel="Information")
            return True
        except Exception as e:
            write_debug(f"Failed to create directory '{path}': {e}", channel="Error")
            return False

    def delete_directory(self, path: str) -> bool:
        """
        Deletes the directory at the specified path if it exists.
        Returns True if the directory was successfully deleted, False otherwise.
        """
        try:
            if os.path.isdir(path):
                os.rmdir(path)
                write_debug(f"Directory deleted: {path}", channel="Information")
                return True
            else:
                write_debug(f"Directory does not exist: {path}", channel="Warning")
                return False
        except Exception as e:
            write_debug(f"Failed to delete directory '{path}': {e}", channel="Error")
            return False

    def list_files(self, path: str):
        """
        Lists the files in the specified directory.
        Returns a list of file and directory names, or None if the path does not exist.
        """
        try:
            if os.path.exists(path):
                files = os.listdir(path)
                write_debug(f"Files in '{path}': {files}", channel="Debug")
                return files
            else:
                write_debug(f"Path does not exist: {path}", channel="Warning")
                return None
        except Exception as e:
            write_debug(f"Error listing files in '{path}': {e}", channel="Error")
            return None

