#!/usr/bin/env python3
"""Replace token symbols in MDX lesson files with <Token mint="..."> components.
Looks up mint addresses via the Jupiter datapi asset search endpoint."""
import json
import re
import glob
import sys
import subprocess
import urllib.parse
import time

KNOWN_MINTS = {
    "SOL": "So11111111111111111111111111111111111111112",
}

SYMBOLS_TO_PROCESS = [
    "SOL", "USDC", "USDT", "BTC", "ETH", "JUP", "JLP",
    "jupSOL", "JupUSD",
    "WBTC", "cbBTC",
    "jlWSOL", "jlUSDC",
]

API_BASE = "https://datapi.jup.ag/v1/assets/search"


def fetch_mint(symbol):
    """Look up a token's mint address from the Jupiter API.
    Picks the result whose symbol matches exactly AND has the highest organic score / is verified."""
    if symbol in KNOWN_MINTS:
        return KNOWN_MINTS[symbol]

    params = urllib.parse.urlencode({"query": symbol, "limit": 8, "searchFields": "symbol"})
    url = f"{API_BASE}?{params}"
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "10", url],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
    except Exception as e:
        print(f"  WARNING: API lookup failed for {symbol}: {e}")
        return None

    exact = [a for a in data if a.get("symbol") == symbol]
    if not exact:
        print(f"  WARNING: No exact symbol match for '{symbol}' in API results")
        return None

    verified = [a for a in exact if a.get("isVerified")]
    pool = verified if verified else exact
    pool.sort(key=lambda a: a.get("organicScore", 0), reverse=True)
    return pool[0]["id"]


def build_mint_map(symbols):
    mint_map = {}
    for sym in symbols:
        print(f"  Looking up {sym}...", end=" ", flush=True)
        mint = fetch_mint(sym)
        if mint:
            mint_map[sym] = mint
            print(f"{mint[:8]}...{mint[-4:]}")
        else:
            print("SKIPPED")
        time.sleep(0.15)
    return mint_map


def find_protected_regions(line):
    """Find regions that should not have token replacement."""
    regions = []
    for m in re.finditer(r'!?\[[^\]]*\]\([^\)]*\)', line):
        regions.append((m.start(), m.end()))
    for m in re.finditer(r'<[^>]+/?>', line):
        regions.append((m.start(), m.end()))
    for m in re.finditer(r'`[^`]+`', line):
        regions.append((m.start(), m.end()))
    for m in re.finditer(r'<Term[^>]*>.*?</Term>', line):
        regions.append((m.start(), m.end()))
    for m in re.finditer(r'<Token[^>]*>.*?</Token>', line):
        regions.append((m.start(), m.end()))
    return regions


def is_in_protected(start, end, regions):
    for rs, re_ in regions:
        if start < re_ and end > rs:
            return True
    return False


def is_valid_boundary(line, start, end):
    """Token must be preceded by whitespace/start/$ and followed by whitespace/punctuation/end."""
    if start > 0:
        prev = line[start - 1]
        if prev == '$':
            pass
        elif prev not in (' ', '\t', '(', '*'):
            return False
    if end < len(line):
        nxt = line[end]
        if nxt not in (' ', '.', ',', ')', ':', ';', '!', '?', '*', '\\', "'", '"'):
            return False
    return True


def replace_tokens_in_line(line, token_regex, mint_map):
    protected = find_protected_regions(line)
    matches = list(token_regex.finditer(line))
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

    filtered = []
    for m in valid:
        if not any(m.start() < e.end() and m.end() > e.start() for e in filtered):
            filtered.append(m)

    result = line
    for m in reversed(filtered):
        symbol = m.group(0)
        mint = mint_map.get(symbol)
        if not mint:
            continue
        s = m.start()
        # Strip leading $ if present
        if s > 0 and result[s - 1] == '$':
            s -= 1
        result = result[:s] + f'<Token mint="{mint}">{symbol}</Token>' + result[m.end():]

    return result


def process_mdx(filepath, token_regex, mint_map):
    with open(filepath, 'r') as f:
        lines = f.read().split('\n')

    in_frontmatter = False
    past_frontmatter = False
    in_code_block = False
    result = []
    replacements = 0

    for line in lines:
        stripped = line.strip()

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

        if stripped.startswith('```'):
            in_code_block = not in_code_block
            result.append(line)
            continue
        if in_code_block:
            result.append(line)
            continue

        if stripped.startswith('#'):
            result.append(line)
            continue

        if not stripped:
            result.append(line)
            continue

        new_line = replace_tokens_in_line(line, token_regex, mint_map)
        if new_line != line:
            replacements += 1
        result.append(new_line)

    with open(filepath, 'w') as f:
        f.write('\n'.join(result))

    return replacements


def main():
    symbols = SYMBOLS_TO_PROCESS
    if len(sys.argv) > 1:
        symbols = sys.argv[1:]

    print("Fetching mint addresses...")
    mint_map = build_mint_map(symbols)

    if not mint_map:
        print("No mint addresses found. Exiting.")
        return

    print(f"\nResolved {len(mint_map)}/{len(symbols)} tokens:")
    for sym, mint in mint_map.items():
        print(f"  {sym:>10} -> {mint}")

    # Build regex, longest symbols first for greedy match
    sorted_symbols = sorted(mint_map.keys(), key=len, reverse=True)
    escaped = [re.escape(s) for s in sorted_symbols]
    token_regex = re.compile('(' + '|'.join(escaped) + ')')

    mdx_files = sorted(glob.glob('lessons/*.mdx'))
    print(f"\nProcessing {len(mdx_files)} MDX files...")

    total = 0
    for fp in mdx_files:
        count = process_mdx(fp, token_regex, mint_map)
        if count:
            print(f"  {fp}: {count} lines modified")
        total += count

    print(f"\nDone! Modified {total} lines across {len(mdx_files)} files.")


if __name__ == '__main__':
    main()
