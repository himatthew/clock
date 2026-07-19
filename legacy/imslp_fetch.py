#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 IMSLP（公有领域乐谱库）抓取「完整钢琴独奏谱」并保存为 PDF 到 assets/。

流程（纯 urllib + MediaWiki API，无需浏览器）：
  api_search(查询) -> 作品页标题
  -> 取作品页 HTML -> 解析每个文件块(id=IMSLPxxxx)
     * 标签(Complete Score / Complete Recording / Parts / Incomplete)
     * 真实 PDF 路径(/images/.../...pdf，来自 class="internal" 隐藏链接)
     * 页数(X pp.)
  -> 过滤：标签含 "Complete Score"、且非其他乐器/非 4手/非 Parts/非录音
  -> 选最优（页数最多；偏好 scan/原版）
  -> 下载 PDF -> assets/<slug>.pdf

用法：
  python3 imslp_fetch.py --test "Für Elise"
  python3 imslp_fetch.py --all
  python3 imslp_fetch.py --query "Moonlight Sonata" --out moonlight_sonata
"""
import os, re, sys, time, json, urllib.request, urllib.parse, argparse
from PIL import Image

# 后台运行时 stdout 可能是 ASCII 编码，print 含重音符号的曲名会抛
# UnicodeEncodeError（'ascii' codec can't encode）。强制 UTF-8 输出。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "https://imslp.org"
API = BASE + "/api.php"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "data", "assets")
os.makedirs(ASSETS, exist_ok=True)

# 排除非钢琴独奏的文件块（按文件名/块文本关键词）
NON_PIANO = ["cello", "violin", "viola", "guitar", "flute", "oboe", "clarinet",
             "trumpet", "horn", "harp", "organ", "voice", "vocal", "chorus",
             "choir", "ensemble", "orchestra", "quartet", "quintet", "trio",
             "saxophone", "recorder", "bassoon", "trombone", "sax", "band",
             "4 hands", "four hands", "piano duet", "duet", "2 pianos"]
# 但保留含 piano/pianoforte 的
EXCLUDE_LABEL = ["recording", "parts", "incomplete", "extract", "redo", "midi"]


def http_get(url, binary=False, timeout=40, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                        "Referer": BASE + "/"})
            data = urllib.request.urlopen(req, timeout=timeout).read()
            return data if binary else data.decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(1.5)
    raise last


def api(params):
    url = API + "?" + urllib.parse.urlencode(params)
    return json.loads(http_get(url))


def api_search(query, limit=8):
    d = api({"action": "query", "list": "search",
             "srsearch": query, "format": "json", "srlimit": limit})
    return [r["title"] for r in d.get("query", {}).get("search", [])]


def clean_query(q):
    """去掉 Op./No./纯数字等会破坏搜索的记号，保留作曲家与曲名关键词。"""
    keep = []
    for w in q.split():
        if re.match(r'(?i)^(op\.?|no\.?|\d+|\d+/\d+)$', w):
            continue
        keep.append(w)
    return " ".join(keep)


def work_title(query):
    """搜索并选最合适的作品页标题（召回用净化查询，排序用作曲家+作品号加权）。"""
    cleaned = clean_query(query)
    variants = [query, cleaned]
    parts = query.split()
    for i in range(1, len(parts)):
        variants.append(" ".join(parts[:len(parts) - i]))
    seen = []
    for v in variants:
        if not v:
            continue
        try:
            titles = api_search(v)
        except Exception:
            titles = []
        for t in titles:
            if t not in seen:
                seen.append(t)
    skip = ["study on", "variations on", "exercise", "method", "tutorial",
            "how to", "analysis", "arrangement of", "transcription of"]
    cands = [t for t in seen if not any(s in t.lower() for s in skip)]
    if not cands:
        cands = seen
    if not cands:
        return None
    qtokens = [w.lower() for w in query.split() if len(w) > 2]
    stop = {"sonata", "nocturne", "prelude", "waltz", "march", "op", "no",
            "suite", "concerto", "rhapsody", "impromptu", "ballade",
            "scherzo", "polonaise", "etude", "sonate", "score", "song",
            "elise", "joy", "king", "fairy", "rose", "mood", "swan"}
    composer = [w for w in query.split() if w[:1].isupper() and len(w) > 3
                and w.lower() not in stop]
    opus = re.findall(r'(?i)(op\.?\s*\d+|no\.?\s*\d+|k\.?\s*\d+|bwv\s*\d+|'
                      r'woo\s*\d+|\d+/\d+)', query)

    def score(t):
        tl = t.lower()
        s = sum(1 for w in qtokens if w in tl)
        if any(c.lower() in tl for c in composer):
            s += 10
        for o in opus:
            if o.lower().replace(" ", "") in tl.replace(" ", ""):
                s += 3
        return s

    # 优先要求标题含作曲家（避免选到同曲名的其他作曲家版本）
    if composer:
        with_comp = [t for t in cands if any(c.lower() in t.lower() for c in composer)]
        if with_comp:
            cands = with_comp
    cands.sort(key=score, reverse=True)
    return cands[0]


def parse_files(html):
    """解析作品页所有文件块 -> list of dict。"""
    blocks = html.split('<div id="IMSLP')
    out = []
    for b in blocks[1:]:
        m_id = re.match(r'(\d+)', b)
        fid = m_id.group(1) if m_id else None
        # 标签：Complete Score / Complete Recording / Parts / Incomplete Score
        lab = re.search(r'>(Complete Score|Complete Recording|Parts|Incomplete Score)<', b)
        label = lab.group(1) if lab else ""
        # 真实 PDF 路径：class="internal" 的 /images/.../...pdf（href 与 class 先后不定）
        m = re.search(r'class="internal"[^>]*href="(/images/[^"]+\.pdf)"', b) or \
            re.search(r'href="(/images/[^"]+\.pdf)"[^>]*class="internal"', b)
        pdf_path = m.group(1) if m else None
        # 文件标题
        ft = re.search(r'href="(/wiki/File:[^"]+\.pdf)"', b)
        file_title = ft.group(1) if ft else None
        # 页数
        pp = re.search(r'(\d+)\s*pp', b)
        pages = int(pp.group(1)) if pp else 0
        # 整块文本（小写）用于乐器过滤
        text = b.lower()
        out.append({"id": fid, "label": label, "pdf": pdf_path,
                    "file": file_title, "pages": pages, "text": text,
                    "raw": b})
    return out


def is_piano_solo(block):
    # 钢琴作品页上的文件默认是钢琴；只排除明显是其他乐器/编制的块。
    t = block["text"]
    if any(k in t for k in NON_PIANO):
        return False
    return True


def select_best(blocks):
    cands = [b for b in blocks if "Complete Score" in b["label"]
             and b["pdf"] and is_piano_solo(b)
             and not any(k in b["label"].lower() for k in EXCLUDE_LABEL)]
    if not cands:
        return None
    # 偏好 scan/原版，再按页数降序
    def score(b):
        s = b["pages"]
        if "scan" in b["text"] or "first edition" in b["text"]:
            s += 5
        return s
    cands.sort(key=score, reverse=True)
    return cands[0]


def ascii_safe_url(u):
    """把 URL 中可能含非 ASCII 的路径/查询重新百分号编码，保持 ASCII 安全。
    已编码的 %xx 不会被二次编码（% 在 safe 集合中）。用于 CDN 文件名带重音
    （如 À_l'aventure...pdf）的情形，避免 http.client 拼请求行时 encode('ascii') 失败。
    """
    try:
        parts = urllib.parse.urlsplit(u)
    except Exception:
        return u
    path = urllib.parse.quote(parts.path, safe='/%')
    query = urllib.parse.quote(parts.query, safe='=&%;/')
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path,
                                    query, parts.fragment))


def resolve_files_url(idval):
    """redirecttopdfproc/<id> -> pdfprocessor?files=<真实PDF URL>。"""
    u = f"{BASE}/wiki/Special:GM/redirecttopdfproc/{idval}"
    for _ in range(3):
        try:
            resp = urllib.request.urlopen(
                urllib.request.Request(u, headers={"User-Agent": UA,
                                                    "Referer": BASE + "/"}),
                timeout=40)
            final = resp.geturl()
            q = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
            if "files" in q:
                # 保持百分号编码（ASCII 安全），不要 unquote 还原重音字符
                return q["files"][0]
            return None
        except Exception:
            time.sleep(1.5)
    return None


def download_pdf(idval, outpdf):
    files_url = resolve_files_url(idval)
    if not files_url:
        return False
    if "linkhandler.php" in files_url:
        try:
            html = http_get(files_url)
        except Exception:
            return False
        m = re.search(r'href="(/files/imglnks/[^"]+\.pdf)"', html) or \
            re.search(r'href="(https?://[^"]+\.pdf)"', html)
        if not m:
            return False
        pdf_url = m.group(1)
        if pdf_url.startswith("/"):
            pdf_url = "https://imslp.eu" + pdf_url
        pdf_url = ascii_safe_url(pdf_url)
    else:
        pdf_url = ascii_safe_url(files_url)
    data = http_get(pdf_url, binary=True, timeout=120)
    if len(data) < 5000 or data[:4] != b"%PDF":
        return False
    with open(outpdf, "wb") as f:
        f.write(data)
    return True


def process_title(slug, title, outdir=None, verbose=True):
    """已知作品页标题，抓取其钢琴独奏完整谱 PDF。返回 pdf 路径或 None。"""
    outdir = outdir or ASSETS
    url = BASE + "/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    try:
        html = http_get(url)
    except Exception as e:
        if verbose:
            print(f"    ! 取作品页失败: {e}")
        return None
    blocks = parse_files(html)
    best = select_best(blocks)
    if not best:
        if verbose:
            print(f"    ! 无合适钢琴独奏完整谱（块数={len(blocks)}）")
        return None
    outpdf = os.path.join(outdir, f"{slug}.pdf")
    if download_pdf(best["id"], outpdf):
        sz = os.path.getsize(outpdf)
        if verbose:
            print(f"    ✓ {slug} <- {title}  ({sz//1024}KB, {best['pages']}pp)")
        return outpdf
    if verbose:
        print("    ! PDF 下载失败")
    return None


def process(slug, query, outdir=None):
    outdir = outdir or ASSETS
    print(f"[>] {slug}  <- IMSLP 搜索「{query}」")
    title = work_title(query)
    if not title:
        print("    ! 无搜索结果")
        return None
    print(f"    作品页: {title}")
    return process_title(slug, title, outdir)


def sanitize(title):
    s = re.sub(r'[^A-Za-z0-9\u4e00-\u9fff]+', '_', title)
    s = s.strip('_')
    return s[:60] or "score"


def category_members(cat, limit=400):
    """取 IMSLP 分类成员标题列表（分页）。"""
    members = []
    cmcontinue = None
    while len(members) < limit:
        params = {"action": "query", "list": "categorymembers",
                  "cmtitle": "Category:" + cat, "cmlimit": 100,
                  "format": "json"}
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        try:
            d = api(params)
        except Exception as e:
            print("  category API 出错:", e)
            break
        for m in d.get("query", {}).get("categorymembers", []):
            members.append(m["title"])
        if "continue" not in d:
            break
        cmcontinue = d["continue"]["cmcontinue"]
    return members


def collect(n, category="For piano", outdir=None):
    """从 IMSLP 某分类收集 n 个钢琴独奏完整谱 PDF 到 assets/。

    - 已存在的 PDF 计入目标数（不重复下载）；
    - 若原始 slug 文件已存在则整条跳过；
    - 不同条目 sanitize 出相同 slug 时用 base_k 区分。
    """
    outdir = outdir or ASSETS
    existing = [f for f in os.listdir(outdir) if f.lower().endswith(".pdf")]
    have = len(existing)
    print(f"[*] {outdir} 已有 {have} 个 PDF，目标 {n}")
    members = category_members(category, limit=max(n * 4, 400))
    print(f"[*] 分类「{category}」取到 {len(members)} 个条目")
    done, fail = have, 0
    used = set()
    for title in members:
        if title.startswith(("Category:", "File:", "Talk:", "User:",
                             "Template:", "Portal:", "Special:")):
            continue
        slug = sanitize(title)
        # 原始 slug 文件已存在 -> 跳过（不重新下载）
        if os.path.exists(os.path.join(outdir, slug + ".pdf")):
            continue
        base, k = slug, 1
        while slug in used:
            slug = f"{base}_{k}"
            k += 1
        used.add(slug)
        try:
            r = process_title(slug, title, outdir)
        except Exception as e:
            print(f"[!] {slug} 异常: {e}")
            r = None
        if r:
            done += 1
        else:
            fail += 1
        if done >= n:
            break
        time.sleep(1.0)
    print(f"\n=== 收集完成: 成功 {done} / 失败 {fail} / 目标 {n} ===")
    return done


# ---------- 100 首映射：slug -> IMSLP 搜索词（用原作/英文名，命中率最高） ----------
IMSLP_QUERIES = {
    "fur_elise": "Für Elise",
    "moonlight_sonata": "Moonlight Sonata Beethoven",
    "ode_to_joy": "Ode to Joy Beethoven",
    "turkish_march": "Turkish March Mozart",
    "sonata_k545": "Piano Sonata No.16 K.545 Mozart",
    "minuet_in_g": "Minuet in G major BWV Anh.114 Bach",
    "prelude_in_c": "Prelude in C major BWV 846 Bach",
    "gymnopedie_1": "Gymnopédie No.1 Satie",
    "clair_de_lune": "Clair de Lune Debussy",
    "traumerei": "Träumerei Schumann",
    "nocturne_op9_2": "Nocturne Op.9 No.2 Chopin",
    "minute_waltz": "Waltz in D flat Op.64 No.1 Chopin",
    "raindrop_prelude": "Raindrop Prelude Op.28 No.15 Chopin",
    "sugar_plum_fairy": "Dance of the Sugar Plum Fairy Tchaikovsky",
    "lullaby_brahms": "Wiegenlied Brahms",
    "canon_in_d": "Canon in D Pachelbel",
    "ave_maria": "Ave Maria Schubert",
    "eine_kleine": "Eine kleine Nachtmusik Mozart",
    "wedding_march": "Wedding March Mendelssohn",
    "hallelujah": "Hallelujah chorus Handel",
    "sarabande": "Sarabande Handel",
    "trumpet_voluntary": "Prince of Denmark's March Clarke",
    "mountain_king": "In the Hall of the Mountain King Grieg",
    "humoresque": "Humoresque Op.101 No.7 Dvorak",
    "largo_new_world": "Largo from New World Symphony Dvorak",
    "promenade": "Pictures at an Exhibition Promenade Mussorgsky",
    "sabre_dance": "Sabre Dance Khachaturian",
    "the_swan": "The Swan Saint-Saens",
    "spring_song": "Spring Song Mendelssohn",
    "rach_prelude_csharp": "Prelude in C-sharp minor Rachmaninoff",
    "fantaisie_impromptu": "Fantaisie-Impromptu Chopin",
    "maple_leaf_rag": "Maple Leaf Rag Joplin",
    "the_entertainer": "The Entertainer Joplin",
    "surprise_symphony": "Surprise Symphony Haydn",
    "to_a_wild_rose": "To a Wild Rose MacDowell",
    "pathetique": "Piano Sonata No.8 Pathetique Beethoven",
    "waldstein": "Piano Sonata No.21 Waldstein Beethoven",
    "appassionata": "Piano Sonata No.23 Appassionata Beethoven",
    "symphony_no5": "Symphony No.5 Beethoven piano",
    "egmont": "Egmont Overture Beethoven",
    "fantasia_d_minor": "Fantasia in D minor Mozart",
    "sonata_k331": "Piano Sonata No.11 K.331 Mozart",
    "sonata_k333": "Piano Sonata No.13 K.333 Mozart",
    "sonata_k284": "Piano Sonata No.6 K.284 Mozart",
    "invention_1": "Invention No.1 BWV 772 Bach",
    "invention_8": "Invention No.8 BWV 779 Bach",
    "invention_13": "Invention No.13 BWV 784 Bach",
    "prelude_in_d": "Prelude in D major BWV 850 Bach",
    "prelude_in_bflat": "Prelude in B-flat major BWV 866 Bach",
    "toccata_d_minor": "Toccata and Fugue in D minor BWV 565 Bach",
    "jesu_joy": "Jesu, Joy of Man's Desiring Bach",
    "nocturne_op9_1": "Nocturne Op.9 No.1 Chopin",
    "nocturne_op27_2": "Nocturne Op.27 No.2 Chopin",
    "nocturne_op55_1": "Nocturne Op.55 No.1 Chopin",
    "waltz_op18": "Waltz in E flat Op.18 Chopin",
    "waltz_op64_2": "Waltz in C-sharp minor Op.64 No.2 Chopin",
    "prelude_op28_7": "Prelude Op.28 No.7 Chopin",
    "prelude_op28_20": "Prelude Op.28 No.20 Chopin",
    "etude_op10_3": "Etude Op.10 No.3 Chopin",
    "etude_op10_12": "Revolutionary Etude Op.10 No.12 Chopin",
    "polonaise_militaire": "Polonaise in A-flat Op.53 Chopin",
    "ballade_1": "Ballade No.1 Chopin",
    "scherzo_2": "Scherzo No.2 Chopin",
    "impromptu_op90_4": "Impromptu Op.90 No.4 Schubert",
    "serenade_standchen": "Ständchen Schubert",
    "frohlicher_landmann": "Fröhlicher Landmann Schumann",
    "arabesque_schumann": "Arabesque Schumann Op.18",
    "liebestraum_3": "Liebestraum No.3 Liszt",
    "hungarian_rhapsody_2": "Hungarian Rhapsody No.2 Liszt",
    "consolation_3": "Consolation No.3 Liszt",
    "la_campanella": "La Campanella Liszt",
    "piano_concerto_grieg": "Piano Concerto A minor Grieg",
    "arietta_grieg": "Lyric Piece Arietta Grieg",
    "morning_mood": "Morning Mood Peer Gynt Grieg",
    "wedding_day_troldhaugen": "Wedding Day at Troldhaugen Grieg",
    "june_barcarolle": "June Barcarolle Tchaikovsky",
    "october_autumn": "October Autumn Song Tchaikovsky",
    "december_christmas": "December Christmas Tchaikovsky",
    "swan_lake": "Swan Lake Tchaikovsky",
    "romeo_and_juliet": "Romeo and Juliet Tchaikovsky",
    "prelude_op23_5": "Prelude Op.23 No.5 Rachmaninoff",
    "prelude_op32_5": "Prelude Op.32 No.5 Rachmaninoff",
    "piano_concerto_2": "Piano Concerto No.2 Rachmaninoff",
    "rhapsody_paganini": "Rhapsody on a Theme of Paganini Rachmaninoff",
    "finlandia": "Finlandia Sibelius",
    "slavonic_dance_1": "Slavonic Dance Op.46 No.1 Dvorak",
    "songs_mother_taught": "Songs My Mother Taught Me Dvorak",
    "the_moldau": "The Moldau Smetana",
    "polovtsian": "Polovtsian Dances Borodin",
    "night_on_bald_mountain": "Night on Bald Mountain Mussorgsky",
    "asturias": "Asturias Leyenda Albeniz",
    "spanish_dance_andaluza": "Spanish Dance Andaluza Granados",
    "ritual_fire_dance": "Ritual Fire Dance Falla",
    "girl_with_flaxen_hair": "Girl with the Flaxen Hair Debussy",
    "arabesque_debussy": "Arabesque No.1 Debussy",
    "pavane_ravel": "Pavane pour une infante défunte Ravel",
    "jeux_d_eau": "Jeux d'eau Ravel",
    "o_polichinelo": "O Polichinelo Villa-Lobos",
    "carnival_of_venice": "Carnival of Venice ",
    "rondo_alla_turca_b": "Rondo Alla Turca Mozart",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", help="单首验证（IMSLP 搜索词）")
    ap.add_argument("--query", help="指定 IMSLP 搜索词")
    ap.add_argument("--out", help="输出 slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--collect", type=int, help="从 IMSLP 分类收集 N 个钢琴谱 PDF")
    ap.add_argument("--cat", default="For piano", help="收集使用的 IMSLP 分类名")
    args = ap.parse_args()

    if args.test:
        process("test", args.test)
        return
    if args.query:
        slug = args.out or "custom"
        process(slug, args.query)
        return
    if args.collect:
        collect(args.collect, category=args.cat)
        return
    if args.all:
        done, fail = 0, 0
        for slug, q in IMSLP_QUERIES.items():
            try:
                r = process(slug, q)
                if r:
                    done += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"[!] {slug} 异常: {e}")
                fail += 1
            time.sleep(1.5)
        print(f"\n=== 完成: 成功 {done} / 失败 {fail} / 共 {len(IMSLP_QUERIES)} ===")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
