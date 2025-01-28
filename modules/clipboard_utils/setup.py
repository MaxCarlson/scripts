from setuptools import setup, find_packages

setup(
    name="clipboard_utils",
    version="1.0.0",
    description="Cross-platform clipboard utility for Python. Supports Android termux, pwsh, and Linux",                  author="Maxwell Carlson",
    author_email="carlsonamax@gmail.com",
    packages=find_packages(),
    python_requires=">=3.6",                                                         classifiers=[                                                                        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License"
    ]
)
