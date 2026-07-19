#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预处理: 把 assets/ 下的文件改名成 日期_原文件名.ext。
日期从今天起依次每天 1 个(顺序无所谓); 已带日期前缀的跳过, 可重复跑。

用法:
  python3 rename_assets.py                 # 从今天起, 每天 1 个, 真改名
  python3 rename_assets.py --per-day 3     # 每天 3 个
  python3 rename_assets.py --start 2026-07-20
  python3 rename_assets.py --dry-run       # 只预览不改名
"""
import os, re, argparse, datetime
from collections import defaultdict

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "assets")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def log(*a):
    print(*a, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD (默认今天)")
    ap.add_argument("--per-day", type=int, default=1, help="每天分配几个文件 (默认1)")
    ap.add_argument("--dry-run", action="store_true", help="只预览不改名")
    args = ap.parse_args()

    start = (datetime.date.fromisoformat(args.start) if args.start
             else datetime.date.today())
    per_day = max(1, args.per_day)

    files = [f for f in sorted(os.listdir(ASSETS))
             if os.path.isfile(os.path.join(ASSETS, f)) and not DATE_RE.match(f)]
    log(f"[*] 待改名 {len(files)} 个 (已带日期前缀的跳过)")
    if not files:
        log("[*] 没有需要改名的文件")
        return

    buckets = defaultdict(list)
    for i, f in enumerate(files):
        day = start + datetime.timedelta(days=i // per_day)
        buckets[day.isoformat()].append(f)

    for day in sorted(buckets):
        for f in buckets[day]:
            new = f"{day}_{f}"
            dst = os.path.join(ASSETS, new)
            if os.path.exists(dst):
                base, ext = os.path.splitext(new)
                k = 1
                while os.path.exists(os.path.join(ASSETS, f"{base}_{k}{ext}")):
                    k += 1
                new = f"{base}_{k}{ext}"
                dst = os.path.join(ASSETS, new)
            if args.dry_run:
                log(f"  [dry] {f}  ->  {new}")
            else:
                os.rename(os.path.join(ASSETS, f), dst)
                log(f"  {f}  ->  {new}")
    log(f"\n=== 完成: 处理 {len(files)} 个, 起始 {start.isoformat()}, 每天 {per_day} 个 ===")


if __name__ == "__main__":
    main()
