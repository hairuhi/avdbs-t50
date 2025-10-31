import os, re, time, pathlib
from io import BytesIO
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
import requests
from bs4 import BeautifulSoup

# ===== Telegram =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ===== Target =====
AVDBS_BASE = os.getenv("AVDBS_BASE", "https://www.avdbs.com").rstrip("/")
BOARD_PATH = os.getenv("AVDBS_BOARD_PATH", "/board/t50")  # t50
LIST_URL = f"{AVDBS_BASE}{BOARD_PATH}"

# ===== Auth (우선순위: AVDBS_COOKIE → AVDBS_ID/PW) =====
AVDBS_COOKIE = os.getenv("AVDBS_COOKIE", "").strip()
AVDBS_ID = os.getenv("AVDBS_ID", "").strip()
AVDBS_PW = os.getenv("AVDBS_PW", "").strip()

# ===== Runtime / State =====
TIMEOUT = 25
TRACE_IMAGE_DEBUG = os.getenv("TRACE_IMAGE_DEBUG", "0").strip() == "1"
FORCE_SEND_LATEST = os.getenv("FORCE_SEND_LATEST", "0").strip() == "1"
RESET_SEEN = os.getenv("RESET_SEEN", "0").strip() == "1"
SEEN_FILE = os.getenv("SEEN_SET_FILE", "state/avdbs_t50_seen.txt")

# ===== Filters =====
EXCLUDE_IMAGE_SUBSTRINGS = [
    "/logo/","/banner/","/ads/","/noimage","/favicon","/thumb/","/placeholder/","/loading",".svg",
    "/img/level/","mb3_","avdbs_logo","main-search","new_9x9w.png","/img/19cert/","19_cert","19_popup",
]
ALLOWED_IMG_DOMAINS = {"avdbs.com","www.avdbs.com","i1.avdbs.com"}
CONTENT_PATH_ALLOW_RE = re.compile(r"/(data|upload|board|files?|attach)/", re.I)
BOILERPLATE_RE = re.compile(r"(로그아웃|마이페이지|모바일앱|연예정보|배우\s*순위|품번\s*검색|한줄평/추천|질문답변\s*커뮤니티|인기\s*게시글\s*전체\s*게시글)", re.I)

# ===== HTTP =====
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; AVDBS-t50Bot/8.0)",
    "Accept-Language": "ko,en;q=0.8",
    "Connection": "close",
})

# ===== State =====
def ensure_state_dir():
    pathlib.Path("state").mkdir(parents=True, exist_ok=True)

