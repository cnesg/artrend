import re
from pathlib import Path

files = list(Path("vault_curated/artists").glob("*.md"))
print(f"Total files in vault_curated/artists: {len(files)}")

# Check ID pattern
ids = []
for f in files[:10]:
    m = re.search(r'\(([0-9a-f]{8})\)\.md$', f.name)
    if m:
        ids.append((f.stem, m.group(1)))
print("Sample matched IDs:", ids[:5])
