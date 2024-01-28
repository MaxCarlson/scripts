# Function to execute a command and check for errors
execute_command() {
    echo "Running: $1"
    eval "$1"
    if [ $? -ne 0 ]; then
        echo "Error encountered running '$1'"
        return 1
    fi
    echo "-------------------------------------------------"
}


# Check if python and python3 are the same
python_version=$(python --version 2>&1)
python3_version=$(python3 --version 2>&1)
pip_version=$(pip --version 2>&1)
pip3_version=$(pip3 --version 2>&1)

python_version_num=$(python --version 2>&1 | awk '{print $2}')
python3_version_num=$(python3 --version 2>&1 | awk '{print $2}')
pip_version_num=$(pip --version 2>&1 | awk '{print $2}')
pip3_version_num=$(pip3 --version 2>&1 | awk '{print $2}')

PYTHON_ONLY_COMMANDS_LIST=("python")
if [ "$python_version_num" != "$python3_version_num" ]; then
    echo "python and python3 versions differ!"
    PYTHON_ONLY_COMMANDS_LIST+=("python3")
fi


PIP_ONLY_COMMANDS_LIST=("pip")
if [ "$pip_version_num" != "$pip3_version_num" ]; then
    echo "pip and pip3 versions differ"
    PIP_ONLY_COMMANDS_LIST=("pip3")
fi

PYPIP_COMMANDS_LIST+=("${PYTHON_ONLY_COMMANDS_LIST[@]}" "${PIP_ONLY_COMMANDS_LIST[@]}")


# List of commands
ListOfCommandsForCheckingPythonEnv=(
    'which ${PYPIP_COMMANDS_LIST[@]}'
    '${PYPIP_COMMANDS_LIST[@]/%/ --version}'
    'pyenv which ${PYPIP_COMMANDS_LIST[@]}'
    '${PIP_ONLY_COMMANDS_LIST[@]/%/ list}'
    '${PYTHON_ONLY_COMMANDS_LIST[@]/%/ -c "import platform; print(platform.python_compiler())"}'
    "alias | grep python"
    "env | grep PYTHON"
    "pyenv versions"
    "which virtualenv"
    "uname -a"
    '${PYTHON_ONLY_COMMANDS_LIST[@]/%/ -m sysconfig} | grep -E "Python version|Platform|base=|stdlib=|purelib=|platlib=|include=|scripts=|CC=|CFLAGS=|CPPFLAGS=|LDFLAGS=|SO=|EXT_SUFFIX=|LDSHARED=|CONFIG_ARGS="'
)

# Execute each command
for i in "${ListOfCommandsForCheckingPythonEnv[@]}"; do
    echo "About to run command: $i"
    execute_command "$i" 
done

echo "Script execution completed."

