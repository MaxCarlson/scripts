from setuptools import setup, find_packages

setup(
    name="debug_utils",
    version="1.0.0",
    description="Cross-platform debug logging utility for Python.",
    author="Maxwell Carlson",
    author_email="carlsonamax@gmail.com",
    packages=find_packages(),
    python_requires=">=3.6",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License"
    ]
)
