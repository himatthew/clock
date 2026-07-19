#!/usr/bin/env python3
# 之江汇教育广场 · 陈晓雯名师工作室(sid=2174) 资源删除工具
# 用法:
#   python delete_resource.py cookies.txt --list
#       列出「我的资源」(标题/resId/ownerResId)，重复项标 [DUP]
#   python delete_resource.py cookies.txt --delete <resId> [<resId> ...]
#       删除指定资源(不可逆!)
#   python delete_resource.py cookies.txt --dedupe
#       预览去重计划(同标题只留最新一条)，加 --yes 才真删
#
# 说明: 删除走站点自有接口 POST ?r=studio/resources/delres，
#       需从「我的资源」页拿到每项的 ownerResId 校验 hash。删除不可逆。
import os, sys, argparse, re, time
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
SID = 2174
MYRES_URL = f"https://ms.zjer.cn/index.php?r=studio/resources/myreslist&sid={SID}"
DEL_URL = f"https://ms.zjer.cn/index.php?r=studio/resources/delres&sid={SID}"


def load_cookie_header(path):
    return open(path).read().strip()


def load_cookies(path):
    s = open(path).read().strip()
    out = []
    for p in s.split(";"):
        p = p.strip()
        if not p or "=" not in p:
            continue
        k, v = p.split("=", 1)
        out.append({"name": k.strip(), "value": v.strip(),
                    "domain": ".zjer.cn", "path": "/"})
    return out


def get_my_resources(cookie_path):
    """返回 [{title, resId, ownerResId}]，按页面顺序(通常时间倒序)。"""
    cookies = load_cookies(cookie_path)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = b.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(MYRES_URL, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(2000)
        # 触发懒加载: 反复滚到底
        for _ in range(8):
            before = len(page.query_selector_all("a"))
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
            after = len(page.query_selector_all("a"))
            if after == before:
                break
        page.wait_for_timeout(800)
        items = page.evaluate("""() => {
            const out = [];
            const as = Array.from(document.querySelectorAll('a')).filter(a => {
                const oc = a.getAttribute('onclick') || '';
                return (a.innerText || '').trim() === '删除' && /delRes\\(/.test(oc);
            });
            for (const a of as) {
                const m = (a.getAttribute('onclick') || '').match(/delRes\\('([^']+)',\\s*'([^']+)'\\)/);
                if (!m) continue;
                const ownerResId = m[1];
                const resId = m[2];
                // 向上找带标题的行
                let row = a, title = '';
                for (let i = 0; i < 6; i++) {
                    if (!row.parentElement) break;
                    row = row.parentElement;
                    const tEl = row.querySelector ? row.querySelector('a.title, .title, span[title]') : null;
                    if (tEl) { title = tEl.getAttribute('title') || tEl.innerText || ''; break; }
                }
                out.push({ title: (title || '').trim(), resId, ownerResId });
            }
            return out;
        }""")
        b.close()
    return items


def delete_one(cookie_path, res_id):
    """重新抓「我的资源」拿该 resId 的最新 ownerResId，再 POST 删除。"""
    items = get_my_resources(cookie_path)
    hit = next((x for x in items if x["resId"] == res_id), None)
    if not hit:
        return {"ok": False, "resId": res_id, "msg": "在「我的资源」中找不到该 resId(可能已被删或非本人资源)"}
    owner = hit["ownerResId"]
    hdr = {"User-Agent": UA, "Cookie": load_cookie_header(cookie_path),
           "X-Requested-With": "XMLHttpRequest",
           "Referer": MYRES_URL}
    data = {"ownerResId": owner, "ResId": res_id, "type": "front"}
    r = requests.post(DEL_URL, data=data, headers=hdr, timeout=30)
    try:
        obj = r.json()
        ok = str(obj.get("type", "")).lower() in ("1", "success", "true") or "成功" in str(obj.get("content", ""))
        return {"ok": ok, "resId": res_id, "raw": obj}
    except Exception as e:
        return {"ok": False, "resId": res_id, "msg": f"非JSON响应(status={r.status_code}): {r.text[:200]}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cookie", nargs="?", default="cookies.txt")
    ap.add_argument("--list", action="store_true", help="列出我的资源")
    ap.add_argument("--delete", nargs="+", metavar="RESID", help="删除指定 resId")
    ap.add_argument("--dedupe", action="store_true", help="预览去重计划(同标题留最新)")
    ap.add_argument("--yes", action="store_true", help="与 --dedupe 配合，真正执行删除")
    args = ap.parse_args()

    if not os.path.exists(args.cookie):
        print(f"cookie 文件不存在: {args.cookie}")
        sys.exit(1)

    if args.list or args.dedupe:
        items = get_my_resources(args.cookie)
        # 标记重复: 同 title 出现 >1 次
        from collections import Counter
        cnt = Counter(x["title"] for x in items)
        print(f"共 {len(items)} 条我的资源:\n")
        for i, x in enumerate(items, 1):
            dup = " [DUP]" if cnt[x["title"]] > 1 else ""
            print(f"  {i:3}  {x['title'][:50]:50}  resId={x['resId']}{dup}")
        if args.dedupe:
            # 保留每组最后一条(页面通常时间倒序=最新在上)，删其余
            groups = {}
            for x in items:
                groups.setdefault(x["title"], []).append(x)
            plan_del = []
            for title, grp in groups.items():
                if len(grp) > 1:
                    keep = grp[-1]          # 最新
                    for x in grp[:-1]:
                        plan_del.append(x)
            print(f"\n去重计划: 将删除 {len(plan_del)} 条(每组同名保留最新一条):")
            for x in plan_del:
                print(f"   del  {x['title'][:50]:50}  resId={x['resId']}")
            if args.yes and plan_del:
                print("\n执行删除...")
                for x in plan_del:
                    res = delete_one(args.cookie, x["resId"])
                    print(f"   resId={x['resId']} -> {'OK' if res['ok'] else 'FAIL'}  {res.get('raw', res.get('msg',''))}")
            elif not args.yes:
                print("\n(加 --yes 才真正删除)")
        return

    if args.delete:
        print(f"删除 {len(args.delete)} 条(不可逆):")
        for rid in args.delete:
            res = delete_one(args.cookie, rid)
            print(f"  resId={rid} -> {'✅ OK' if res['ok'] else '❌ FAIL'}  {res.get('raw', res.get('msg',''))}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
