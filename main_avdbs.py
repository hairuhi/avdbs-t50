import os, re, time, pathlib
from io import BytesIO
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

# === 기본 설정 ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AVDBS_BASE = os.getenv("AVDBS_BASE", "https://www.avdbs.com").rstrip("/")
BOARD_PATH = os.getenv("AVDBS_BOARD_PATH", "/board/t22")  # 기본은 t22
AVDBS_COOKIE = os.getenv("AVDBS_COOKIE", "")
TIMEOUT = 25

# === 동작 로그 및 상태 저장 ===
board_name = BOARD_PATH.strip("/").split("/")[-1]
STATE_FILE = f"state/{board_name}_seen.txt"
pathlib.Path("state").mkdir(exist_ok=True, parents=True)

# === 이미지/영상 필터 ===
EXCLUDE_IMG = [
    "logo", "banner", "ads", "level", "19cert", "new_9x9w", "loading_img",
    "favicon", "/thumb/", "/placeholder/", "aashop", "message_icon_main", "main-search-34x34", ""
]
VALID_VIDEO_DOMAINS = ["youtube", "youtu.be", "dood", "avdbs.com"]

# === 세션 ===
session = requests.Session()
session.headers.update({
    "User-Agent": f"Mozilla/5.0 (compatible; AVDBS-Bot/{board_name})",
    "Referer": AVDBS_BASE + "/"
})
for d in ["avdbs.com", ".avdbs.com", "i1.avdbs.com", ".i1.avdbs.com"]:
    session.cookies.set("adult_chk", "1", domain=d)
if AVDBS_COOKIE:
    for c in AVDBS_COOKIE.split(";"):
        if "=" in c:
            k, v = c.split("=", 1)
            for d in ["avdbs.com", ".avdbs.com", "i1.avdbs.com", ".i1.avdbs.com"]:
                session.cookies.set(k.strip(), v.strip(), domain=d)

# === 텔레그램 ===
def tg_send_text(text: str):
    return requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=60,
    )

def tg_send_photo(b: bytes, caption: str | None = None):
    return requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
        data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption or ""},
        files={"photo": ("image.jpg", BytesIO(b))},
        timeout=60,
    )

# === 상태 관리 ===
def load_seen() -> set[str]:
    if not os.path.exists(STATE_FILE): return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(x.strip() for x in f if x.strip())

def save_seen(keys: list[str]):
    if not keys: return
    with open(STATE_FILE, "a", encoding="utf-8") as f:
        for k in keys: f.write(k + "\n")

def clean_url(u: str) -> str:
    if not u: return ""
    if u.startswith("//"): u = "https:" + u
    return urljoin(AVDBS_BASE, u)

def download_image(u: str) -> bytes | None:
    try:
        r = session.get(u, timeout=TIMEOUT, headers={"Referer": AVDBS_BASE + "/"})
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content
    except Exception:
        pass
    return None

# === 게시판 목록 ===
def get_posts() -> list[dict]:
    url = f"{AVDBS_BASE}{BOARD_PATH}"
    r = session.get(url, timeout=TIMEOUT)
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    posts: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/board/\d+(?:\?.*)?$", href):
            title = a.get_text(strip=True)
            full = clean_url(href)
            if title and full not in [p["url"] for p in posts]:
                posts.append({"title": title, "url": full})
    posts.sort(key=lambda x: x["url"], reverse=True)
    return posts

# === 게시글 파싱 ===
def parse_post(url: str) -> dict | None:
    r = session.get(url, timeout=TIMEOUT)
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    if "성인 인증" in soup.text[:1500] or "로그인" in soup.text[:1500]:
        print(f"[warn] adult gate → skip {url}")
        return None

    content = soup.select_one("#bo_v_con") or soup.select_one(".view_content") or soup
    imgs, vids = [], []

    for img in content.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src or any(x in src for x in EXCLUDE_IMG):
            continue
        imgs.append(clean_url(src))

    for iframe in content.find_all("iframe"):
        src = (iframe.get("src") or "").strip()
        if src:
            host = (urlparse(src).hostname or "").lower()
            if any(dom in host for dom in VALID_VIDEO_DOMAINS):
                vids.append(clean_url(src))

    imgs = list(dict.fromkeys(imgs))
    vids = list(dict.fromkeys(vids))
    title = soup.title.text.strip() if soup.title else "(제목 없음)"
    return {"title": title, "url": url, "images": imgs, "videos": vids}

# === 실행 ===
def main():
    seen = load_seen()
    posts = get_posts()
    sent = []

    for p in posts:
        if p["url"] in seen:
            continue

        data = parse_post(p["url"])
        if not data:
            continue

        title, url, images, videos = data["title"], data["url"], data["images"], data["videos"]

        if not images and not videos:
            print(f"[skip] no media {url}")
            continue

        # 이미지 전송
        for u in images[:10]:
            imgdata = download_image(u)
            if imgdata:
                tg_send_photo(imgdata)
                time.sleep(1)

        # 영상 링크 전송
        if videos:
            tg_send_text("🎬 영상 링크:\n" + "\n".join(videos))

        # 제목 + 원문 링크
        tg_send_text(f"<b>{title}</b>\n{url}")

        sent.append(p["url"])
        time.sleep(2)

    save_seen(sent)
    print(f"[done] {board_name}: {len(sent)} new posts sent.")

if __name__ == "__main__":
    main()
