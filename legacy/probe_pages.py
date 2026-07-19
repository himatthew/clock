#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测：给定 yuepu id，从详情页静态 HTML 中提取嵌入的 img 数组成像页列表（五线谱 + 简谱）。"""
import sys, re, json, urllib.request, urllib.parse

BASE = "https://www.tan8.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

def extract_img_arrays(html):
    """从 HTML 中提取 yuepuArrXian / yuepuArr / yuepuArrJian 的 img 数组。"""
    out = {}
    # 形如 var yuepuArrXian = [{"img":["url1","url2",...]}, ...];
    for varname in ["yuepuArrXian", "yuepuArr", "yuepuArrJian"]:
        m = re.search(varname + r"\s*=\s*(\[.*?\])\s*;", html, re.S)
        if not m:
            continue
        try:
            arr = json.loads(m.group(1))
        except Exception:
            # 退一步：用正则抓所有 prev_*.png / *.jianpu.*.png
            urls = re.findall(r'(https?://[^\s"\'<>]*?prev_\d+\.(?:\d+|jianpu\.\d+)\.png)', m.group(1))
            out[varname] = urls
            continue
        urls = []
        for item in arr:
            if isinstance(item, dict) and "img" in item and isinstance(item["img"], list):
                urls.extend(item["img"])
        out[varname] = urls
    return out

def pages_for(yid):
    html = fetch(f"{BASE}/yuepu-{yid}.html")
    arr = extract_img_arrays(html)
    summary = {}
    for k, urls in arr.items():
        std = [u for u in urls if "_standard/" in u and "jianpu" not in u]
        jian = [u for u in urls if "jianpu" in u]
        summary[k] = {"total": len(urls), "standard": len(std), "jianpu": len(jian),
                      "sample": urls[:3]}
    return summary

if __name__ == "__main__":
    ids = sys.argv[1:]
    if not ids:
        ids = ["18547"]
    for yid in ids:
        print(f"\n===== yuepu-{yid} =====")
        try:
            s = pages_for(yid)
            for k, v in s.items():
                print(f"  {k}: total={v['total']} standard={v['standard']} jianpu={v['jianpu']}")
                for u in v["sample"]:
                    print("     ", u)
        except Exception as e:
            print("  ERR", e)
