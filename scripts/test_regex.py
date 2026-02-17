#!/usr/bin/env python
"""Debug script to test the add_missing_commas regex patterns."""
import re

# Test string that should NOT be modified (already has commas)
test_with_commas = '["ec8ba_engine0", ["engine"], [], {"pos":{"x":-0.122839}}]'

# Test string missing comma (should be modified)
test_missing_comma = '["ec8ba_engine0" ["engine"], [], {"pos":{"x":-0.122839}}]'

print("Testing regex patterns from JBeamParser.add_missing_commas()")
print("=" * 60)

patterns = [
    (r'(?<![,])([0-9\]\}"])\s*(\{)', r"\1,\2"),
    (r'(?<![,])([0-9\]\}"])\s*(\[)', r"\1,\2"),
    (r'(?<![,])([0-9\]\}"])\s*(")', r"\1, \2"),
]

for name, test in [("WITH commas", test_with_commas), ("MISSING comma", test_missing_comma)]:
    print(f"\n{name}:")
    print(f"  Input: {test}")
    fixed = test
    for i, (pattern, replacement) in enumerate(patterns):
        before = fixed
        fixed = re.sub(pattern, replacement, fixed)
        if before != fixed:
            print(f"  Pattern {i+1} changed to: {fixed}")
    print(f"  Final: {fixed}")
