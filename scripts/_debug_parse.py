"""Temporary debug script to analyze parse errors in etk800 jbeam files. Reuse / refactor as needed for other files."""
import re, json, sys
from pathlib import Path

def strip_comments(content):
    content = content.replace('https://', '<<<HTTPS>>>')
    content = content.replace('http://', '<<<HTTP>>>')
    content = content.replace('file://', '<<<FILE>>>')
    content = re.sub(r'/\*[\s\S]*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    content = content.replace('<<<HTTPS>>>', 'https://')
    content = content.replace('<<<HTTP>>>', 'http://')
    content = content.replace('<<<FILE>>>', 'file://')
    return content

def add_missing_commas(content):
    """analyze_powertrains version (fewer patterns than engineswap)"""
    content = re.sub(r'(\]|})\s*?(\{|\[)', r'\1,\2', content)
    content = re.sub(r'(}|])\s*"', r'\1,"', content)
    content = re.sub(r'"\{', '", {', content)
    content = re.sub(r'"\s+("|\{)', r'",\1', content)
    content = re.sub(r'(false|true)\s+"', r'\1,"', content)
    content = re.sub(r',\s*,', r',', content)
    content = re.sub(r'("[a-zA-Z0-9_]*")\s(-?[0-9\[])', r'\1, \2', content)
    content = re.sub(r'(\d\.*\d*)\s*\{', r'\1, {', content)
    content = re.sub(r'([0-9])\n', r'\1,\n', content)
    content = re.sub(r'(-?[0-9])\s+(-?[0-9])', r'\1,\2', content)
    content = re.sub(r'([0-9])\s*("[a-zA-Z0-9_]*")', r'\1, \2', content)
    content = re.sub(r'("[a-zA-Z0-9_$.]*")\s*("[a-zA-Z0-9_$.]*")', r'\1, \2', content)
    return content

def remove_trailing_commas(content):
    lines = content.split('\n')
    result_lines = []
    for line in lines:
        for old, new in [(',,',','), ('[,','['), ('{,','{'), (',:', ':'), (',}', '}'), (',]', ']')]:
            line = line.replace(old, new)
        result_lines.append(line)
    content = '\n'.join(result_lines)
    content = re.sub(r',\s*?(]|})', r'\1', content)
    if content.rstrip().endswith(','):
        content = content.rstrip()[:-1]
    if content.count('{') != content.count('}'):
        if content.rstrip().endswith('}'):
            content = content.rstrip()[:-1]
    return content

def test_file(filepath):
    print(f"\n=== Testing: {Path(filepath).name} ===")
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Check for control characters
    for i, ch in enumerate(content):
        if ord(ch) < 32 and ch not in '\n\r\t':
            line_num = content[:i].count('\n') + 1
            col = i - content[:i].rfind('\n')
            print(f"  Control char \\x{ord(ch):02x} at line {line_num} col {col} (pos {i})")
    
    content = strip_comments(content)
    content = add_missing_commas(content)
    content = remove_trailing_commas(content)
    
    try:
        json.loads(content)
        print("  PARSED OK")
    except json.JSONDecodeError as e:
        print(f"  Error: {e.msg} at line {e.lineno} col {e.colno} (pos {e.pos})")
        start = max(0, e.pos - 120)
        end = min(len(content), e.pos + 80)
        ctx = content[start:end]
        marker_pos = e.pos - start
        print(f"  Context:")
        print(f"  ...{repr(ctx)}...")
        # Show the offending line
        all_lines = content.split('\n')
        if e.lineno <= len(all_lines):
            print(f"  Line {e.lineno}: {repr(all_lines[e.lineno-1])}")
            if e.lineno > 1:
                print(f"  Line {e.lineno-1}: {repr(all_lines[e.lineno-2])}")

# Test the two problematic files
base = r"M:\BeamNG_Modding_Temp\SteamLibrary_content_vehicles\etk800\vehicles\etk800"
test_file(f"{base}\\etk800_exhaust_i4_petrol.jbeam")
test_file(f"{base}\\etk800_interior.jbeam")
