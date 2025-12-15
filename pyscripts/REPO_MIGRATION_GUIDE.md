# Repository Path Migration Guide

## Problem

Your repositories are scattered across different machines:
- **Windows**: `C:\Users\mcarls\Repos\`
- **WSL**: `~/src/`
- **Termux**: `~` (home directory)

This creates messy environment variables and hardcoded paths across:
- PowerShell `$PROFILE` (hardlinked from `W11-powershell/Profiles/CustomProfile.ps1`)
- Zsh configs in `dotfiles/zsh_configs/`
- Shell scripts, Python scripts, and PowerShell scripts

## Recommendation: Unified Location

**Use `~/repos/` (lowercase) across ALL platforms**

### Why `~/repos/` (lowercase)?

1. ✅ **UNIX-friendly** - lowercase is conventional on Linux/macOS
2. ✅ **Short and memorable** - easier to type
3. ✅ **Cross-platform** - works on Windows, WSL, Termux, macOS
4. ✅ **Consistent** - same path structure everywhere

### Alternative Options

- `~/src/` - Good alternative if you prefer (already using on WSL)
- `~/projects/` - Another common choice

## Migration Strategy

### Phase 1: Analysis (Dry Run)

First, see what the script will change:

```bash
# On Windows (PowerShell)
python C:\Users\mcarls\src\scripts\pyscripts\migrate_repo_paths.py -t ~/repos --dry-run

# On WSL/Linux
python ~/src/scripts/pyscripts/migrate_repo_paths.py -t ~/repos --dry-run
```

This will show:
- Current repository locations detected
- All files containing path references
- What will be changed (without making changes)

### Phase 2: Backup & Apply

```bash
# Apply with automatic backup (RECOMMENDED)
python migrate_repo_paths.py -t ~/repos --apply --backup

# Apply without backup (NOT RECOMMENDED)
python migrate_repo_paths.py -t ~/repos --apply --no-backup
```

The script will:
1. Create timestamped backup: `~/.repo_migration_backup_YYYYMMDD_HHMMSS/`
2. Rewrite all detected files with new paths
3. Print summary of changes

### Phase 3: Physical Repository Move

After the script updates all references, manually move the repositories:

**On Windows:**
```powershell
# Create target directory
New-Item -Type Directory -Path "$HOME\repos" -Force

# Move repos (adjust as needed)
Move-Item "$HOME\src\scripts" "$HOME\repos\scripts"
Move-Item "$HOME\src\dotfiles" "$HOME\repos\dotfiles"
Move-Item "$HOME\src\W11-powershell" "$HOME\repos\W11-powershell"
```

**On WSL/Linux:**
```bash
# Create target directory
mkdir -p ~/repos

# Move repos
mv ~/src/scripts ~/repos/scripts
mv ~/src/dotfiles ~/repos/dotfiles
# W11-powershell might not exist on WSL
```

**On Termux:**
```bash
# Create target directory
mkdir -p ~/repos

# Move repos from home to repos/
mv ~/scripts ~/repos/scripts
mv ~/dotfiles ~/repos/dotfiles
```

### Phase 4: Verification

Test that everything works:

```bash
# Reload shell config
source ~/.zshrc  # or source ~/.bashrc

# Test cd aliases
cdd    # Should go to ~/repos/dotfiles
cds    # Should go to ~/repos/scripts

# On PowerShell, reload profile
. $PROFILE

