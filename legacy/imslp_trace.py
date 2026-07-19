#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Playwright 走通 IMSLP：搜索 -> 作品页 -> 钢琴独奏 PDF 直链。"""
import sys, re, urllib.parse
from playwright.sync_api import sync_playwright

BASE = "https://imslp.org"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "Für Elise"
    # 正确编码：用 quote 编码原始词（空格留作 +）
    surl = BASE + "/index.php?search=" + urllib.parse.quote(query) + "&searchtitle=Special%3ASearch"
    print("[*] 搜索:", surl)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        pg.set_extra_http_headers({"User-Agent": UA})
        try:
            pg.goto(surl, wait_until="domcontentloaded", timeout=40000)
        except Exception as e:
            print("  goto 警告:", e)
        pg.wait_for_timeout(2500)
        # 抓取搜索结果里指向 /wiki/ 的链接（作品页）
        links = pg.eval_on_selector_all(
            "a[href^='/wiki/']",
            "els=>els.map(e=>({t:e.textContent.trim().slice(0,60),h:e.getAttribute('href')}))")
        # 过滤掉非作品页（Special:, Category:, File:, Help:, User: 等）
        works = [l for l in links if not re.search(r"/(Special|Category|File|Help|User|Talk|Template|Portal):", l["h"])]
        print(f"[*] 候选作品链接: {len(works)}")
        for l in works[:12]:
            print(f"   {l['t']!r:55s} {l['h']}")
        # 访问第一个最可能的作品页
        if works:
            w = works[0]["h"]
            print(f"\n[*] 打开作品页: {BASE}{w}")
            pg.goto(BASE + w, wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_timeout(2500)
            # 找含 "Piano solo" 的小节，抓取其后 PDF/文件链接
            html = pg.content()
            # 在 "Piano solo" 附近提取链接
            m = re.search(r"Piano solo(.*?)(?:Piano\s+4\s+hands|Arrangements|</table>|Piano\s+2)", html, re.S)
            seg = m.group(1) if m else html
            pdfs = re.findall(r'href="(/wiki/[^"]+)"[^>]*>([^<]+)</a>', seg)
            # 也抓 .pdf 直链
            direct = re.findall(r'href="(https?://[^"]+\.pdf)"', seg)
            print(f"   段内链接数: {len(pdfs)}，直链 pdf 数: {len(direct)}")
            for h, t in pdfs[:20]:
                print(f"     link {t.strip()[:40]!r:42s} {h}")
            for u in direct[:10]:
                print("     PDF ", u)
            # 保存作品页 HTML
            open("/tmp/imslp_work.html","w").write(html)
            print("   已存 /tmp/imslp_work.html")
        b.close()

if __name__ == "__main__":
    main()
