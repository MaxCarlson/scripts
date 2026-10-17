"""Test-only bridge for existing engine vectors while the public CLI breaks cleanly.

Argument and top-level CLI tests exercise the production parser directly. The older
engine integration vectors here focus on scan, cache, codec, safety, and report
behavior, so this helper translates their former flat syntax into canonical commands.
"""

from compresser.cli import main as _main, run_comparison

__all__ = ["main", "run_comparison"]


_OPERATIONS = {"inventory", "plan", "estimate", "analyze", "compare", "preview", "apply", "recover"}


def main(argv):
    values = list(argv)
    if not values:
        return _main(values)
    if values and values[0] in _OPERATIONS:
        return _main(values)

    original = list(values)
    if "-R" in values or "-C" in values or "--confirm-recovery" in values:
        operation = "recover"
    elif "-l" in values or "-D" in values:
        operation = "inventory"
    elif "-O" in values:
        operation = "preview"
    elif "-b" in values or "-c" in values:
        operation = "compare"
    elif "-w" in values:
        operation = "apply"
    else:
        operation = "analyze"

    translated = [operation]
    index = 0
    while index < len(values):
        token = values[index]
        if token in ("-l", "-b", "-c", "-R"):
            index += 1
            continue
        if token == "-P" and index + 1 < len(values):
            translated.extend(("-s", values[index + 1] + "%"))
            index += 2
            continue
        if token == "-U" and index + 1 < len(values) and values[index + 1] == "trust":
            translated.extend((token, "snapshot"))
            index += 2
            continue
        value = {"-Q": "-q", "--qualities": "-q", "--confirm-recovery": "-C"}.get(token, token)
        if token == "-s" and index + 1 < len(values) and values[index + 1] == "auto":
            translated.extend((value, "all"))
            index += 2
            continue
        translated.append(value)
        index += 1

    if operation == "compare":
        if "-f" not in translated and "--format" not in translated:
            formats = ("png", "webp", "jpeg", "auto") if "-b" in original else ("webp", "jpeg", "auto")
            translated.extend(("-f", *formats))
        if "-b" in original and "-m" not in translated and "--mode" not in translated:
            translated.extend(("-m", "both"))
    if operation == "apply" and "-w" in original and "-m" in translated:
        mode_index = translated.index("-m") + 1
        if translated[mode_index] != "lossless" and "-L" not in translated:
            translated.append("-L")
    return _main(translated)
