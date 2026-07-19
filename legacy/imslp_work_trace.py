#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查 IMSLP 作品页：Piano solo 分区 -> 文件页 -> PDF 直链。"""
import sys, re, urllib.parse
from playwright.sync_api import sync_playwright

BASE = "https://imslp.org"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def api_search(query):
    import urllib.request, json
    api = BASE + "/api.php?action=query&list=search&srsearch=" + urllib.parse.quote(query) + "&format=json&srlimit=10"
    d = json.loads(urllib.request.urlopen(
        urllib.request.Request(api, headers={"User-Agent": UA}), timeout=30).read().decode("utf-8","ignore"))
    return [r["title"] for r in d.get("query",{}).get("search",[])]

def main():
    title = sys.argv[1] if len(sys.argv)>1 else None
    if not title:
        title = api_search("Für Elise")[0]
    print("[*] 作品页:", title)
    url = BASE + "/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    print("    URL:", url)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        pg.set_extra_http_headers({"User-Agent": UA})
        pg.goto(url, wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_timeout(2000)
        html = pg.content()
        open("/tmp/imslp_fe.html","w").write(html)
        # 找所有 "Piano solo" 出现位置
        for kw in ["Piano solo", "Solo piano", "For piano"]:
            idxs = [m.start() for m in re.finditer(re.escape(kw), html)]
            print(f"[*] 关键词 {kw!r} 出现 {len(idxs)} 次")
        # 提取所有文件页链接 Special:ImagefromIndex 与 /wiki/File:
        filelinks = re.findall(r'href="(/wiki/(?:Special:ImagefromIndex|File:[^"]+))"', html)
        print(f"[*] 文件/图片页链接数: {len(filelinks)}")
        for l in filelinks[:20]:
            print("   ", l)
        # 提取页面内 .pdf 直链
        pdfs = re.findall(r'(https?://[^\s"\'<>]+\.pdf)', html)
        print(f"[*] 页面内 .pdf 直链数: {len(pdfs)}")
        for u in pdfs[:20]:
            print("   ", u)
        b.close()

if __name__ == "__main__":
    main()
