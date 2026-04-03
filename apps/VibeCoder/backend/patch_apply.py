import os
import re


def apply_patch_to_file(filename, patch):
    """Apply a unified diff patch to a file.
    Parses hunks from the unified diff and applies additions/removals."""
    try:
        with open(filename, encoding="utf-8") as f:
            original_lines = f.readlines()
    except FileNotFoundError:
        return f"Patch failed: file not found: {filename}"
    except Exception as e:
        return f"Patch failed: {e}"

    hunks = _parse_hunks(patch)
    if not hunks:
        return "Patch failed: no valid hunks found in patch"

    # Sort hunks by line number so reversing applies bottom-up correctly
    hunks.sort(key=lambda h: h["old_start"])

    # Apply hunks in reverse order so line numbers stay valid
    result_lines = list(original_lines)
    for hunk in reversed(hunks):
        start = hunk["old_start"] - 1  # Convert to 0-indexed
        # Remove old lines, insert new lines
        old_len = len(hunk["old_lines"])
        # Verify old lines match (fuzzy: strip trailing whitespace)
        actual = [l.rstrip('\n\r') for l in result_lines[start:start + old_len]]
        expected = [l.rstrip('\n\r') for l in hunk["old_lines"]]
        if actual != expected:
            # Try fuzzy match (ignore whitespace differences)
            actual_stripped = [l.strip() for l in actual]
            expected_stripped = [l.strip() for l in expected]
            if actual_stripped != expected_stripped:
                return f"Patch failed: hunk at line {hunk['old_start']} does not match file content"
        # Apply the hunk
        new_lines = [l + '\n' if not l.endswith('\n') else l for l in hunk["new_lines"]]
        result_lines[start:start + old_len] = new_lines

    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(filename) or '.', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.writelines(result_lines)
            os.replace(tmp, filename)
        except Exception:
            os.unlink(tmp)
            raise
        return "Patch applied successfully."
    except Exception as e:
        return f"Patch failed: {e}"


def _parse_hunks(patch):
    """Parse unified diff hunks from a patch string."""
    hunks = []
    hunk_header = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
    lines = patch.splitlines()
    i = 0
    while i < len(lines):
        m = hunk_header.match(lines[i])
        if m:
            old_start = int(m.group(1))
            old_lines = []
            new_lines = []
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.startswith('@@') or line.startswith('diff ') or line.startswith('---') or line.startswith('+++'):
                    break
                if line.startswith('-'):
                    old_lines.append(line[1:])
                elif line.startswith('+'):
                    new_lines.append(line[1:])
                elif line.startswith(' '):
                    old_lines.append(line[1:])
                    new_lines.append(line[1:])
                else:
                    # Context line without prefix (some models omit the space)
                    old_lines.append(line)
                    new_lines.append(line)
                i += 1
            hunks.append({
                "old_start": old_start,
                "old_lines": old_lines,
                "new_lines": new_lines,
            })
        else:
            i += 1
    return hunks
