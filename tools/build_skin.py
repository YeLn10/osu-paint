"""Build the delivery skins; beatmap exports use the same builder."""

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from osu_paint_skin import build_skins


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 1–18K Pixel Film 常用屏幕比例皮肤")
    parser.add_argument("--rows", type=int, default=24, help="图案行数，默认 24；应用导出会自动匹配")
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("行数须为正整数")
    for path in build_skins(ROOT, args.rows):
        print(path)