def load_seen() -> set[str]:
    ensure_state_dir()
    if RESET_SEEN:
        print("[debug] RESET_SEEN=1 → fresh run")
        return set()
    p = pathlib.Path(SEEN_FILE)
    if not p.exists(): return set()
    with open(p,"r",encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def append_seen(keys:list[str]):
    if not keys: return
    ensure_state_dir()
    with open(SEEN_FILE,"a",encoding="utf-8") as f:
        for k in keys: f.write(k+"\n")

# ===== Cookies (site + CDN) =====
def cookie_string_to_jar(raw:str)->requests.cookies.RequestsCookieJar:
    jar = requests.cookies.RequestsCookieJar()
    base_host = urlparse(AVDBS_BASE).hostname or "www.avdbs.com"
    cdn_host  = "i1.avdbs.com"
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part: continue
        k,v = part.split("=",1)
        k,v = k.strip(), v.strip()
        for dom in (base_host, "."+base_host.lstrip("."), cdn_host, "."+cdn_host):
            jar.set(k, v, domain=dom)
    return jar

def apply_cookie_string():
    if not AVDBS_COOKIE: return False
    SESSION.cookies.update(cookie_string_to_jar(AVDBS_COOKIE))
    return True

def force_adult_cookie():
    # 일부 페이지는 성인 쿠키 없으면 게이트 → 강제 주입 (서버가 무시할 수도 있으나 대체로 통과에 도움)
    for d in {urlparse(AVDBS_BASE).hostname or "www.avdbs.com", ".avdbs.com","i1.avdbs.com",".i1.avdbs.com"}:
        SESSION.cookies.set("adult_chk","1",domain=d)

# ===== URL canonicalization & filters =====
def canon_url_remove_noise(u:str)->str:
    pr = urlparse(u)
    if not pr.query: return u
    kept=[]
    for k,v in parse_qsl(pr.query, keep_blank_values=True):
        if k.lower() in {"reply","sort","page","s","g"}:
            continue
        kept.append((k,v))
    new_q = urlencode(kept, doseq=True)
    return urlunparse((pr.scheme,pr.netloc,pr.path,pr.params,new_q,pr.fragment))

ARTICLE_URL_RE = re.compile(r"^/board/\d+(?:\?.*)?$", re.I)
BOARD_TAB_RE   = re.compile(r"^/board/t\d+(?:/|$)", re.I)

def is_article_url(href:str, base:str)->str|None:
    if not href: return None
    full = urljoin(base, href.strip())
    u = urlparse(full)
    if u.netloc not in {"www.avdbs.com","avdbs.com"}: return None
    if BOARD_TAB_RE.match(u.path): return None
    if ARTICLE_URL_RE.match(u.path): return full
    return None

# ===== Helpers =====
def absolutize(base_url:str, url:str)->str:
    if not url: return ""
    if url.startswith("//"): return "https:"+url
    return urljoin(base_url, url)

def is_excluded_image(url:str)->bool:
    low = url.lower()
    return any(h in low for h in EXCLUDE_IMAGE_SUBSTRINGS)

def is_content_image(url:str)->bool:
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if host not in ALLOWED_IMG_DOMAINS: return False
        if not CONTENT_PATH_ALLOW_RE.search(u.path or ""): return False
    except Exception:
        return False
    return not is_excluded_image(url)

def download_bytes(url:str, referer:str)->bytes|None:
    try:
        headers = {"Referer": referer, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
        r = SESSION.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code==200 and r.content: return r.content
        print(f"[warn] download {r.status_code}: {url}")
    except Exception as e:
        print(f"[warn] download failed: {url} err={e}")
    return None

def tg_post(method:str, data:dict, files=None):
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", data=data, files=files, timeout=60)
    try: ok = r.json().get("ok", None)
    except Exception: ok = None
    print(f"[tg] {method} {r.status_code} ok={ok}")
    return r

def tg_send_text(text:str):
    return tg_post("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })

def send_photo_file(bytes_data:bytes, caption:str|None):
    return tg_post("sendPhoto",
                   {"chat_id": TELEGRAM_CHAT_ID, "caption": caption or "", "parse_mode": "HTML"},
                   files={"photo": ("image.jpg", BytesIO(bytes_data))})

# ===== Gate / Container / Summary =====
def is_login_gate(resp, soup)->bool:
    final_url = getattr(resp,"url","") or ""
    title_txt = (soup.title.string.strip() if soup.title and soup.title.string else "")
    big_text  = soup.get_text(" ", strip=True)[:2000]
    if "/login" in final_url: return True
    if "AVDBS" in title_txt and "로그인" in title_txt: return True
    if soup.find("input",{"name":"mb_id"}) and soup.find("input",{"name":"mb_password"}): return True
    if ("성인 인증" in big_text) and ("로그인" in big_text): return True
    return False

def pick_main_container(soup:BeautifulSoup):
    for sel in ["#bo_v_con","#view_content",".view_content",".board_view","article"]:
        node = soup.select_one(sel)
        if node: return node
    return soup

def strip_layout(node:BeautifulSoup):
    kill = ["header","nav","footer",".gnb",".snb",".side",".sidebar",".category",".tags",".tag",".btn",".btns",
            ".bo_v_nb",".bo_v_com",".bo_v_sns",".comment",".reply",".writer-info",".meta",".tool",".share"]
    for sel in kill:
        for el in node.select(sel): el.extract()

def summarize_text(node, max_chars=220)->str:
    strip_layout(node)
    for t in node(["script","style","noscript"]): t.extract()
    text = re.sub(r"\s+"," ", node.get_text(" ", strip=True))
    text = BOILERPLATE_RE.sub(" ", text)
    text = re.sub(r"\s+"," ", text).strip()
    if len(text)>max_chars: text = text[:max_chars]+"…"
    return text

# ===== Preflight & Login =====
def preflight_auth()->bool:
    r = SESSION.get(LIST_URL, timeout=TIMEOUT, headers={"Referer": AVDBS_BASE+"/"})
    r.encoding = r.apparent_encoding or "utf-8"
    head = r.text[:4000]
    if ("로그인" in head and "AVDBS" in head) or ("성인 인증" in head):
        return False
    return True

def login_with_credentials()->bool:
    """
    1) 로그인 페이지 GET -> 폼 action/hidden 토큰 수집
    2) mb_id / mb_password 필드 찾아 POST
    3) 성인 쿠키 강제 주입
    """
    if not (AVDBS_ID and AVDBS_PW):
        return False
    try:
        # 로그인 페이지 추정 경로들 시도
        cand_paths = ["/member/login", "/bbs/login.php", "/login"]
        login_html = None
        for p in cand_paths:
            resp = SESSION.get(urljoin(AVDBS_BASE, p), timeout=TIMEOUT, headers={"Referer": AVDBS_BASE+"/"})
            if resp.status_code==200 and resp.text:
                login_html = resp.text; login_url = resp.url; break
        if not login_html:
            print("[warn] login page not found"); return False

        soup = BeautifulSoup(login_html, "html.parser")
        form = soup.find("form")
        if not form:
            print("[warn] login form not found"); return False

        action = form.get("action") or login_url
        action = urljoin(login_url, action)

        payload = {}
        id_key = "mb_id"; pw_key = "mb_password"
        # hidden 포함 모든 input 수집
        for inp in form.find_all("input"):
            name = inp.get("name"); val = inp.get("value","")
            if not name: continue
            payload[name] = val

        # 흔한 필드 네임 보정
        for key in list(payload.keys()):
            lk = key.lower()
            if "id" in lk and lk in {"mb_id","user_id","login_id","userid"}:
                id_key = key
            if "pass" in lk or "pw" in lk:
                pw_key = key

        payload[id_key] = AVDBS_ID
        payload[pw_key] = AVDBS_PW
        payload.setdefault("keep_login","1")

        resp2 = SESSION.post(action, data=payload, timeout=TIMEOUT, headers={"Referer": login_url})
        if resp2.status_code not in (200,302): 
            print(f"[warn] login POST status {resp2.status_code}")
        force_adult_cookie()
        ok = preflight_auth()
        print(f"[debug] credential login result: {ok}")
        return ok
    except Exception as e:
        print(f"[warn] login exception: {e}")
        return False

# ===== Parsing =====
def parse_list()->list[dict]:
    r = SESSION.get(LIST_URL, timeout=TIMEOUT, headers={"Referer": AVDBS_BASE+"/"})
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    posts={}
    for a in soup.find_all("a", href=True):
        art = is_article_url(a["href"], LIST_URL)
        if not art: continue
        art = canon_url_remove_noise(art)
        title = a.get_text(strip=True) or "(제목 없음)"
        if art not in posts or len(title) > len(posts[art]["title"]):
            posts[art] = {"url": art, "title": title}

    res = list(posts.values())
    res.sort(key=lambda x: x["url"], reverse=True)
    print(f"[debug] (t50) list collected (articles only): {len(res)} items")
    return res

def parse_post(url:str):
    resp = SESSION.get(url, timeout=TIMEOUT, headers={"Referer": url})
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    if is_login_gate(resp, soup):
        print(f"[warn] login/adult gate detected, skip: {url}")
        return None

    container = pick_main_container(soup)
    summary = summarize_text(container)
    title = soup.title.string.strip() if soup.title and soup.title.string else "(제목 없음)"

    images=[]
    for img in container.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-echo")
        if not src: continue
        full = absolutize(url, src)
        if is_content_image(full): images.append(full)

    if not images:
        for a in container.find_all("a", href=True):
            h = a["href"].strip()
            if re.search(r"\.(jpg|jpeg|png|gif|webp)(?:\?|$)", h, re.I):
                full = absolutize(url, h)
                if is_content_image(full): images.append(full)

    images = list(dict.fromkeys(images))

    if len(summary) < 60 and not images:
        print(f"[warn] weak content (short text & no images), skip: {url}")
        return None

    if TRACE_IMAGE_DEBUG:
        print("[trace][t50] images(after whitelist):", images[:10])
        try: tg_send_text("🔍 t50 candidates:\n" + "\n".join(images[:10] or ["(no images)"]))
        except Exception: pass

    return {"title": title, "summary": summary, "images": images}

# ===== Main =====
def process():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID required")

    used_cookie = apply_cookie_string()
    if not preflight_auth():
        # 쿠키 실패 → 자격증명으로 로그인 시도
        if AVDBS_ID and AVDBS_PW:
            print("[info] cookie preflight failed → try credential login")
            if not login_with_credentials():
                tg_send_text("⚠️ t50: 쿠키/로그인 모두 실패. Secrets의 AVDBS_COOKIE 또는 AVDBS_ID/AVDBS_PW를 확인하세요.")
                return
        else:
            tg_send_text("⚠️ t50: 쿠키 프리플라이트 실패. AVDBS_COOKIE를 갱신하거나 AVDBS_ID/AVDBS_PW를 추가해주세요.")
            return

    posts = parse_list()
    if not posts:
        print("[info] no posts found (t50)"); return

    seen = load_seen()
    to_send=[]
    for p in posts:
        key = f"avdbs:t50:{p['url']}"
        if key not in seen:
            d=dict(p); d["_seen_key"]=key; to_send.append(d)

    if FORCE_SEND_LATEST and not to_send and posts:
        latest=dict(posts[0]); latest["_seen_key"]=f"avdbs:t50:{latest['url']}"
        to_send=[latest]; print("[debug] FORCE_SEND_LATEST=1 → sending most recent once (t50)")

    if not to_send:
        print("[info] no new posts to send (t50)"); return

    sent=[]
    for p in to_send:
        url = p["url"]
        data = parse_post(url)
        if data is None: continue

        title, summary, images = data["title"], data["summary"], data["images"]
        tg_send_text(f"📌 <b>{title}</b>\n{summary}\n{url}")
        time.sleep(1)
        for img in images[:10]:
            blob = download_bytes(img, url)
            if blob:
                send_photo_file(blob, None); time.sleep(1)
            else:
                print(f"[warn] skip image due to download failure: {img}")
        sent.append(p["_seen_key"])

    append_seen(sent)
    print(f"[info] appended {len(sent)} keys (t50)")

if __name__ == "__main__":
    process()
