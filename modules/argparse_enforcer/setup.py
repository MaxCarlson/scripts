from setuptools import setup, find_packages

setup(
    name="argparse-enforcer",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "argparse",
        "argcomplete",
    ],
    python_requires=">=3.7",
    author="",
    description="Argparse wrapper enforcing strict argument naming conventions",
    long_description=open("README.md").read() if __file__ else "",
    long_description_content_type="text/markdown",
)
