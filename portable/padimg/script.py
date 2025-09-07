#!/usr/bin/env python3
"""
Pad an image to a target aspect ratio by adding even gray bars.

Examples:
  # classic: make a square into 4:5 (top/bottom bars)
  python pad_aspect.py in.jpg --ratio 4:5

  # 3:2 (side bars if needed)
  python pad_aspect.py in.png out.png --ratio 3:2

  # ratio as float or dimensions
  python pad_aspect.py in.jpg --ratio 0.8
  python pad_aspect.py in.jpg --ratio 1080x1350

Notes:
- No scaling or cropping of the original; we only pad.
- Chooses the minimal padding: tries vertical first (fix width),
  falls back to horizontal if height would need to shrink.
"""
import os, sys, argparse, math
from PIL import Image, ImageOps

def parse_ratio(s: str) -> float:
    s = s.strip().lower()
    if ":" in s:
        a, b = s.split(":")
        a, b = float(a), float(b)
        if a <= 0 or b <= 0: raise ValueError
        return a / b
    if "x" in s:
        a, b = s.split("x")
        a, b = float(a), float(b)
        if a <= 0 or b <= 0: raise ValueError
        return a / b
    r = float(s)
    if r <= 0: raise ValueError
    return r

def make_bg(gray: int, mode: str):
    gray = max(0, min(255, int(gray)))
    if mode in ("RGBA",):
        return (gray, gray, gray, 255)
    if mode in ("LA",):
        return (gray, 255)
    if mode == "L":
        return gray
    return (gray, gray, gray)

def main():
    ap = argparse.ArgumentParser(description="Pad an image to a target aspect ratio with gray bars.")
    ap.add_argument("input", help="Path to input image")
    ap.add_argument("output", nargs="?", help="Optional output path; defaults to *_padded.<ext>")
    ap.add_argument("--ratio", default="4:5", help="Target aspect ratio (W:H, float, or WxH). Default: 4:5")
    ap.add_argument("--gray", type=int, default=128, help="Gray level for bars (0–255). Default: 128")
    args = ap.parse_args()

    try:
        target_ratio = parse_ratio(args.ratio)
    except Exception:
        sys.exit("error: --ratio must be W:H, WxH, or a positive float (e.g., 4:5, 1080x1350, 0.8)")

    img = Image.open(args.input)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        # keep it simple; ensure we can paint a gray background deterministically
        img = img.convert("RGB")

    w, h = img.size
    # If already at target ratio (within 1px once padded), just compute minimal pad
    # Try vertical padding first (fix width). If that would require shrinking height, pad horizontally.
    new_h = math.ceil(w / target_ratio)
    if new_h >= h:
        pad_total = new_h - h
        pad_top = pad_total // 2
        pad_bottom = pad_total - pad_top
        canvas = Image.new(img.mode, (w, new_h), make_bg(args.gray, img.mode))
        canvas.paste(img, (0, pad_top))
    else:
        new_w = math.ceil(h * target_ratio)
        pad_total = new_w - w
        pad_left = pad_total // 2
        pad_right = pad_total - pad_left
        canvas = Image.new(img.mode, (new_w, h), make_bg(args.gray, img.mode))
        canvas.paste(img, (pad_left, 0))

    out_path = args.output
    if not out_path:
        stem, ext = os.path.splitext(args.input)
        ext = ext or ".jpg"
        out_path = f"{stem}_padded{ext}"

    # JPEG can't handle alpha
    if out_path.lower().endswith((".jpg", ".jpeg")) and canvas.mode in ("RGBA", "LA"):
        canvas = canvas.convert("RGB")

    canvas.save(out_path, quality=95)
    print(out_path)

if __name__ == "__main__":
    main()