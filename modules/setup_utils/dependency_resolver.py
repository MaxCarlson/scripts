#!/usr/bin/env python3
"""
Dependency resolver for local module installation.

Analyzes pyproject.toml/setup.py files to determine installation order
based on local module dependencies, preventing "module not found" errors.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Set, Optional
import re

try:
    import tomllib  # Py3.11+
except ImportError:
    try:
        import tomli as tomllib  # Py<=3.10
    except ImportError:
        print("[ERROR] tomli required for TOML parsing", file=sys.stderr)
        sys.exit(1)


class DependencyResolver:
    """Resolves local module dependencies and determines installation order."""

    def __init__(self, modules_dir: Path):
        self.modules_dir = modules_dir
        self.modules: Dict[str, ModuleInfo] = {}
        self.local_module_names: Set[str] = set()

    def discover_modules(self) -> None:
        """Discover all modules in the modules directory."""
        if not self.modules_dir.exists():
            return

        for entry in self.modules_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith('.'):
                continue

            pyproject = entry / "pyproject.toml"
            setup_py = entry / "setup.py"

            if pyproject.exists() or setup_py.exists():
                info = ModuleInfo(entry.name, entry, pyproject, setup_py)
                self.modules[info.name] = info

                # Get package name from metadata
                pkg_name = self._get_package_name(info)
                if pkg_name:
                    self.local_module_names.add(pkg_name)
                    info.package_name = pkg_name

    def analyze_dependencies(self) -> None:
        """Analyze dependencies for each module."""
        for module in self.modules.values():
            deps = self._extract_dependencies(module)

            # Filter to only local module dependencies
            for dep in deps:
                # Check if dependency is one of our local modules
                dep_base = dep.split('[')[0].split('>=')[0].split('==')[0].strip()
                if dep_base in self.local_module_names:
                    # Find which module provides this package
                    for other in self.modules.values():
                        if other.package_name == dep_base:
                            module.local_deps.add(other.name)
                            break

    def get_installation_order(self) -> List[str]:
        """
        Calculate installation order using topological sort.
        Returns list of module names in order they should be installed.
        """
        # Build adjacency list (reverse of dependencies)
        in_degree: Dict[str, int] = {name: 0 for name in self.modules}
        adj_list: Dict[str, List[str]] = {name: [] for name in self.modules}

        for module in self.modules.values():
            for dep_name in module.local_deps:
                if dep_name in self.modules:
                    adj_list[dep_name].append(module.name)
                    in_degree[module.name] += 1

        # Topological sort (Kahn's algorithm)
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # Sort alphabetically for deterministic output when multiple options
            queue.sort()
            current = queue.pop(0)
            result.append(current)

            for neighbor in adj_list[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for circular dependencies
        if len(result) != len(self.modules):
            remaining = set(self.modules.keys()) - set(result)
            raise ValueError(f"Circular dependency detected involving: {remaining}")

        return result

    def _get_package_name(self, module: ModuleInfo) -> Optional[str]:
        """Extract package name from pyproject.toml or setup.py."""
        if module.pyproject_path.exists():
            try:
                with open(module.pyproject_path, 'rb') as f:
                    data = tomllib.load(f)

                # Try project.name first
                if 'project' in data and 'name' in data['project']:
                    return data['project']['name']

                # Try poetry.name
                if 'tool' in data and 'poetry' in data['tool']:
                    return data['tool']['poetry'].get('name')
            except Exception:
                pass

        # Fallback: use directory name
        return module.name

    def _extract_dependencies(self, module: ModuleInfo) -> Set[str]:
        """Extract dependencies from pyproject.toml or setup.py."""
        deps: Set[str] = set()

        if module.pyproject_path.exists():
            deps.update(self._parse_pyproject_deps(module.pyproject_path))

        if module.setup_py_path.exists():
            deps.update(self._parse_setup_py_deps(module.setup_py_path))

        return deps

    def _parse_pyproject_deps(self, path: Path) -> Set[str]:
        """Parse dependencies from pyproject.toml."""
        deps: Set[str] = set()

        try:
            with open(path, 'rb') as f:
                data = tomllib.load(f)

            # Standard project.dependencies
            if 'project' in data and 'dependencies' in data['project']:
                deps.update(data['project']['dependencies'])

            # Poetry dependencies
            if 'tool' in data and 'poetry' in data['tool']:
                poetry_deps = data['tool']['poetry'].get('dependencies', {})
                for dep_name, dep_spec in poetry_deps.items():
                    if dep_name != 'python':  # Skip python version spec
                        if isinstance(dep_spec, str):
                            deps.add(f"{dep_name}{dep_spec}")
                        else:
                            deps.add(dep_name)
        except Exception:
            pass

        return deps

    def _parse_setup_py_deps(self, path: Path) -> Set[str]:
        """Parse dependencies from setup.py (basic regex extraction)."""
        deps: Set[str] = set()

        try:
            content = path.read_text(encoding='utf-8')

            # Look for install_requires or requires
            patterns = [
                r'install_requires\s*=\s*\[(.*?)\]',
                r'requires\s*=\s*\[(.*?)\]',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, content, re.DOTALL)
                for match in matches:
                    # Extract quoted strings
                    deps.update(re.findall(r'["\']([^"\']+)["\']', match))
        except Exception:
            pass

        return deps


class ModuleInfo:
    """Information about a module."""

    def __init__(
        self,
        name: str,
        path: Path,
        pyproject_path: Path,
        setup_py_path: Path
    ):
        self.name = name
        self.path = path
        self.pyproject_path = pyproject_path
        self.setup_py_path = setup_py_path
        self.package_name: Optional[str] = None
        self.local_deps: Set[str] = set()


def resolve_module_order(modules_dir: Path) -> List[str]:
    """
    Convenience function to resolve module installation order.

    Returns:
        List of module names in order they should be installed.
    """
    resolver = DependencyResolver(modules_dir)
    resolver.discover_modules()
    resolver.analyze_dependencies()
    return resolver.get_installation_order()


if __name__ == "__main__":
    # Test the resolver
    if len(sys.argv) > 1:
        modules_dir = Path(sys.argv[1])
    else:
        modules_dir = Path(__file__).parent.parent

    try:
        order = resolve_module_order(modules_dir)
        print("Installation order:")
        for i, name in enumerate(order, 1):
            print(f"  {i}. {name}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
