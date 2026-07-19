#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, json, urllib.request, urllib.parse, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # legacy/ 自身, 避免硬编码绝对路径
from probe_pages import fetch, extract_img_arrays

BASE = "https://www.tan8.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def search(query):
    url = BASE + "/search-1-1-0.php?keyword=" + urllib.parse.quote(query)
    h = fetch(url)
    items = re.findall(r'<a[^>]*href="(/yuepu-\d+\.html)"[^>]*>(.*?)</a>', h, re.S)
    out, seen = [], set()
    for href, txt in items:
        title = re.sub(r"<[^>]+>", "", txt).strip()
        if not title or href in seen:
            continue
        seen.add(href); out.append((href, title))
    return out

queries = ["致爱丽丝","卡农","月光奏鸣曲","欢乐颂","土耳其进行曲","野玫瑰","命运交响曲","小星星","梦中的婚礼","童年","天空之城","菊次郎的夏天","river flows in you","神秘园","秋日私语"]
for q in queries:
    res = search(q)
    if not res:
        print(f"[?] {q}: 无结果"); continue
    href, title = res[0]
    yid = re.search(r"/yuepu-(\d+)\.html", href).group(1)
    try:
        html = fetch(f"{BASE}/yuepu-{yid}.html")
        arr = extract_img_arrays(html)
        tot = max((len(v) for k,v in arr.items() if k in ("yuepuArrXian","yuepuArr")), default=0)
        std_n = 0
        for k,v in arr.items():
            std_n = max(std_n, sum(1 for u in v if "_standard/" in u and "jianpu" not in u))
        print(f"[*] {q:12s} -> {title} (yuepu-{yid})  五线谱页数={std_n}  数组总数={tot}")
    except Exception as e:
        print(f"[!] {q}: ERR {e}")
