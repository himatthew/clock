#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
之江汇教育广场 · 资源「拆页批量上传」每日任务
------------------------------------------------
把 assets/ 下「当天日期前缀」的整本 PDF 拆成 一页一个 的 PDF,
逐页上传为独立资源(综合资源), 并发送微信提醒。

设计:
  * 拆页用纯 Python 的 pypdf(无需系统 poppler 依赖), 输出到
    assets/_pages/<日期>/<日期_曲名_P001>.pdf
  * 上传复用已逐项验证的 publish_resource_playwright.py --pages-dir(单浏览器循环)
  * 每页文件名带 _P<NNN> 后缀 -> resolve_pdf_asset 用 stem 当标题, 各页独立命名
  * 用 --no-variant: 每页内容不同, 自然 MD5 不同; 同页重传会被服务端去重(type=2), 幂等不重复
  * 微信提醒走 notify.py --resource-only(只显示 工作室/Cookie/资源)

依赖: 本机/服务器 venv 装 pypdf:  pip install pypdf

用法(通常由 split_upload_daily.sh 在 cron 调用):
  python3 split_upload_daily.py --cookie cookies.txt
  python3 split_upload_daily.py --cookie cookies.txt --date 2026-07-19 --dry-run
"""
import os
import re
import sys
import argparse
import subprocess
import datetime

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.stderr.write("ERROR: 缺少 pypdf, 请先 pip install pypdf\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "data", "assets")
START_DATE = "2026-07-19"  # 启动日守卫(与 run_daily.sh 一致)


def log(*a):
    print(*a, flush=True)


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def find_today_pdf(date):
    """返回 assets/ 下当天日期前缀的 PDF(取第一个, 按名排序)。无则 None。"""
    prefix = date + "_"
    pdfs = sorted(
        f for f in os.listdir(ASSETS)
        if f.startswith(prefix) and f.lower().endswith(".pdf")
    )
    return os.path.join(ASSETS, pdfs[0]) if pdfs else None


def split_pdf(src, date):
    """拆成 一页一个 PDF, 写入 assets/_pages/<date>/, 返回 [(页码, 路径)]。"""
    stem = os.path.splitext(os.path.basename(src))[0]
    out_dir = os.path.join(ASSETS, "_pages", date)
    os.makedirs(out_dir, exist_ok=True)
    reader = PdfReader(src)
    n = len(reader.pages)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        w = PdfWriter()
        w.add_page(page)
        out = os.path.join(out_dir, f"{stem}_P{i:03d}.pdf")
        with open(out, "wb") as f:
            w.write(f)
        pages.append((i, out))
    return n, pages


def parse_upload_result(out):
    """从 publish_resource_playwright.py 输出解析 成功/失败/共。"""
    m = re.search(r"=== 完成:\s*成功\s*(\d+)\s*/\s*失败\s*(\d+)\s*/\s*共\s*(\d+)\s*===", out)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    # 兜底: 统计 type=1 / 失败标记
    ok = len(re.findall(r"✅ 提交成功 \(type=1\)", out))
    fail = len(re.findall(r"(⚠️|❓|\[!\] 上传失败)", out))
    return ok, fail, ok + fail


def main():
    ap = argparse.ArgumentParser(description="资源拆页批量上传(每日)")
    ap.add_argument("--cookie", default="cookies.txt", help="cookies.txt 路径")
    ap.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD(默认当天)")
    ap.add_argument("--dry-run", action="store_true", help="只拆页并打印计划, 不上传不推送")
    ap.add_argument("--no-notify", action="store_true", help="上传但不发微信")
    args = ap.parse_args()

    date = args.date or today_str()

    # 启动日守卫
    if date < START_DATE:
        log(f"[跳过] 未到启动日 {START_DATE} (今天 {date})")
        sys.exit(0)

    # 1) 找当天 PDF
    src = find_today_pdf(date)
    if not src:
        msg = f"assets/ 下没有匹配当天({date})的 PDF 文件"
        log(f"[!] {msg}")
        if not args.no_notify and not args.dry_run:
            subprocess.run([
                sys.executable, os.path.join(HERE, "notify.py"), "--date", date,
                "--cookie-status", "成功", "--upload-status", "失败",
                "--resource-only", "--resources", "无",
                "--headline", "失败～毛毛小主 未找到可上传的PDF",
                "--title", "失败～毛毛小主 未找到可上传的PDF",
                "--detail", msg,
            ], cwd=HERE)
        sys.exit(1)

    log(f"[*] 找到当日 PDF: {os.path.basename(src)}")

    # 2) 拆页
    n, pages = split_pdf(src, date)
    log(f"[*] 拆出 {n} 页 -> assets/_pages/{date}/")
    for i, p in pages:
        log(f"    P{i:03d}  {os.path.basename(p)}")

    if args.dry_run:
        log("[dry-run] 跳过上传与推送")
        sys.exit(0)

    # 3) 批量上传(单浏览器循环, --no-variant 幂等)
    # cookie 相对路径按「项目根(HERE 的上级)」解析(脚本不 chdir, 始终以项目根为基准)
    cookie = args.cookie if os.path.isabs(args.cookie) \
        else os.path.join(os.path.dirname(HERE), args.cookie)
    if not os.path.exists(cookie) or os.path.getsize(cookie) == 0:
        log("[!] cookies.txt 缺失或为空, 上传很可能失败")
    pages_dir = os.path.join(ASSETS, "_pages", date)
    cmd = [sys.executable, os.path.join(HERE, "publish_resource_playwright.py"), cookie,
           "--pages-dir", pages_dir, "--no-variant"]
    log(f"[*] 调用上传: {' '.join(cmd)}")
    p = subprocess.Popen(cmd, cwd=HERE, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out_lines = []
    assert p.stdout is not None
    for line in p.stdout:        # 实时转发, 排障可见进度
        print(line, end="", flush=True)
        out_lines.append(line)
    p.wait()
    out = "".join(out_lines)     # 已实时打印, 无需再 log(out)

    ok, fail, total = parse_upload_result(out)
    log(f"[*] 上传结果: 成功 {ok} / 失败 {fail} / 共 {total}")

    # 4) 微信提醒
    cookie_ok = os.path.exists(cookie) and os.path.getsize(cookie) > 0
    cookie_status = "成功" if cookie_ok else "失败"
    upload_ok = (fail == 0 and ok > 0)
    upload_status = "成功" if upload_ok else "失败"
    stem = os.path.splitext(os.path.basename(src))[0]
    res_name = re.sub(r"^" + re.escape(date) + r"_", "", stem)  # 去日期前缀
    resources_label = f"{res_name} ({n}页)"
    detail = (f"拆分 {n} 页, 上传成功 {ok} / 失败 {fail} / 共 {total}\n"
              + "\n".join(out.strip().splitlines()[-15:]))

    if not args.no_notify:
        if upload_ok:
            res_headline = f"万福，毛毛小主！{ok}个pdf已上传。"
        else:
            res_headline = f"资源上传（成功 {ok} / 共 {total}）"
        log("[*] 发送微信提醒(notify.py --resource-only) ...")
        nr = subprocess.run([
            sys.executable, os.path.join(HERE, "notify.py"), "--date", date,
            "--cookie-status", cookie_status,
            "--upload-status", upload_status,
            "--resource-only",
            "--resources", resources_label,
            "--headline", res_headline,
            "--title", res_headline,
            "--detail", detail,
        ], cwd=HERE, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log(nr.stdout or "")

    log(f"[完成] 拆页上传任务: 资源={upload_status} ({ok}/{total})")
    sys.exit(0 if upload_ok else 1)


if __name__ == "__main__":
    main()
