#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 tan8.com（弹琴吧）抓取真实钢琴曲谱，合并为 PDF 存入 assets/。

流程：
  search(钢琴, keyword) -> 结果列表(yuepu id + 标题)
  -> 选最优（优先“原版/完整”，避开“简单/简易/初学/超简单/爵士/流行...”）
  -> 抓取详情页，解析五线谱(standard)分页图片数组（无则回退简谱 jianpu）
  -> 下载各页 PNG -> Pillow 合并为单页 PDF

用法：
  python3 fetch_tan8.py --test "致爱丽丝"      # 单首验证
  python3 fetch_tan8.py --all                  # 按 QUERIES 批量抓取 100 首
  python3 fetch_tan8.py --query "卡农" --out canon   # 指定查询与输出名
"""
import os
import re
import sys
import time
import html
import urllib.parse
import urllib.request

import argparse
from PIL import Image

BASE = "https://www.tan8.com"
SEARCH = BASE + "/search-1-1-0.php?keyword="
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "data", "assets")
os.makedirs(ASSETS, exist_ok=True)

# 100 首查询：尽量用中文名（tan8 以中文为主），并列英文/别名兜底。
# (输出文件名slug, 搜索词, 期望作曲家/备注用于校验)
QUERIES = [
    ("fur_elise", "致爱丽丝"),
    ("moonlight_sonata", "月光奏鸣曲"),
    ("ode_to_joy", "欢乐颂"),
    ("turkish_march", "土耳其进行曲"),
    ("sonata_k545", "C大调钢琴奏鸣曲 K545"),
    ("minuet_in_g", "G大调小步舞曲 巴赫"),
    ("prelude_in_c", "C大调前奏曲 巴赫"),
    ("gymnopedie_1", " gymnopédie 第一号"),
    ("clair_de_lune", "月光 德彪西"),
    ("traumerei", "梦幻曲 舒曼"),
    ("nocturne_op9_2", "夜曲 op9 no2 肖邦"),
    ("minute_waltz", "小狗圆舞曲 肖邦"),
    ("raindrop_prelude", "雨滴前奏曲 肖邦"),
    ("sugar_plum_fairy", "糖果仙子舞曲"),
    ("lullaby_brahms", "摇篮曲 勃拉姆斯"),
    ("canon_in_d", "卡农 d大调"),
    ("ave_maria", "圣母颂 舒伯特"),
    ("eine_kleine", "小夜曲 莫扎特"),
    ("wedding_march", "婚礼进行曲 门德尔松"),
    ("hallelujah", "哈利路亚 亨德尔"),
    ("sarabande", "萨拉班德 亨德尔"),
    ("trumpet_voluntary", "小号自愿曲"),
    ("mountain_king", "山魔王的大厅 格里格"),
    ("humoresque", "幽默曲 德沃夏克"),
    ("largo_new_world", "广板 新世界 德沃夏克"),
    ("promenade", "图画展览会 漫步"),
    ("sabre_dance", "马刀舞曲"),
    ("the_swan", "天鹅 圣桑"),
    ("spring_song", "春之歌 门德尔松"),
    ("rach_prelude_csharp", "升c小调前奏曲 拉赫玛尼诺夫"),
    ("fantaisie_impromptu", "幻想即兴曲 肖邦"),
    ("maple_leaf_rag", "枫叶拉格"),
    ("the_entertainer", "艺人 乔普林"),
    ("surprise_symphony", "惊愕交响曲"),
    ("to_a_wild_rose", "野玫瑰 麦克道威尔"),
    ("pathetique", "悲怆奏鸣曲"),
    ("waldstein", "华尔斯坦奏鸣曲"),
    ("appassionata", "热情奏鸣曲"),
    ("symphony_no5", "命运交响曲 钢琴"),
    ("egmont", "艾格蒙特序曲"),
    ("fantasia_d_minor", "d小调幻想曲 莫扎特"),
    ("sonata_k331", "A大调钢琴奏鸣曲 莫扎特"),
    ("sonata_k333", "F大调钢琴奏鸣曲 莫扎特"),
    ("sonata_k284", "D大调钢琴奏鸣曲 莫扎特"),
    ("invention_1", "创意曲第一首 巴赫"),
    ("invention_8", "创意曲第八首 巴赫"),
    ("invention_13", "创意曲第十三首 巴赫"),
    ("prelude_in_d", "D大调前奏曲 巴赫"),
    ("prelude_in_bflat", "降B大调前奏曲 巴赫"),
    ("toccata_d_minor", "d小调托卡塔 巴赫"),
    ("jesu_joy", "耶稣，人们渴望的欢乐 巴赫"),
    ("nocturne_op9_1", "夜曲 op9 no1 肖邦"),
    ("nocturne_op27_2", "夜曲 op27 no2 肖邦"),
    ("nocturne_op55_1", "夜曲 op55 no1 肖邦"),
    ("waltz_op18", "华丽大圆舞曲 肖邦"),
    ("waltz_op64_2", "圆舞曲 op64 no2 肖邦"),
    ("prelude_op28_7", "前奏曲 op28 no7 肖邦"),
    ("prelude_op28_20", "前奏曲 op28 no20 肖邦"),
    ("etude_op10_3", "练习曲 op10 no3 肖邦"),
    ("etude_op10_12", "革命练习曲 肖邦"),
    ("polonaise_militaire", "军队波罗乃兹 肖邦"),
    ("ballade_1", "叙事曲第一首 肖邦"),
    ("scherzo_2", "诙谐曲第二首 肖邦"),
    ("impromptu_op90_4", "即兴曲 op90 no4 舒伯特"),
    ("serenade_standchen", "小夜曲 舒伯特"),
    ("frohlicher_landmann", "快乐的农夫 舒曼"),
    ("arabesque_schumann", "阿拉伯风格曲 舒曼"),
    ("liebestraum_3", "爱之梦 第三首 李斯特"),
    ("hungarian_rhapsody_2", "匈牙利狂想曲第二首 李斯特"),
    ("consolation_3", "安慰曲第三首 李斯特"),
    ("la_campanella", "钟 李斯特"),
    ("piano_concerto_grieg", "a小调钢琴协奏曲 格里格"),
    ("arietta_grieg", "aria 格里格"),
    ("morning_mood", "晨景 格里格"),
    ("wedding_day_troldhaugen", "特罗尔豪根的婚礼 格里格"),
    ("june_barcarolle", "六月 船歌 柴可夫斯基"),
    ("october_autumn", "十月 秋之歌 柴可夫斯基"),
    ("december_christmas", "十二月 圣诞节 柴可夫斯基"),
    ("swan_lake", "天鹅湖 柴可夫斯基"),
    ("romeo_and_juliet", "罗密欧与朱丽叶 柴可夫斯基"),
    ("prelude_op23_5", "前奏曲 op23 no5 拉赫玛尼诺夫"),
    ("prelude_op32_5", "前奏曲 op32 no5 拉赫玛尼诺夫"),
    ("piano_concerto_2", "c小调第二钢琴协奏曲 拉赫玛尼诺夫"),
    ("rhapsody_paganini", "帕格尼尼主题狂想曲 拉赫玛尼诺夫"),
    ("finlandia", "芬兰颂"),
    ("slavonic_dance_1", "斯拉夫舞曲 德沃夏克"),
    ("songs_mother_taught", "母亲教我的歌 德沃夏克"),
    ("the_moldau", "沃尔塔瓦河 斯美塔那"),
    ("polovtsian", "波罗维茨舞曲"),
    ("night_on_bald_mountain", "荒山之夜 穆索尔斯基"),
    ("asturias", "阿斯图里亚斯 阿尔贝尼斯"),
    ("spanish_dance_andaluza", "安达卢萨 西班牙舞曲 格拉纳多斯"),
    ("ritual_fire_dance", "火祭之舞 法雅"),
    ("girl_with_flaxen_hair", "金色头发的少女 德彪西"),
    ("arabesque_debussy", "阿拉伯风格曲第一首 德彪西"),
    ("pavane_ravel", "悼念公主的帕凡舞曲 拉威尔"),
    ("jeux_d_eau", "水之嬉戏 拉威尔"),
    ("o_polichinelo", "小丑 维拉-洛博斯"),
    ("carnival_of_venice", "威尼斯狂欢节"),
    ("rondo_alla_turca_b", "土耳其回旋曲 莫扎特"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def search(query):
    url = SEARCH + urllib.parse.quote(query)
    h = get(url)
    items = re.findall(r'<a[^>]*href="(/yuepu-\d+\.html)"[^>]*>(.*?)</a>', h, re.S)
    out, seen = [], set()
    for href, txt in items:
        title = re.sub(r"<[^>]+>", "", txt).strip()
        if not title:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append((href, title))
    return out


def pick_best(results, query):
    bad = ["简单", "简易", "初学", "超简单", "爵士", "流行", "儿歌", "电子",
           "弹奏", "教学", "考级", "视唱", "拜厄", "车尔尼", "哈农"]
    good = ["原版", "完整", "正谱", "钢琴谱"]

    def score(t):
        s = 0
        for g in good:
            if g in t:
                s += 5
        for b in bad:
            if b in t:
                s -= 4
        return s

    best, best_s = None, -999
    for h, t in results:
        s = score(t)
        if s > best_s:
            best_s, best = s, (h, t)
    return best


def url_ok(u):
    """用 HEAD 轻量探测图片是否存在（OSS 支持 HEAD）。"""
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Referer": BASE + "/"},
                                      method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            cl = int(r.headers.get("Content-Length", "0") or 0)
            return r.status == 200 and cl > 2000
    except Exception:
        return False


def get_pages(yuepu_id):
    url = f"{BASE}/yuepu-{yuepu_id}.html"
    h = get(url).replace("\\/", "/")
    # 详情页仅内嵌第 0 页模板；viewer 通过递增页码加载后续页。
    # 形如：.../<id>/<id>_<token>_standard/prev_<id>.<N>.png（standard=五线谱，jianpu=简谱）
    pats = [
        rf"(https?://oss\.tan8\.com/yuepuku/\d+/{yuepu_id}/{yuepu_id}_[A-Za-z0-9]+_standard/prev_{yuepu_id}\.)(\d+)(\.png)",
        rf"(https?://oss\.tan8\.com/yuepuku/\d+/{yuepu_id}/{yuepu_id}_[A-Za-z0-9]+_jianpu/prev_{yuepu_id}\.)(\d+)(\.jianpu\.png)",
    ]
    for pat in pats:
        m = re.search(pat, h)
        if not m:
            continue
        prefix, _, ext = m.group(1), m.group(2), m.group(3)
        urls = [f"{prefix}0{ext}"]  # 第 0 页必存在
        for n in range(1, 40):
            u = f"{prefix}{n}{ext}"
            if url_ok(u):
                urls.append(u)
            else:
                break
        if urls:
            return urls
    return []


def download(urls, outdir, slug):
    paths = []
    for i, u in enumerate(urls):
        p = os.path.join(outdir, f"_{slug}_{i:02d}.png")
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA,
                                                      "Referer": BASE + "/"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 1000:
                break
            with open(p, "wb") as f:
                f.write(data)
            paths.append(p)
        except Exception as e:
            print(f"    ! 下载页 {i} 失败: {e}")
            break
    return paths


def make_pdf(paths, outpdf):
    imgs = [Image.open(p).convert("RGB") for p in paths]
    if not imgs:
        return False
    imgs[0].save(outpdf, save_all=True, append_images=imgs[1:], resolution=100.0)
    return True


def process(slug, query, outdir=None):
    outdir = outdir or ASSETS
    print(f"[>] {slug}  <- 搜索「{query}」")
    results = search(query)
    if not results:
        print(f"    ! 无搜索结果")
        return None
    best = pick_best(results, query)
    if not best:
        print(f"    ! 无合适结果")
        return None
    href, title = best
    yid = re.search(r"/yuepu-(\d+)\.html", href).group(1)
    print(f"    选定: {title}  (yuepu-{yid})  共 {len(results)} 条结果")
    pages = get_pages(yid)
    print(f"    谱面页数: {len(pages)}")
    if not pages:
        print(f"    ! 未解析到谱面图片")
        return None
    paths = download(pages, outdir, slug)
    if not paths:
        print(f"    ! 下载失败")
        return None
    outpdf = os.path.join(outdir, f"{slug}.pdf")
    ok = make_pdf(paths, outpdf)
    # 清理临时 png
    for p in paths:
        try:
            os.remove(p)
        except Exception:
            pass
    if ok:
        print(f"    ✓ 已生成 {outpdf}  ({len(paths)} 页)")
        return outpdf
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", help="用单个查询做端到端验证")
    ap.add_argument("--query", help="指定查询词")
    ap.add_argument("--out", help="指定输出 slug（配合 --query）")
    ap.add_argument("--all", action="store_true", help="批量抓取 QUERIES 中全部 100 首")
    args = ap.parse_args()

    if args.test:
        process("test", args.test)
        return
    if args.query:
        slug = args.out or "custom"
        process(slug, args.query)
        return
    if args.all:
        done, fail = 0, 0
        for slug, q in QUERIES:
            try:
                r = process(slug, q)
                if r:
                    done += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"[!] {slug} 异常: {e}")
                fail += 1
            time.sleep(1.0)  # 礼貌节流
        print(f"\n=== 完成: 成功 {done} / 失败 {fail} / 共 {len(QUERIES)} ===")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
