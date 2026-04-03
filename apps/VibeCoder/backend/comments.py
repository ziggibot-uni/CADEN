import re
from typing import List, Dict, Optional

# --- Structured Comment Extraction, Compaction, Validation, Normalization ---

COMMENT_TAGS = [
    '@summary', '@why', '@depends', '@side_effects', '@entrypoints', '@data_flow', '@invariants', '@module', '@id', '@trust'
]

COMMENT_PATTERN = re.compile(r'#\s*(@\w+):\s*(.*)')

# Extract all structured comment blocks from a file

def extract_structured_comments(code: str) -> List[Dict[str, str]]:
    comments = []
    current = {}
    for line in code.splitlines():
        match = COMMENT_PATTERN.match(line)
        if match:
            tag, value = match.groups()
            current[tag] = value.strip()
        elif current:
            comments.append(current)
            current = {}
    if current:
        comments.append(current)
    return comments

# Compact comments to fit a token budget (simple char-based for now)
def compact_comments(comments: List[Dict[str, str]], max_chars: int) -> List[Dict[str, str]]:
    # Prioritize @why, @invariants, @entrypoints
    important = [c for c in comments if any(tag in c for tag in ('@why', '@invariants', '@entrypoints'))]
    others = [c for c in comments if c not in important]
    result = []
    total = 0
    for c in important + others:
        s = str(c)
        if total + len(s) > max_chars:
            break
        result.append(c)
        total += len(s)
    return result

# Validate and normalize comment format
def validate_and_normalize_comments(comments: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized = []
    for c in comments:
        norm = {k: v for k, v in c.items() if k in COMMENT_TAGS}
        # Add missing required tags as empty
        for tag in ['@summary', '@why']:
            if tag not in norm:
                norm[tag] = ''
        normalized.append(norm)
    return normalized

# Remove duplicate or stale comments by @id
def deduplicate_comments(comments: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    result = []
    for c in comments:
        cid = c.get('@id')
        if cid and cid in seen:
            continue
        if cid:
            seen.add(cid)
        result.append(c)
    return result

# Limit number of comment lines per file
def limit_comment_lines(comments: List[Dict[str, str]], max_lines: int) -> List[Dict[str, str]]:
    # Always keep high-value comments first
    prioritized = sorted(comments, key=lambda c: int('@why' in c or '@invariants' in c or '@entrypoints' in c), reverse=True)
    return prioritized[:max_lines]

# Trust level utilities
def set_trust_level(comments: List[Dict[str, str]], trust: str) -> List[Dict[str, str]]:
    """
    Set trust level for all comments. Trust can be 'fresh', 'stale', or 'verified'.
    """
    allowed = {'fresh', 'stale', 'verified'}
    trust = trust if trust in allowed else 'fresh'
    for c in comments:
        c['@trust'] = trust
    return comments

def update_trust_levels(old_comments: List[Dict[str, str]], new_comments: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Compare old and new comments by @id. If code changed but comment not updated, mark as 'stale'.
    If comment was re-derived from code, mark as 'verified'.
    If new comment, mark as 'fresh'.
    """
    old_by_id = {c.get('@id'): c for c in old_comments if c.get('@id')}
    for c in new_comments:
        cid = c.get('@id')
        if not cid:
            c['@trust'] = 'fresh'
            continue
        old = old_by_id.get(cid)
        if not old:
            c['@trust'] = 'fresh'
        elif c == old:
            c['@trust'] = old.get('@trust', 'stale')
        elif c.get('@summary') != old.get('@summary') or c.get('@why') != old.get('@why'):
            c['@trust'] = 'verified'
        else:
            c['@trust'] = 'stale'
    return new_comments

# Example usage (for testing)
if __name__ == "__main__":
    with open("example.py") as f:
        code = f.read()
    comments = extract_structured_comments(code)
    comments = validate_and_normalize_comments(comments)
    comments = deduplicate_comments(comments)
    comments = limit_comment_lines(comments, 20)
    comments = set_trust_level(comments, 'fresh')
    print(comments)
