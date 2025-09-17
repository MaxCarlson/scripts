# Obfuscator - Sensitive Data Anonymization Tool

`obfuscator` is a Python command-line tool designed to anonymize sensitive information within text or files. It can replace paths, usernames, machine names, and IP addresses with generic, non-identifying placeholders. Additionally, it supports custom glob and regex-based replacements for highly flexible data sanitization.

## Features

*   **Path Obfuscation**: Replaces file system paths (both Linux and Windows) with generic, depth-preserving placeholders.
    *   Supports full path obfuscation.
    *   Supports partial path obfuscation (replacing a specific segment of a path).
*   **Username Obfuscation**: Replaces common username patterns (e.g., `/home/user`, `C:\Users\user`) with a generic username.
*   **Machine Name Obfuscation**: Replaces the local machine's hostname with a generic machine name.
*   **IP Address Obfuscation**: Replaces IPv4 and IPv6 addresses with generic IP addresses.
*   **Custom Glob Replacements**: Allows users to define `search:replacement` pairs where `search` is a glob pattern. Useful for replacing specific file names or patterns.
*   **Custom Regex Replacements**: Provides powerful `pattern:replacement` pairs using regular expressions for advanced text manipulation.
*   **Configurable Defaults**: Default replacement texts for paths, usernames, machine names, and IPs can be customized via a JSON file.
*   **Input Flexibility**: Can process input directly from the command line or from a specified file.

## Installation

(Assuming Python 3 is installed)

```bash
# Navigate to the module directory
cd /data/data/com.termux/files/home/scripts/modules/obfuscator

# Install dependencies (if any, check requirements.txt)
# pip install -r requirements.txt
```

## Usage

```bash
python obfuscator.py <input_text_or_file> [options]
```

**Arguments:**

*   `<input_text_or_file>`: The text string to obfuscate, or the path to a file whose content should be obfuscated.

**Options:**

*   `-u`, `--obfuscate-user`: Enable username obfuscation.
*   `--obfuscate-ip`: Enable IP address obfuscation.
*   `--obfuscate-machine`: Enable machine name obfuscation (default: on).
*   `-p`, `--obfuscate-path`: Enable full path obfuscation.
*   `-pp <PARTIAL_PATH>`, `--partial-path <PARTIAL_PATH>`: Specify a part of a path to obfuscate. Only this segment will be replaced.
*   `--partial-path-case-sensitive`: Make partial path obfuscation case-sensitive (default: off).
*   `-r <PATTERN:REPLACEMENT> [<PATTERN:REPLACEMENT> ...]`, `--regex <PATTERN:REPLACEMENT> [...]`: Apply custom regex replacements. Example: `-r "errors-\d{8}:errors-REDACTED"`.
*   `-g <PATTERN:REPLACEMENT> [<PATTERN:REPLACEMENT> ...]`, `--glob <PATTERN:REPLACEMENT> [...]`: Apply custom glob replacements. Example: `-g "*.log:obfuscated.log"`.
*   `--default-texts <FILE_PATH>`: Path to a JSON file containing custom default replacement texts.

### Examples

**Obfuscate a string:**

```bash
python obfuscator.py "My path is /home/user/documents/secret.txt and my IP is 192.168.1.100"
# Expected (approximate) output:
# My path is /this/is/a/path/f1 and my IP is 192.168.0.1
```

**Obfuscate a file:**

```bash
# Assuming 'log.txt' contains sensitive data
python obfuscator.py log.txt --obfuscate-user --obfuscate-ip
```

**Custom regex replacement:**

```bash
python obfuscator.py "Error code: ABC-12345" -r "ABC-\d+:ERROR-CODE-REDACTED"
# Expected output:
# Error code: ERROR-CODE-REDACTED
```

**Custom default texts (default_texts.json):**

```json
{
    "path_prefix": ["my", "anon", "path"],
    "username": "anon_user",
    "machine": "anon_host",
    "ip_v4": "10.0.0.0",
    "ip_v6": "::1"
}
```

```bash
python obfuscator.py "/home/original_user/file.txt" --obfuscate-user --default-texts default_texts.json
# Expected output:
# /home/anon_user/file.txt
```
