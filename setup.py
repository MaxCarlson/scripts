import os
import subprocess
import sys

try:
    import pkg_resources
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "setuptools"])
    import pkg_resources

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])


def is_tool(name):
    from shutil import which

    return which(name) is not None


# Check for necessary Python packages
required_packages = ["PyPDF2", "pdfminer.six", "pdf2image"]
for package in required_packages:
    try:
        dist = pkg_resources.get_distribution(package)
        print("{dist.key} ({dist.version}) is installed")
    except pkg_resources.DistributionNotFound:
        print("{package} is NOT installed")
        install(package)

# Check for necessary system utilities
required_utilities = ["poppler", "tesseract"]
for utility in required_utilities:
    if not is_tool(utility):
        print(f"{utility} is NOT installed")
        if "linux" in sys.platform:
            subprocess.run(["sudo", "apt-get", "install", utility], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["brew", "install", utility], check=False)
        elif sys.platform == "win32":
            print("Please install {} manually".format(utility))
            # On Windows, you can download the installer from the Tesseract GitHub page
            # and then add the Tesseract path to your system's PATH.
            # After installing, you can check if Tesseract is correctly installed and in your PATH
            # by running tesseract --version in your terminal.
            # If it's correctly installed, you should see the version information for Tesseract.
            # If you still see the error, you may need to restart your terminal or your computer for the changes to take effect.

# Set local Python version using pyenv
subprocess.run(["pyenv", "local", "3.12.1"])
