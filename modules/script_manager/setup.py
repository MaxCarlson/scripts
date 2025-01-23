from setuptools import setup, find_packages

setup(
    name="script_manager",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        "console_scripts": [
            "create-module=script_manager.cli.create_module:main",
            "make-executable=script_manager.cli.make_executable:main"
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
