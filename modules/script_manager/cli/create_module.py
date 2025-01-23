import argparse
import sys
from pathlib import Path
from script_manager.modules import create_module_structure
from script_manager.env_setup import create_virtual_environment
from script_manager.utils import validate_python_name

def main():
    parser = argparse.ArgumentParser(description="Manage Python modules")
    parser.add_argument("-s", "--sources", type=str, required=True, help="Path to the module folder.")
    parser.add_argument("-n", "--name", type=str, help="Module name (required if outside the default modules path).")
    parser.add_argument("-m", "--modules_path", type=str, default="~/scripts/Modules",
                        help="Specify the base modules directory (default: ~/scripts/Modules).")
    parser.add_argument("--venv", action="store_true", help="Create a virtual environment for the module.")
    parser.add_argument("--conda", action="store_true", help="Create a Conda environment for the module.")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing files where necessary.")
    parser.add_argument("--no_requirements", action="store_true", help="Skip generating requirements.txt.")
    parser.add_argument("--no_test", action="store_true", help="Skip creating test setup.")
    parser.add_argument("-t", "--test", type=str, nargs="?", const="", help="Specify test source or create a blank test.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug output.")

    args = parser.parse_args()
    module_path = Path(args.sources).expanduser()
    DEFAULT_MODULES_PATH = Path(args.modules_path).expanduser()

    print(f"📂 Resolving module path: {module_path}")

    # Infer module name if inside specified modules path
    if module_path.resolve().parent == DEFAULT_MODULES_PATH.resolve():
        if args.name:
            sys.exit("❌ Error: Module name should not be specified when using a predefined module path.")
        module_name = module_path.name
    else:
        if not args.name:
            sys.exit("❌ Error: Module name is required when not using a predefined module path.")
        module_name = args.name

    print(f"📦 Module name determined: {module_name}")

    validate_python_name(module_name)
    print("✅ Module name validation passed.")

    # Call module structure creation
    print("🔨 Creating module structure...")
    create_module_structure(module_path, module_name, args.force, args.no_requirements, args.no_test, args.test)
    print("✅ Module structure created.")

    # Setup environment if requested
    if args.venv or args.conda:
        print("⚙️ Setting up virtual environment...")
        create_virtual_environment(module_path, module_name, args.conda, args.force)
        print("✅ Virtual environment setup complete.")

    print("🎉 Module creation complete.")

    # Debug mode: Show skipped actions and detailed steps
    if args.debug:
        print("\n🔍 Debug Info:")
        print(f"  - Source path: {module_path}")
        print(f"  - Modules path: {DEFAULT_MODULES_PATH}")
        print(f"  - Inferred module name: {module_name}")
        print(f"  - Virtual environment: {'Enabled' if args.venv else 'Disabled'}")
        print(f"  - Conda environment: {'Enabled' if args.conda else 'Disabled'}")
        print(f"  - Force overwrite: {'Yes' if args.force else 'No'}")
        print(f"  - Skip requirements.txt: {'Yes' if args.no_requirements else 'No'}")
        print(f"  - Skip tests: {'Yes' if args.no_test else 'No'}")
        print(f"  - Test source: {args.test if args.test else 'None'}")

if __name__ == "__main__":
    main()
