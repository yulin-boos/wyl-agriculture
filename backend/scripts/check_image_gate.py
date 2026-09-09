"""Check local images without running diagnosis, calling advice APIs or using a database."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crop_disease.image_gate import AgriculturalImageGate, GateSettings, ImageGateError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("images", nargs="+", type=Path)
args = parser.parse_args()
gate = AgriculturalImageGate(GateSettings.from_env(Path(__file__).resolve().parents[1]))
for path in args.images:
    try:
        result = gate.check(path)
    except ImageGateError as error:
        result = {"accepted": False, "code": error.code, "message": error.message}
    print(json.dumps({"image": str(path), **result}, ensure_ascii=False))
