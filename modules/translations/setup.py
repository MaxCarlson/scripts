from pathlib import Path
from setuptools import setup, find_packages

README = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="translations",
    version="0.1.0",
    author="Max Carlson",
    author_email="mcarlson@example.com",
    description="Unified transcription and translation toolkit for media workflows",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/mcarls/scripts",
    packages=find_packages(include=["translations", "translations.*"]),
    python_requires=">=3.9",
    install_requires=[
        "typer>=0.9",
        "rich>=13.7",
        "pydantic>=2.6",
        "soundfile>=0.12",
        "numpy>=1.24",
    ],
    extras_require={
        "gpu": [
            "faster-whisper>=1.0",
        ],
        "translate": [
            "pykakasi>=2.3.1",
            "transformers>=4.35",
            "sentencepiece>=0.1.99",
        ],
        "openai": [
            "openai>=1.6.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "translations=translations.cli:main",
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
