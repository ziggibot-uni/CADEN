# Patch-based editing utilities for agent
import difflib
from typing import List

def make_patch(original: str, modified: str, filename: str) -> str:
    """Return a unified diff patch string for a file."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)
    diff = difflib.unified_diff(orig_lines, mod_lines, fromfile=filename, tofile=filename)
    return ''.join(diff)

# Example usage:
if __name__ == "__main__":
    with open("example.py") as f:
        orig = f.read()
    # Simulate a change
    mod = orig.replace("foo", "bar")
    patch = make_patch(orig, mod, "example.py")
    print(patch)
