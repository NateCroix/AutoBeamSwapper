"""
Targeted test for _identify_default_transmission() with transmissions_to_adapt: "single".

Tests two donors:
  1. testy623 — expects camso_transmission_58d60.jbeam (hash 58d60)
  2. persh_crayenne_moracc — expects camso_transmission_ec8ba.jbeam (hash ec8ba)

Both should skip the sequential variant.
"""
import sys
import logging
from pathlib import Path

# Setup logging to see method output
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Import from engineswap
from engineswap import EngineTransplantUtility

# Minimal construction — only base_vehicles_path and output_path needed
utility = EngineTransplantUtility(
    base_vehicles_path=Path("../SteamLibrary_content_vehicles"),
    output_path=Path("../output"),
    workspace_subfolder="test_single_trans",
)

MODS = Path("../mods/unpacked")

# ── Test 1: testy623 ──────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("TEST 1: testy623  (expect 58d60, skip sequential)")
print("=" * 72)

t623_engine = MODS / "testy623/vehicles/test_623/eng_28457/camso_engine_28457.jbeam"
t623_base   = MODS / "testy623/vehicles/test_623"
t623_trans   = sorted(t623_base.rglob("camso_transmission*.jbeam"))

print(f"\nEngine file : {t623_engine}")
print(f"Engine exists: {t623_engine.exists()}")
print(f"Trans files found ({len(t623_trans)}):")
for f in t623_trans:
    print(f"  - {f.relative_to(t623_base)}")

result1 = utility._identify_default_transmission(t623_engine, t623_trans)

print(f"\nReturned file: {result1}")
if result1:
    print(f"Returned name: {result1.name}")

# Assertions
seq_file_1 = t623_base / "camso_transmission_sequential.jbeam"
ok1_correct = result1 is not None and "58d60" in result1.name
ok1_skip    = result1 != seq_file_1

print(f"\n  ✓ Correct default (58d60)?  {'PASS' if ok1_correct else 'FAIL'}")
print(f"  ✓ Sequential skipped?       {'PASS' if ok1_skip else 'FAIL'}")

# ── Test 2: persh_crayenne_moracc ─────────────────────────────────────────────
print("\n" + "=" * 72)
print("TEST 2: persh_crayenne_moracc  (expect ec8ba, skip sequential)")
print("=" * 72)

pcm_engine = MODS / "persh_crayenne_moracc/vehicles/persh_crayenne_moracc/eng_3813e/camso_engine_3813e.jbeam"
pcm_base   = MODS / "persh_crayenne_moracc/vehicles/persh_crayenne_moracc"
pcm_trans  = sorted(pcm_base.rglob("camso_transmission*.jbeam"))

print(f"\nEngine file : {pcm_engine}")
print(f"Engine exists: {pcm_engine.exists()}")
print(f"Trans files found ({len(pcm_trans)}):")
for f in pcm_trans:
    print(f"  - {f.relative_to(pcm_base)}")

result2 = utility._identify_default_transmission(pcm_engine, pcm_trans)

print(f"\nReturned file: {result2}")
if result2:
    print(f"Returned name: {result2.name}")

seq_file_2 = pcm_base / "camso_transmission_sequential.jbeam"
ok2_correct = result2 is not None and "ec8ba" in result2.name
ok2_skip    = result2 != seq_file_2

print(f"\n  ✓ Correct default (ec8ba)?  {'PASS' if ok2_correct else 'FAIL'}")
print(f"  ✓ Sequential skipped?       {'PASS' if ok2_skip else 'FAIL'}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
all_pass = ok1_correct and ok1_skip and ok2_correct and ok2_skip
print(f"OVERALL: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
print("=" * 72)

sys.exit(0 if all_pass else 1)
