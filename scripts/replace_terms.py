#!/usr/bin/env python3
"""Replace glossary terms in MDX lesson files with <Term> components.
Case-sensitive, requires space/start before and space/dot/end after."""
import json
import re
import glob

# Load terms
with open('glossary/terms.json', 'r') as f:
    terms_data = json.load(f)

# Build term list with ids, sorted longest first
term_list = []
for t in terms_data:
    term = t['term']
    term_id = term.lower().replace(' ', '-')
    term_list.append((term, term_id))
term_list.sort(key=lambda x: -len(x[0]))

# Lookup from exact term text to term_id
term_lookup = {term: tid for term, tid in term_list}

# Build regex: case-sensitive, longest first
escaped = [re.escape(t[0]) for t in term_list]
pattern = '(' + '|'.join(escaped) + ')'
term_regex = re.compile(pattern)  # Case-sensitive


def is_valid_boundary(line, start, end):
    """Check: space/start before, space/dot/end after."""
    if start > 0 and line[start - 1] not in (' ', '\t'):
        return False
    if end < len(line) and line[end] not in (' ', '.'):
        return False
    return True


def find_protected_regions(line):
    """Find regions that should not have term replacement."""
    regions = []
    # Markdown links: [text](url) and images ![alt](url)
    for m in re.finditer(r'!?\[[^\]]*\]\([^\)]*\)', line):
        regions.append((m.start(), m.end()))
    # HTML/JSX tags
    for m in re.finditer(r'<[^>]+/?>', line):
        regions.append((m.start(), m.end()))
    # Inline code
    for m in re.finditer(r'`[^`]+`', line):
        regions.append((m.start(), m.end()))
    # Already-placed Term components
    for m in re.finditer(r'<Term[^>]*>.*?</Term>', line):
        regions.append((m.start(), m.end()))
    return regions


def is_in_protected(start, end, regions):
    for rs, re_ in regions:
        if start < re_ and end > rs:
            return True
    return False


def replace_terms_in_line(line):
    protected = find_protected_regions(line)
    matches = list(term_regex.finditer(line))
    if not matches:
        return line

    valid = []
    for m in matches:
        if is_in_protected(m.start(), m.end(), protected):
            continue
        if not is_valid_boundary(line, m.start(), m.end()):
            continue
        valid.append(m)

    if not valid:
        return line

    # Remove overlaps (keep first/longest)
    filtered = []
    for m in valid:
        if not any(m.start() < e.end() and m.end() > e.start() for e in filtered):
            filtered.append(m)

    # Replace right-to-left
    result = line
    for m in reversed(filtered):
        original = m.group(0)
        tid = term_lookup.get(original)
        if tid:
            result = result[:m.start()] + f'<Term id="{tid}">{original}</Term>' + result[m.end():]
    return result


def process_mdx(filepath):
    with open(filepath, 'r') as f:
        lines = f.read().split('\n')

    in_frontmatter = False
    past_frontmatter = False
    in_code_block = False
    result = []
    replacements = 0

    for line in lines:
        stripped = line.strip()

        # Frontmatter
        if stripped == '---':
            if not past_frontmatter:
                if not in_frontmatter:
                    in_frontmatter = True
                else:
                    in_frontmatter = False
                    past_frontmatter = True
            result.append(line)
            continue

        if in_frontmatter:
            result.append(line)
            continue

        # Code blocks
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            result.append(line)
            continue
        if in_code_block:
            result.append(line)
            continue

        # Headings
        if stripped.startswith('#'):
            result.append(line)
            continue

        # Empty
        if not stripped:
            result.append(line)
            continue

        new_line = replace_terms_in_line(line)
        if new_line != line:
            replacements += 1
        result.append(new_line)

    with open(filepath, 'w') as f:
        f.write('\n'.join(result))

    return replacements


# Process all MDX files
mdx_files = sorted(glob.glob('lessons/*.mdx'))
total = 0
for fp in mdx_files:
    count = process_mdx(fp)
    if count:
        print(f"  {fp}: {count} lines modified")
    total += count

print(f"\nDone! Modified {total} lines across {len(mdx_files)} files.")
