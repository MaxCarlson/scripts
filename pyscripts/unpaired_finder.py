import sys

def find_unpaired_braces(filepath):
    """
    Scans a file to find unpaired braces ({[]}) and lists line numbers
    of unpaired opening braces.

    Args:
        filepath (str): The path to the file to scan.

    Returns:
        tuple: A tuple containing:
            - list: A list of strings describing errors found (mismatches, extra closers).
            - list: A list of integers representing the line numbers of unpaired opening braces.
                   Returns None for both if the file cannot be opened.
    """
    opening_braces = {'(', '{', '['}
    closing_braces = {')', '}', ']'}
    pairs = {')': '(', '}': '{', ']': '['} # Maps closing to opening

    stack = []  # Stack will store tuples: (opening_brace_char, line_number)
    errors = [] # Stores error messages
    unpaired_opener_lines = [] # Stores line numbers of unpaired openers

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1): # Start line count from 1
                for col_num, char in enumerate(line, 1): # Start column count from 1
                    if char in opening_braces:
                        stack.append((char, line_num))
                    elif char in closing_braces:
                        if not stack:
                            errors.append(f"Error: Unpaired closing brace '{char}' found at line {line_num}, col {col_num}")
                        else:
                            expected_opener, opener_line_num = stack.pop()
                            if pairs[char] != expected_opener:
                                errors.append(
                                    f"Error: Mismatched closing brace '{char}' found at line {line_num}, col {col_num}. "
                                    f"Expected closing brace for '{expected_opener}' from line {opener_line_num}."
                                )
                                # Note: We popped the opener, but it didn't match.
                                # The script focuses on reporting the mismatch at the closer's position.
                                # Depending on logic, you might push the opener back or handle differently.
                                # For this requirement, just reporting the mismatch is sufficient.

            # After reading the whole file, check the stack
            # Any remaining items are unpaired opening braces
            while stack:
                opener, line_num = stack.pop()
                error_msg = f"Error: Unpaired opening brace '{opener}' found at line {line_num}"
                errors.append(error_msg)
                unpaired_opener_lines.append(line_num)

            # Sort the unpaired opener lines for clearer output
            unpaired_opener_lines.sort()

            return errors, unpaired_opener_lines

    except FileNotFoundError:
        print(f"Error: File not found at '{filepath}'")
        return None, None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None, None

# --- Main Execution ---
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scan_braces.py <filepath>")
        sys.exit(1)

    file_to_scan = sys.argv[1]
    found_errors, opener_lines = find_unpaired_braces(file_to_scan)

    if found_errors is not None: # Check if file processing was successful
        print(f"\n--- Scan Results for '{file_to_scan}' ---")

        if not found_errors:
            print("✅ No unpaired or mismatched braces found.")
        else:
            print("\nErrors Found:")
            for error in found_errors:
                print(f"- {error}")

            if opener_lines:
                print("\nLine numbers of unpaired OPENING braces:")
                print(opener_lines)
            else:
                # This case happens if errors were only mismatches or extra closers
                print("\nNo remaining unpaired OPENING braces (errors might be mismatches or extra closers).")

        print("\n--- End of Scan ---")
