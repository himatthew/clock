#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
之江汇教育广场 (陈晓雯名师工作室 sid=2174) 资源上传 - Playwright 版
基于已逐项验证正确的白盒逻辑 (所有自定义控件处理正确):
  * 资源类型课件 = 点可见 label (hRadio 插件, 改 checked 无效)
  * 学段小学 / 学科音乐(jcsub20, 注意另有 艺术·音乐=fd88cf..)
  * 教材目录其它(value=ms_other_330000, 单次展开单击避免卡顿)
  * 工作室分类PPT = 点 <a id=treeDemo2_10_a> 触发 move() 写 #parentId
  * 属性本人原创 = 点 label[for=iso]
  * 原创承诺 checkbox = 点含"承诺"文字的 label
  * 文件经隐藏 iframe (#inp_fbtn) 走 OSS 上传

两种模式 (--mode):
  auto     默认, headless=True, 填完自动提交并打印 type 判据
  whitebox headless=False, 填到发布前停住, 供人工可视化排查 (手动点【发布】)
           仅当只上传 1 个文件时生效(批量时强制 auto)

去重: 默认复制源文件为新 MD5 变体(追加随机字节), 如需用原文件加 --no-variant。

PDF 资源(assets/ 下):
  文件名已由 rename_assets.py 预处理为 日期_原文件名.pdf。
  * 显式传 assets/ 下 .pdf -> 单文件上传(parentId=综合资源)
  * 不传文件 -> 批量上传 assets 下「当天日期前缀」的全部 PDF
  * 旧 PPTX 写法(pptx 不在 assets/ 下)仍走原逻辑(parentId=PPT)
"""
import os, re, time, argparse, tempfile
from playwright.sync_api import sync_playwright
from resource_config import (resolve_resource, list_resources,
                             _default_config_path, resolve_pdf_asset, today_str,
                             ORIGINAL_OPTIONS)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
# 之江汇资源上传页: 用户实测的真正链接(原样, name=JSON转义字面量, url 双层编码, 不可用 urlencode 解码)
UPLOAD_URL = r"https://ms.zjer.cn/index.php?r=studio/resources/upload&sid=2174&name=%22%5Cu8d44%5Cu6e90%5Cu5217%5Cu8868%22&url=%252Findex.php%253Fr%253Dstudio%252Fresources%2526sid%253D2174"
DEF_PPTX = "/Users/matthew/Downloads/《铃儿响叮当》课件.pptx"


def log(*a):
    print(*a, flush=True)


def parse_cookies(s):
    c = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        name, value = part.split("=", 1) if "=" in part else (part, "")
        dom = ".henan.smartedu.cn" if "henan.smartedu.cn" in name else ".zjer.cn"
        c.append({"name": name.strip(), "value": value.strip(), "domain": dom, "path": "/"})
    return c


def make_variant(src, dst):
    with open(src, "rb") as f:
        data = f.read()
    data += os.urandom(16)  # 改字节 -> 改 MD5, 绕过去重
    with open(dst, "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cookie", help="cookies.txt 路径")
    ap.add_argument("url", nargs="?", default=UPLOAD_URL, help="资源上传页 URL")
    ap.add_argument("pptx", nargs="?", default=None,
                    help="源 pptx/pdf(可选; 不传则上传 assets 下当天日期前缀的 PDF)")
    ap.add_argument("--mode", choices=["auto", "whitebox"], default="auto")
    ap.add_argument("--title", default=None, help="资源名称(可选, 覆盖配置)")
    ap.add_argument("--config", default=None, help="资源配置文件 (默认 resources_config.json)")
    ap.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD 取资源 (默认当天)")
    ap.add_argument("--list", action="store_true", help="列出配置里全部资源后退出")
    ap.add_argument("--no-variant", action="store_true", help="用原文件, 不改 MD5")
    ap.add_argument("--pages-dir", default=None,
                    help="批量上传该目录下全部 .pdf(拆页后逐页上传); 优先于 --pptx/当天前缀")
    args = ap.parse_args()

    if args.list:
        cp = args.config or _default_config_path()
        rows = list_resources(cp)
        if not rows:
            raise SystemExit(f"配置文件无资源: {cp}")
        print(f"配置文件 {cp} 中的资源:")
        for d, t, f in rows:
            print(f"  {d:>12}  {t}  <-  {f}")
        return

    # ---- 构建上传目标: --pages-dir / 指定 assets/ 下 .pdf / 指定 pptx / 当天日期前缀批量 ----
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "assets")
    targets = []

    if args.pages_dir:
        d = os.path.abspath(args.pages_dir)
        if not os.path.isdir(d):
            raise SystemExit(f"--pages-dir 不存在: {d}")
        pdfs = sorted(f for f in os.listdir(d) if f.lower().endswith(".pdf"))
        if not pdfs:
            raise SystemExit(f"{d} 下没有 PDF 文件")
        log(f"[*] --pages-dir 待上传 {len(pdfs)} 个:")
        for f in pdfs:
            fp = os.path.join(d, f)
            fields, source = resolve_pdf_asset(fp, args.title)
            targets.append((fp, fields, source, "pdf"))
            log(f"    {f}")
    elif args.pptx:
        _p = os.path.abspath(args.pptx)
        is_pdf_asset = args.pptx.lower().endswith(".pdf") and \
            os.path.dirname(_p) == assets_dir
        if is_pdf_asset:
            fields, source = resolve_pdf_asset(args.pptx, args.title)
            targets.append((args.pptx, fields, source, "pdf"))
        else:
            cli_file = args.pptx
            cli_title = args.title or os.path.splitext(os.path.basename(cli_file))[0]
            fields, source = resolve_resource(
                config_path=args.config, override_date=args.date,
                cli_file=cli_file, cli_title=cli_title)
            targets.append((fields.get("file"), fields, source, "pptx"))
    else:
        date = args.date or today_str()
        prefix = date + "_"
        pdfs = sorted(f for f in os.listdir(assets_dir)
                      if f.startswith(prefix) and f.lower().endswith(".pdf"))
        if not pdfs:
            raise SystemExit(f"assets/ 下没有匹配当天({date})的 PDF 文件")
        log(f"[*] 当天({date})待上传 {len(pdfs)} 个:")
        for f in pdfs:
            fp = os.path.join(assets_dir, f)
            fields, source = resolve_pdf_asset(fp, args.title)
            targets.append((fp, fields, source, "pdf"))
            log(f"    {f}")

    if not targets:
        raise SystemExit("无上传目标")

    cookie = open(args.cookie, encoding="utf-8").read().strip()
    headless = (args.mode == "auto")
    log(f"mode={args.mode}  headless={headless}  共 {len(targets)} 个目标")

    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(user_agent=UA)
        ctx.add_cookies(parse_cookies(cookie))

        ok = fail = 0
        for src, fields, source, mode in targets:
            try:
                pdf_mode = (mode == "pdf")
                log(f"\n===== 来源: {source}  mode={mode} =====")
                if not src or not os.path.exists(src):
                    if pdf_mode:
                        raise SystemExit(f"找不到 PDF 文件: {src}")
                    alt = os.path.join(os.getcwd(), "《铃儿响叮当》 课件 上传3.pptx")
                    if os.path.exists(alt):
                        src = alt
                        log("源文件不存在, 改用:", alt)
                    else:
                        raise SystemExit("找不到 pptx 文件, 请检查配置 file 路径")

                if args.no_variant:
                    pptx = src
                    log("使用原文件 (未改 MD5, 可能触发服务端去重)")
                else:
                    stem, ext = os.path.splitext(os.path.basename(src))
                    if pdf_mode:
                        # 文件名已含日期(预处理改名), 变体保持同名写临时目录
                        pptx = os.path.join(tempfile.gettempdir(), f"{stem}{ext}")
                    else:
                        workdir = os.path.dirname(os.path.abspath(src)) or "."
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        pptx = os.path.join(workdir, f"{stem} pw_{ts}{ext}")
                    make_variant(src, pptx)
                    log("生成去重变体:", pptx)

                fname = os.path.basename(pptx)
                title = fields.get("title") or os.path.splitext(fname)[0]
                intro = fields.get("intro") or title
                log(f"title={title}")

                page = ctx.new_page()
                page.set_viewport_size({"width": 1366, "height": 900})

                post_responses = []
                def on_resp(resp):
                    if resp.request.method == "POST" and "studio/resources/upload" in resp.url:
                        try:
                            body = resp.text()[:2000]
                        except Exception:
                            body = ""
                        post_responses.append((resp.status, resp.url, body))
                page.on("response", on_resp)

                page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)

                # ---- 1) 上传文件 (隐藏 iframe) ----
                # 上传表单的隐藏 iframe(NAME=iframeName) 由页面 JS 异步注入,
                # 偶发加载慢 -> "上传 iframe 未找到" 并级联后续点击超时(整篇失败)。
                # 用 page.frame("iframeName") 轮询等待其就绪(与原始可用逻辑一致),
                # 最多 ~20s; 注意: 该 iframe 以 name/id 注册, 必须走 page.frame() 才能稳定取到,
                # 用 CSS 选择器 iframe[NAME=...] 反而不匹配 -> 全部误判失败。
                # 仍缺失才抛错由外层标记失败(不再做无意义的后续点击)。
                log("--- step1: 上传文件 ---")
                frame = None
                for _ in range(20):
                    frame = page.frame("iframeName")
                    if frame:
                        break
                    page.wait_for_timeout(1000)
                if not frame:
                    raise RuntimeError("上传 iframe 未找到(轮询20s仍缺失), 中止本文件上传")
                frame.wait_for_selector("#inp_fbtn", state="attached", timeout=10000)
                frame.set_input_files("#inp_fbtn", pptx)
                done = False
                for _ in range(60):
                    vid = frame.evaluate("()=>document.querySelector('#attachFileId')?.value||''")
                    if vid:
                        log(f"上传完成: attachFileId={vid[:40]}"); done = True; break
                    page.wait_for_timeout(1000)
                if not done:
                    log("WARN: 60s 内上传未完成")

                # ---- 2) 资源类型 课件 (hRadio, 必须点 label) ----
                log("--- step2: 资源类型=课件 ---")
                try:
                    page.click('.radiolist1 label.hRadio:has-text("课件")', timeout=5000)
                except Exception as e:
                    log(f"click 课件 label 失败: {e}; JS 兜底")
                    page.evaluate("""() => {
                        const radios=[...document.querySelectorAll('input[name="classid"]')];
                        radios.forEach(r=>{ r.checked=(r.value==='22'); });
                        document.querySelectorAll('.radiolist1 label.hRadio').forEach(l=>{
                            l.classList.toggle('hRadio_Checked', (l.innerText||'').trim()==='课件');
                        });
                    }""")
                page.wait_for_timeout(500)
                cv = page.evaluate("()=>document.querySelector('input[name=\"classid\"]:checked')?.value||'(none)'")
                log(f"classid checked={cv!r}")

                # ---- 3) 学段 小学 ----
                log("--- step3: 学段=小学 ---")
                page.click("#perioddis", timeout=5000); page.wait_for_timeout(800)
                page.click('#periodlist a[value="xx"]', timeout=5000)
                page.wait_for_timeout(1200)

                # ---- 4) 学科 音乐 (jcsub20) ----
                log("--- step4: 学科=音乐 ---")
                page.click("#subjectdis", timeout=5000); page.wait_for_timeout(1200)
                try:
                    page.click('#subjectlist a[value="jcsub20"]', force=True, timeout=5000)
                except Exception as e:
                    log(f"click 学科音乐 失败: {e}")
                page.wait_for_timeout(900)
                subj = page.evaluate("()=>document.querySelector('input[name=\"subject\"]')?.value||''")
                if subj != "jcsub20":
                    log(f"学科未写入({subj!r}), JS 兜底")
                    page.evaluate("""() => { const a=document.querySelector('#subjectlist a[value="jcsub20"]'); if(a) a.click(); }""")
                    page.wait_for_timeout(800)
                log(f"学科 subject={subj!r}")

                # ---- 5) 教学目录 其它 (单次展开+单击) ----
                log("--- step5: 教学目录=其它 ---")
                try:
                    expanded = page.evaluate("""() => { const el=document.querySelector('#new_select_chapter')||document.querySelector('#menu_list'); return !!(el && el.offsetParent!==null); }""")
                    if not expanded:
                        page.click(".ljcd_xiala", timeout=5000); page.wait_for_timeout(1000)
                    # 优先按 value=ms_other_330000 精确点; 否则按可见文本「其它」点
                    page.evaluate("""() => {
                        const el=document.querySelector('#new_select_chapter')||document.querySelector('#menu_list');
                        if(!el) return;
                        const items=Array.from(el.querySelectorAll('a,li'));
                        const byVal=items.find(a=>(a.getAttribute('value')||'')==='ms_other_330000');
                        if(byVal){ byVal.click(); return; }
                        const t=items.find(a=>(a.innerText||'').trim()==='其它'); if(t) t.click();
                    }""")
                    page.wait_for_timeout(1200)
                    # 若还有子级未到底, 逐层进入 value 以 ms_other 开头的节点(JS 用 startsWith)
                    for _ in range(4):
                        still = page.evaluate("""() => { const el=document.querySelector('#new_select_chapter')||document.querySelector('#menu_list'); return !!(el && el.offsetParent!==null); }""")
                        has_sub = page.evaluate("""() => { const el=document.querySelector('#new_select_chapter')||document.querySelector('#menu_list'); if(!el||el.offsetParent===null) return false; return Array.from(el.querySelectorAll('a,li')).some(a=>{const v=(a.getAttribute('value')||''); return v && v!=='ms_other_330000' && !v.startsWith('ms_other');}); }""")
                        if not still or not has_sub: break
                        clicked = page.evaluate("""() => { const el=document.querySelector('#new_select_chapter')||document.querySelector('#menu_list'); if(!el) return false; const items=Array.from(el.querySelectorAll('a,li')); const any=items.find(a=>(a.getAttribute('value')||'').startsWith('ms_other'))||items[0]; if(any){any.click(); return true;} return false; }""")
                        if not clicked: break
                        page.wait_for_timeout(1000)
                    # 末级补一次精确点(防止停在父节点)
                    page.evaluate("""() => { const el=document.querySelector('#new_select_chapter')||document.querySelector('#menu_list'); if(!el) return; const items=Array.from(el.querySelectorAll('a,li')); const byVal=items.find(a=>(a.getAttribute('value')||'')==='ms_other_330000'); if(byVal){byVal.click();} else { const t=items.find(a=>(a.innerText||'').trim()==='其它'); if(t) t.click(); } }""")
                    page.wait_for_timeout(1000)
                    ed = page.evaluate("()=>document.querySelector('#editionname')?.value||''")
                    edid = page.evaluate("()=>document.querySelector('#editionid')?.value||''")
                    log(f"教学目录 editionname={ed!r} editionid={edid!r}")
                    # 兜底: 若仍为空, 直接写隐藏域并触发 change(部分页面提交只读隐藏域)
                    if not edid:
                        page.evaluate("""() => { const e=document.querySelector('#editionid'); const n=document.querySelector('#editionname'); if(e){e.value='ms_other_330000'; e.dispatchEvent(new Event('change',{bubbles:true}));} if(n){n.value='其它'; n.dispatchEvent(new Event('change',{bubbles:true}));} }""")
                        log("教学目录: JS 兜底写入 editionid=ms_other_330000 / editionname=其它")
                except Exception as e:
                    log(f"教学目录 err: {e}")

                # ---- 6) 工作室分类 ----
                if pdf_mode:
                    log("--- step6: 工作室分类=综合资源 (move) ---")
                    page.evaluate(
                        "() => { try{ if(typeof move==='function') move('%s'); }catch(e){} }"
                        % fields["parentId"])
                else:
                    log("--- step6: 工作室分类=PPT ---")
                    try:
                        page.click("#treeDemo2_10_a", force=True, timeout=5000)
                    except Exception as e:
                        log(f"click #treeDemo2_10_a 失败: {e}; 调 move()")
                        page.evaluate("""() => { try{ if(typeof move==='function') move('db1a78ebac1d2c2f2970bbf81f0d1a61'); }catch(e){} }""")
                page.wait_for_timeout(1200)
                pid = page.evaluate("()=>document.querySelector('#parentId')?.value||'(not found)'")
                log(f"parentId={pid!r}")

                # ---- 7) 资源简介 ----
                log("--- step7: 资源简介 ---")
                page.fill('textarea[name="intro"]', intro)
                log(f"intro={intro!r}")

                # ---- 8) 属性 (本人原创/工作室成员原创/授权转载, 按字段值点对应 label) ----
                original_val = str(fields.get("original") or "0")
                orig_name = {v: k for k, v in ORIGINAL_OPTIONS.items()}.get(original_val, "本人原创")
                log(f"--- step8: 属性={orig_name} (value={original_val}) ---")
                try:
                    page.click(f'label.hRadio:has-text("{orig_name}")', timeout=5000)
                except Exception as e:
                    log(f"click 属性 label[{orig_name}] 失败: {e}; JS 兜底")
                    page.evaluate("""(a) => {
                        const nm=a.nm, val=a.val;
                        const labs=[...document.querySelectorAll('label.hRadio')];
                        const l=labs.find(x=>(x.innerText||'').trim()===nm);
                        if(l){ l.click(); return; }
                        const radios=[...document.querySelectorAll('input[name="original"]')];
                        const r=radios.find(x=>String(x.value)===String(val));
                        if(r){ r.checked=true; const lab=document.querySelector('label[for="'+r.id+'"]'); if(lab) lab.classList.add('hRadio_Checked'); }
                    }""", {"nm": orig_name, "val": original_val})
                page.wait_for_timeout(500)

                # ---- 9) 作者 (读字段值 original_author) ----
                author = fields.get("original_author") or "佚名"
                log(f"--- step9: 作者={author} ---")
                page.fill('input[name="original_author"]', author)

                # ---- 10) 原创承诺 checkbox (点含"承诺"的 label) ----
                log("--- step10: 原创承诺 ---")
                ck = page.evaluate("""() => {
                    const labs=[...document.querySelectorAll('label.checkbox, label')];
                    const cl=labs.find(x=>(x.innerText||'').includes('承诺'));
                    if(cl){ cl.click(); return true; } return false;
                }""")
                log(f"承诺 label 点击: {ck}")

                page.wait_for_timeout(500)

                # === PRE-SUBMIT CHECK ===
                log("\n=== 提交前字段检查 ===")
                pre = page.evaluate("""()=>{
                    const d={};
                    ['title','intro','original_author','subject','parentId','editionname','attachFileId'].forEach(n=>{
                        const el=document.querySelector('[name="'+n+'"]'); d[n]=el?(el.value||'').slice(0,60):'(not found)';
                    });
                    ['classid','original'].forEach(n=>{
                        const el=document.querySelector('input[name="'+n+'"]:checked'); d['radio:'+n]=el?el.value:'(none)';
                    });
                    const lab=document.querySelector('label[for="iso"]'); d['attrLabelCls']=lab?lab.className:'(none)';
                    const labs=[...document.querySelectorAll('label.checkbox, label')];
                    const cl=labs.find(x=>(x.innerText||'').includes('承诺'));
                    d['承诺checked']=cl?(cl.querySelector('input[type=checkbox]')?.checked):'(none)';
                    return d;
                }""")
                for k, v in pre.items():
                    log(f"  {k} = {v!r}")

                if args.mode == "whitebox" and len(targets) == 1:
                    log("\n=== 白盒模式: 表单已填好, 请在浏览器手动点【发布】, 完成后回到此处按 Enter 结束 ===")
                    try:
                        input()
                    except EOFError:
                        pass
                    page.close()
                    b.close()
                    return

                # ---- auto: 提交 ----
                log("\n--- auto: 点击发布 ---")
                page.evaluate("()=>{ const b=document.getElementById('submit'); if(b) b.click(); }")
                page.wait_for_timeout(6000)
                found = None
                for st, url, body in post_responses:
                    mt = re.search(r'"type"\s*:\s*(\d+)', body)
                    mc = re.search(r'"content"\s*:\s*"([^"]*)"', body)
                    if mt:
                        found = (mt.group(1), mc.group(1) if mc else "")
                        break
                if found:
                    mtype, content = found
                    if mtype == "1":
                        log(f"✅ 提交成功 (type=1) content={content}")
                    elif mtype == "2":
                        log(f"⚠️ 服务端去重/校验拦截 (type=2) content={content}")
                    else:
                        log(f"❓ 未知 type={mtype} content={content}")
                else:
                    final = page.url
                    body_txt = page.evaluate("()=>document.body?document.body.innerText:'')") or ""
                    if "成功" in body_txt:
                        log("✅ 页面提示成功")
                    else:
                        log(f"❓ 未捕获 type, 最终URL={final[:120]} body前120={body_txt[:120]}")
                page.close()
                ok += 1
            except Exception as e:
                log(f"[!] 上传失败 {os.path.basename(str(src))}: {e}")
                fail += 1
        if args.mode == "whitebox":
            log("=== 白盒模式: 浏览器保持打开供查看 (约120秒后自动关闭) ===")
            try:
                input()
            except EOFError:
                pass
            time.sleep(120)
        b.close()

    log(f"\n=== 完成: 成功 {ok} / 失败 {fail} / 共 {len(targets)} ===")


if __name__ == "__main__":
    main()
