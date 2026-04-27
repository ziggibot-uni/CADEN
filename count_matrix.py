import re

counts = {
    'covered': 0,
    'partial': 0,
    'uncovered': 0,
    'manual': 0,
    'eval': 0,
    'future': 0,
    'duplicate': 0
}

authoritative_rows = 0

with open('CADEN_testMatrix.md', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith('|'):
            continue
        
        # Split by pipe and remove empty strings from ends
        parts = [p.strip() for p in line.split('|') if p.strip() != '']
        if len(parts) < 5:
            continue
            
        id_val = parts[0]
        status = parts[4].lower()
        
        # Skip header rows
        if id_val.lower() == 'id' or id_val.startswith('---'):
            continue
            
        # Exclude EX-* rows
        if id_val.startswith('EX-'):
            continue
            
        authoritative_rows += 1
        
        if status in counts:
            counts[status] += 1

covered = counts['covered']
total = authoritative_rows
percentage = (covered / total * 100) if total > 0 else 0

for key in ['covered', 'partial', 'uncovered', 'manual', 'eval', 'future', 'duplicate']:
    print(f"{key}: {counts[key]}")
print(f"total: {total}")
print(f"percentage: {percentage:.2f}%")
