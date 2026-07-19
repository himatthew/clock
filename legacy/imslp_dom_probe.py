#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, re, urllib.parse, urllib.request, json
from playwright.sync_api import sync_playwright

BASE="https://imslp.org"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
PROXY="http://127.0.0.1:55113"

def api_search(q):
    api=BASE+"/api.php?action=query&list=search&srsearch="+urllib.parse.quote(q)+"&format=json&srlimit=5"
    d=json.loads(urllib.request.urlopen(urllib.request.Request(api,headers={"User-Agent":UA}),timeout=30).read().decode("utf-8","ignore"))
    return [r["title"] for r in d.get("query",{}).get("search",[])]

def main():
    q=sys.argv[1] if len(sys.argv)>1 else "Moonlight Sonata"
    title=api_search(q)[0]
    url=BASE+"/wiki/"+urllib.parse.quote(title.replace(" ","_"))
    print("[*]", q, "->", title)
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        pg=b.new_page()
        pg.set_extra_http_headers({"User-Agent":UA})
        pg.goto(url, wait_until="networkidle", timeout=50000)
        pg.wait_for_timeout(2000)
        # 渲染后所有 a 标签，筛 pdf / imglnks / cn.imslp / redirecttopdfproc
        links=pg.eval_on_selector_all("a[href]", "els=>els.map(e=>e.href)")
        interesting=[u for u in links if re.search(r'\.pdf|imglnks|cn\.imslp|redirecttopdfproc|FilePath', u)]
        print("渲染后相关链接数:", len(interesting))
        for u in interesting[:40]:
            print("  ", u)
        # 专门找包含 'Piano solo' 文字的祖先区块内的 pdf 链接
        b.close()

if __name__=="__main__":
    main()
