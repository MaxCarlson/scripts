#!/bin/bash

# Set the desired Python version using pyenv
pyenv local 3.12.1

# Install pipreqs if not already installed
if ! command -v pipreqs &> /dev/null
then
    pip install pipreqs
fi

# Generate requirements.txt using pipreqs
pipreqs . --force

# Install the requirements
pip install -r requirements.txt --upgrade

# Call the Python setup script
python setup.py
#!/bin/bash

# Set the desired Python version using pyenv
pyenv local 3.12.1

# Install pipreqs if not already installed
if ! command -v pipreqs &> /dev/null
then
    pip install pipreqs
fi

# Generate requirements.txt using pipreqs
pipreqs . --force

# Check if requirements.txt has changed
if ! cmp -s requirements.txt requirements.txt.bak; then
    echo "New imports detected. Updating requirements.txt..."
    mv requirements.txt requirements.txt.bak
    pip install -r requirements.txt.bak --upgrade
fi

# Call the Python setup script
python setup.py
