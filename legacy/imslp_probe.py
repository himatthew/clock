#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查 IMSLP 页面结构：搜索 -> 作品页 -> 钢琴独奏 PDF 直链。"""
import sys, re, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

PROXY = "http://127.0.0.1:55113"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE = "https://imslp.org"

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")

def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "Für Elise"
    print(f"[*] 搜索 IMSLP: {query!r}")
    # IMSLP 搜索
    surl = BASE + "/index.php?search=" + urllib.parse.quote(query) + "&searchtitle=Special%3ASearch"
    try:
        h = http_get(surl)
    except Exception as e:
        print("  搜索失败(urllib):", e)
        h = None
    if h:
        links = re.findall(r'href="(/wiki/[^"]+)"', h)
        print(f"  搜索结果 wiki 链接数: {len(links)}")
        for l in links[:15]:
            print("   ", l)

    # 直接用 Playwright 加载搜索并抓取实际 PDF 链接（处理 JS）
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, proxy={"server": PROXY}, args=["--no-sandbox"])
        ctx = b.new_context(user_agent=UA)
        page = ctx.new_page()
        pdfs = []
        page.on("response", lambda r: pdfs.append(r.url) if r.url.lower().endswith(".pdf") else None)
        try:
            page.goto(surl, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print("  Playwright goto 警告:", e)
        page.wait_for_timeout(2500)
        # 抓取页面里所有 .pdf 链接
        links = page.eval_on_selector_all("a[href$='.pdf']", "els=>els.map(e=>({t:e.textContent.trim().slice(0,40),h:e.href}))")
        print(f"\n[*] 页面内 .pdf 链接数: {len(links)}")
        for l in links[:30]:
            print(f"   {l['t']!r:45s} {l['h']}")
        # 也抓所有包含 imslp 的 pdf（可能在别的 host）
        print(f"\n[*] network 中捕获的 .pdf 响应数: {len(pdfs)}")
        for u in sorted(set(pdfs))[:30]:
            print("   ", u)
        b.close()

if __name__ == "__main__":
    main()