# Test PowerShell functions
cdrs   # Should go to ~/repos
```

## What the Script Detects

The migration script automatically finds and updates:

### PowerShell Files (.ps1, .psm1)
- Environment variables: `$env:PWSH_REPO`, `$env:SCRIPTS_REPO`, `$env:DOTFILES_REPO`
- Global variables: `$global:SCRIPTS`, `$global:DOTFILES_REPO`
- Hardcoded paths in functions, aliases, and configurations
- Path patterns like `$HOME\Repos\scripts`, `$env:USERPROFILE\src\dotfiles`

### Shell Files (.sh, .bash, .zsh, rc files)
- Environment variables: `$DOTFILES`, `$SCRIPTS`, `$PROJECTS`
- Export statements: `export SCRIPTS=...`
- Hardcoded paths in functions and aliases
- Path patterns like `~/src/scripts`, `$HOME/Repos/dotfiles`

### Python Files (.py)
- Path constants and variables
- Hardcoded path strings

## Files Currently Affected

The script detected **108 references** across **35 files**:

### PowerShell (22 files)
- `W11-powershell/Profiles/CustomProfile.ps1` - Main profile (hardlinked to $PROFILE)
- `W11-powershell/Enviornment/env.ps1` - Environment setup
- Various setup and utility scripts

### Shell (11 files)
- `dotfiles/zsh_configs/*.zsh` - Zsh configurations
- `dotfiles/setup*.sh` - Setup scripts
- `dotfiles/symlinked/home/zshrc` - Main zshrc

### Python (2 files)
- Module configurations with hardcoded paths

## Safety Features

The script includes:

1. **Dry-run mode** - See changes without applying (`--dry-run`)
2. **Automatic backups** - Timestamped backups before changes (`--backup`)
3. **Verbose mode** - Detailed logging (`-v`)
4. **Confirmation prompt** - Must type "yes" to proceed (unless dry-run)

## Rollback

If something goes wrong:

```bash
# Backups are in ~/.repo_migration_backup_TIMESTAMP/

# To restore a file:
cp ~/.repo_migration_backup_20250101_123456/path/to/file ~/path/to/file

# To restore everything:
# Find your backup directory
ls -la ~/.repo_migration_backup_*

# Then manually restore files from that directory
```

## Script Options

```bash
migrate_repo_paths.py -t TARGET [OPTIONS]

Required:
  -t, --target PATH     Target directory (e.g., ~/repos)

Options:
  -n, --dry-run         Show changes without applying
  -b, --backup          Create backup before changes (default: True)
  --no-backup           Skip backup (not recommended)
  --apply               Actually apply changes (required)
  -v, --verbose         Verbose output

Examples:
  # Preview changes
  python migrate_repo_paths.py -t ~/repos --dry-run

  # Apply with backup
  python migrate_repo_paths.py -t ~/repos --apply

  # Apply without backup (dangerous!)
  python migrate_repo_paths.py -t ~/repos --apply --no-backup

  # Verbose dry run
  python migrate_repo_paths.py -t ~/repos --dry-run -v
```

## Platform-Specific Notes

### Windows
- Uses backslash `\` in PowerShell files
- Updates `$HOME`, `$env:USERPROFILE` references
- Handles hardlinked `$PROFILE` properly

### WSL
- Uses forward slash `/` in shell files
- Updates `$HOME`, `~` references
- Works with both bash and zsh configs

### Termux
- Uses forward slash `/`
- May have repos directly in `~` instead of subdirectory
- Script handles this case

## Post-Migration Checklist

After running the migration:

- [ ] Physically move repositories to new location
- [ ] Test shell reload: `source ~/.zshrc` or `. ~/.bashrc`
- [ ] Test PowerShell reload: `. $PROFILE`
- [ ] Test cd aliases: `cdd`, `cds`, etc.
- [ ] Run a sample script from each repo
- [ ] Check environment variables: `echo $SCRIPTS`, `echo $DOTFILES`
- [ ] On PowerShell: `$env:SCRIPTS_REPO`, `$global:SCRIPTS_REPO`
- [ ] Verify git repositories still work after move
- [ ] Update any external tools/IDEs that reference old paths

## Troubleshooting

### Script can't find repositories
The script auto-detects by searching common locations. If repos aren't found:
- Ensure they exist at current locations
- Check the script's detection logic in `detect_current_locations()`

### References not detected
Some manual paths might not match patterns. Check:
- Symbolic links (script follows symlinks)
- Non-standard path formats
- Run with `-v` for verbose output

### After migration, things don't work
1. Check if repos were physically moved
2. Reload shell configs
3. Check backup directory for comparison
4. Verify paths in key files like `$PROFILE`, `.zshrc`

## Additional Notes

- The script uses the `cross_platform` module for platform detection
- It intelligently handles path separators (`\` vs `/`)
- Preserves file permissions and attributes
- Safe for git repositories (doesn't modify .git/)
- Can be run multiple times (idempotent on second run if paths unchanged)

## Support

For issues or questions:
1. Check the backup directory first
2. Run with `--dry-run -v` for detailed analysis
3. Review the script output for specific file errors
4. Manually verify critical files like `$PROFILE` and `.zshrc`
