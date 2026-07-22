#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
之江汇教育广场(陈晓雯名师工作室 sid=2174) 资源上传 - 接口直发版
绕过页面自定义控件(heapbox / ztree / hRadio / 隐藏 iframe), 直接走 HTTP 链路:

  1) ossGetAuthorization  -> 拿阿里云 OSS 直传签名(accessid/policy/signature/key/host)
  2) POST <oss host>      -> multipart 直传文件到 OSS (返回 204)
  3) finishUploadFile     -> 登记, 返回 fid (即 attachFileId)
  4) 提交资源表单         -> /index.php?r=studio/resources/upload&sid=2174&cid=

设计要点:
  * 跳过 rapidUpload 秒传探测 -> 秒传才是按 fileMd5 判重的源头, 直接走真实上传强制拿新 fid
  * 每次运行复制源文件为新 MD5 变体(追加随机字节) -> 双保险彻底绕过去重
  * 默认直接提交并打印 type 判据(type=1 成功 / type=2 去重)
  * --dry-run 可停在提交前, 仅验证上传拿到 fid

用法:
  # 推荐: 读 resources_config.json 里「当天」的资源自动发(含固定字段)
  python3 publish_resource_api.py cookies.txt

  # 指定配置文件 / 看某天资源(不实际提交)
  python3 publish_resource_api.py cookies.txt --config my_res.json
  python3 publish_resource_api.py cookies.txt --date 2026-07-14 --dry-run

  # 仍支持旧写法(优先级最高, 越过配置)
  python3 publish_resource_api.py cookies.txt "/path/课件.pptx" --title "课件名"
