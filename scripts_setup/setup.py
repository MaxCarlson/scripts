from setuptools import setup, find_packages

setup(
    name="scripts_setup_utils",  # ✅ Distinct package name
    version="1.0.0",
    packages=find_packages(),
    install_requires=[],
    description="Utility scripts for setting up the scripts repository",
)
