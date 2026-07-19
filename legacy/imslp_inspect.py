#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, re, urllib.parse, urllib.request, json
from playwright.sync_api import sync_playwright

BASE="https://imslp.org"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

def api_search(q):
    api=BASE+"/api.php?action=query&list=search&srsearch="+urllib.parse.quote(q)+"&format=json&srlimit=6"
    d=json.loads(urllib.request.urlopen(urllib.request.Request(api,headers={"User-Agent":UA}),timeout=30).read().decode("utf-8","ignore"))
    return [r["title"] for r in d.get("query",{}).get("search",[])]
def get_html(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    return urllib.request.urlopen(req,timeout=40).read().decode("utf-8","ignore")

def main():
    queries = sys.argv[1:] or ["Moonlight Sonata", "Nocturne Op.9 No.2"]
    for q in queries:
        title = api_search(q)[0]
        print("\n############################################")
        print(f"## 查询 {q!r} -> 作品页 {title!r}")
        url = BASE+"/wiki/"+urllib.parse.quote(title.replace(" ","_"))
        html = get_html(url)
        # 找 Piano solo 区块
        m = re.search(r'(Piano solo.*?)(Arrangements and Transcriptions|<!-|<h2|General Information)', html, re.S)
        seg = m.group(1) if m else html
        # 提取该区块内的文件链接与可见文字
        files = re.findall(r'/wiki/(?:File:[^"<>]+\.pdf|Special:ImagefromIndex/[^"<>]+)', seg)
        # 看看 "Piano solo" 出现位置及周围
        print("  Piano solo 区块长度:", len(seg))
        # 列出区块内所有 pdf 文件链接（去重）
        print("  区块内 pdf 文件链接数:", len(files))
        for f in sorted(set(files))[:25]:
            print("    ", f)
        # 片段里出现的可读行（含 'pdf' 或 'Complete' 或 'movement'）
        for line in re.findall(r'>([^<>]{3,80})<', seg):
            if re.search(r'pdf|Complete|movement|scan|edition|Piano solo', line, re.I):
                print("    TXT:", line.strip()[:70])
        open(f"/tmp/imslp_{q.replace(' ','_')}.html","w").write(html)

if __name__=="__main__":
    main()