"""

import sys, os, re, hashlib, time, argparse, tempfile
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resource_config import (resolve_resource, list_resources,
                             _default_config_path, resolve_pdf_asset, today_str)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

UPLOAD_URL = "https://ms.zjer.cn/index.php?r=studio/resources/upload&sid=2174"
SUBMIT_URL = "https://ms.zjer.cn/index.php?r=studio/resources/upload&sid=2174&cid="
AUTH_URL   = "https://ms.zjer.cn/index.php?r=common/ossjsupload/ossGetAuthorization"
FINISH_URL = "https://ms.zjer.cn/index.php?r=common/ossjsupload/finishUploadFile"
USER_ID    = "shixun_700138"   # 前端 JS 写死的上传账号

# 固定表单默认值, 实际以 resource_config.resolve_resource 返回的 fields 为准
# (配置文件 fixed 段 + 当天 resources 条目可覆盖任意项)


def log(*a):
    print(*a, flush=True)


def load_cookie(path):
    raw = open(path, "r", encoding="utf-8").read().strip()
    # 压缩多余空白(避免 cookies.txt 含换行导致 header 非法)
    return re.sub(r"\s+", " ", raw).strip()


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_variant(src, dst):
    """复制源文件并追加随机字节 -> 改变 MD5, 绕过去重"""
    with open(src, "rb") as f:
        data = f.read()
    data += os.urandom(16)
    with open(dst, "wb") as f:
        f.write(data)


def oss_upload(session, cookie, path):
    """执行上传三步, 返回 fid(attachFileId)"""
    fname = os.path.basename(path)
    file_md5 = md5_of(path)
    size = os.path.getsize(path)
    h = {"Cookie": cookie, "User-Agent": UA, "X-Requested-With": "XMLHttpRequest"}

    # 1) OSS 授权
    log(f"[1/4] ossGetAuthorization  fileMd5={file_md5} size={size}")
    r = session.post(AUTH_URL, data={
        "fileMd5": file_md5, "userId": USER_ID,
        "fileLength": size, "fileName": fname,
    }, headers=h, timeout=30)
    j = r.json()
    if j.get("result") != "000000":
        raise RuntimeError(f"ossGetAuthorization 失败: {j}")
    d = j["data"]
    accessid, signature, key, policy, host = (
        d["accessid"], d["signature"], d["dir"], d["policy"], d["host"])
    log(f"      host={host}\n      key={key}")

    # 2) OSS 直传
    log("[2/4] 直传 OSS ...")
    with open(path, "rb") as f:
        files = [
            ("OSSAccessKeyId", (None, accessid)),
            ("policy", (None, policy)),
            ("Signature", (None, signature)),
            ("key", (None, key)),
            ("file", (fname, f, "application/octet-stream")),
            ("submit", (None, "Upload to OSS")),
        ]
        # OSS 直传不需要业务 cookie, 仅带 UA
        r2 = requests.post(host, files=files, timeout=120)
    if r2.status_code != 204:
        raise RuntimeError(f"OSS 直传失败 status={r2.status_code} body={r2.text[:200]}")
    log("      OSS 204 OK")

    # 3) 登记
    log("[3/4] finishUploadFile ...")
    r3 = session.post(FINISH_URL, data={
        "fileMd5": file_md5, "ossKey": key, "userId": USER_ID,
        "fileLength": size, "fileName": fname,
    }, headers=h, timeout=30)
    j3 = r3.json()
    if j3.get("result") != "000000":
        raise RuntimeError(f"finishUploadFile 失败: {j3}")
    fid = j3["data"]["fid"]
    log(f"      attachFileId(fid) = {fid}")
    return fid


def get_page_hash(session, cookie):
    h = {"Cookie": cookie, "User-Agent": UA}
    r = session.get(UPLOAD_URL, headers=h, timeout=30)
    m = re.search(r'name="hash"\s+value="([0-9a-f]+)"', r.text)
    return m.group(1) if m else "f50a470c7da0b7d6a2ac0a99a3f35b2b"


def submit_resource(session, cookie, fid, fields, page_hash, dry_run=False):
    data = dict(fields)
    data["hash"] = page_hash
    data["contentIds"] = fid

    if dry_run:
        log("[dry-run] 提交前数据预览:")
        for k, v in data.items():
            log(f"    {k} = {v}")
        return None

    log("[4/4] 提交资源表单 ...")
    h = {"Cookie": cookie, "User-Agent": UA,
         "Referer": UPLOAD_URL, "X-Requested-With": "XMLHttpRequest"}
    r = session.post(SUBMIT_URL, data=data, headers=h, timeout=30)
    text = r.text
    log(f"      HTTP {r.status_code}  body_len={len(text)}")
    mt = re.search(r'"type"\s*:\s*(\d+)', text)
    mtype = mt.group(1) if mt else "?"
    mc = re.search(r'"content"\s*:\s*"([^"]*)"', text)
    content = mc.group(1) if mc else text[:200]
    log(f"      >>> type={mtype}  content={content}")
    return mtype, content


def upload_one(src, fields, source, mode, cookie, args):
    """上传单个文件: 去重变体 -> OSS 直传 -> 提交。"""
    log(f"\n===== 来源: {source}  mode={mode} =====")
    if not src or not os.path.exists(src):
        if mode == "pdf":
            raise SystemExit(f"找不到 PDF 文件: {src}")
        alt = os.path.join(os.getcwd(), "《铃儿响叮当》 课件 上传3.pptx")
        if os.path.exists(alt):
            src = alt
            log(f"源文件不存在, 改用: {alt}")
        else:
            raise SystemExit("找不到源 pptx 文件, 请检查配置 file 路径")

    title = fields.get("title") or os.path.splitext(os.path.basename(src))[0]
    fields["title"] = title
    if not fields.get("intro"):
        fields["intro"] = title

    stem, ext = os.path.splitext(os.path.basename(src))
    if args.no_variant:
        # 用原文件直传, 靠服务端 MD5 去重实现幂等(与 playwright --no-variant 一致)
        variant = src
        log(f"使用原文件(不改 MD5, 服务端去重兜底): {variant}")
    elif mode == "pdf":
        # 文件名已含日期(预处理改名), 变体保持同名写临时目录, 不污染 assets/
        variant = os.path.join(tempfile.gettempdir(), f"{stem}{ext}")
        make_variant(src, variant)
        log(f"生成去重变体(新MD5): {variant}")
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        workdir = os.path.dirname(os.path.abspath(src)) or "."
        variant = os.path.join(workdir, f"{stem} api_{ts}{ext}")
        make_variant(src, variant)
        log(f"生成去重变体(新MD5): {variant}")
    log(f"文件 MD5 = {md5_of(variant)}")

    session = requests.Session()
    fid = oss_upload(session, cookie, variant)
    page_hash = get_page_hash(session, cookie)
    log(f"page hash = {page_hash}")
    res = submit_resource(session, cookie, fid, fields, page_hash, dry_run=args.dry_run)
    if res:
        mtype, content = res
        if mtype == "1":
            log("✅ 提交成功 (type=1)")
        elif mtype == "2":
            log("⚠️ 服务端去重拦截 (type=2): 需更换文件 MD5 后重试")
        else:
            log(f"❓ 未知返回 type={mtype}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cookie", help="cookies.txt 路径")
    ap.add_argument("file", nargs="?", default=None,
                    help="源文件(可选; 不传则上传 assets 下当天日期前缀的 PDF)")
    ap.add_argument("--title", default=None, help="资源名称(可选, 覆盖配置)")
    ap.add_argument("--intro", default=None, help="资源简介(可选, 默认=title)")
    ap.add_argument("--config", default=None, help="资源配置文件 (默认 resources_config.json)")
    ap.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD 取资源 (默认当天)")
    ap.add_argument("--list", action="store_true", help="列出配置文件里全部资源后退出")
    ap.add_argument("--pages-dir", default=None,
                    help="拆页批量: 上传该目录下全部 PDF(每日拆页任务用, 替代 assets 整本)")
    ap.add_argument("--no-variant", action="store_true",
                    help="不上传去重变体, 用原文件(靠服务端 MD5 去重, 可幂等重跑)")
    ap.add_argument("--dry-run", action="store_true",
                    help="停在提交前, 只验证上传拿到 fid")
    args = ap.parse_args()

    if args.list:
        cp = args.config or _default_config_path()
        rows = list_resources(cp)
        if not rows:
            raise SystemExit(f"配置文件无资源: {cp}")
        log(f"配置文件 {cp} 中的资源:")
        for d, t, f in rows:
            log(f"  {d:>12}  {t}  <-  {f}")
        return

    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "assets")

    # 构建上传目标列表 (src, fields, source, mode)
    targets = []

    if args.pages_dir:
        # 拆页批量: 上传目录下全部 PDF(每日拆页任务用, 优先于其它来源)
        d = os.path.abspath(args.pages_dir)
        if not os.path.isdir(d):
            raise SystemExit(f"--pages-dir 不存在: {d}")
        pdfs = sorted(f for f in os.listdir(d) if f.lower().endswith(".pdf"))
        if not pdfs:
            raise SystemExit(f"{d} 下没有 PDF 文件")
        log(f"[*] --pages-dir 待上传 {len(pdfs)} 个:")
        for f in pdfs:
            fp = os.path.join(d, f)
            fields, source = resolve_pdf_asset(fp, args.title, args.intro)
            targets.append((fp, fields, source, "pdf"))
            log(f"    {f}")
    elif args.file:
        # 显式指定单个文件
        _p = os.path.abspath(args.file)
        is_pdf_asset = args.file.lower().endswith(".pdf") and \
            os.path.dirname(_p) == assets_dir
        if is_pdf_asset:
            fields, source = resolve_pdf_asset(args.file, args.title, args.intro)
            targets.append((args.file, fields, source, "pdf"))
        else:
            # 旧 PPTX 逻辑
            fields, source = resolve_resource(
                config_path=args.config, override_date=args.date,
                cli_file=args.file, cli_title=args.title, cli_intro=args.intro)
            targets.append((fields.get("file"), fields, source, "pptx"))
    else:
        # 批量: assets 下当天日期前缀的 PDF
        date = args.date or today_str()
        prefix = date + "_"
        pdfs = sorted(
            f for f in os.listdir(assets_dir)
            if f.startswith(prefix) and f.lower().endswith(".pdf"))
        if not pdfs:
            raise SystemExit(f"assets/ 下没有匹配当天({date})的 PDF 文件")
        log(f"[*] 当天({date})待上传 {len(pdfs)} 个:")
        for f in pdfs:
            fp = os.path.join(assets_dir, f)
            fields, source = resolve_pdf_asset(fp, args.title, args.intro)
            targets.append((fp, fields, source, "pdf"))
            log(f"    {f}")

    cookie = load_cookie(args.cookie)
    ok = fail = 0
    for src, fields, source, mode in targets:
        try:
            upload_one(src, fields, source, mode, cookie, args)
            ok += 1
        except Exception as e:
            log(f"[!] 上传失败 {os.path.basename(str(src))}: {e}")
            fail += 1
    log(f"\n=== 完成: 成功 {ok} / 失败 {fail} / 共 {len(targets)} ===")


if __name__ == "__main__":
    main()
