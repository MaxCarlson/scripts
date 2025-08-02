# setup.py

from setuptools import setup, find_packages

setup(
    name="folder_util",
    version="0.1.0",
    description="A comprehensive folder and file utilities tool with rich CLI output",
    author="Your Name",
    author_email="your.email@example.com",
    packages=find_packages(),
    install_requires=[
        "rich>=10.0.0",
        # Optionally add other requirements, e.g., GitPython if needed.
    ],
    entry_points={
        "console_scripts": [
            "folder_util=folder_util.folder_util:main"
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)