import os, re, time, pathlib
from io import BytesIO
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

# === Telegram ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# === AVDBS 설정 ===
AVDBS_BASE = os.getenv("AVDBS_BASE", "https://www.avdbs.com").rstrip("/")
BOARD_PATH = os.getenv("AVDBS_BOARD_PATH", "/board/t50")
LIST_URL = f"{AVDBS_BASE}{BOARD_PATH}"

AVDBS_COOKIE = os.getenv("AVDBS_COOKIE", "")
AVDBS_ID = os.getenv("AVDBS_ID", "")
AVDBS_PW = os.getenv("AVDBS_PW", "")

TIMEOUT = 25
STATE_FILE = "state/t50_seen.txt"

# === 필터 ===
EXCLUDE_IMG = ["logo", "banner", "ads", "level", "19cert", "new_9x9w", "loading_img"]
VALID_VIDEO_DOMAINS = ["youtube.com", "youtu.be", "dood", "avdbs.com"]

# === 세션 설정 ===
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; AVDBS-T50Bot/9.0)",
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

# === 텔레그램 전송 ===
def tg_send_text(text):
    return requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    })

def tg_send_photo(bytes_data, caption=None):
    return requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                         data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption or ""},
                         files={"photo": ("image.jpg", BytesIO(bytes_data))})

# === 유틸 ===
def load_seen():
    pathlib.Path("state").mkdir(exist_ok=True)
    if not os.path.exists(STATE_FILE): return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(f.read().splitlines())

def save_seen(keys):
    pathlib.Path("state").mkdir(exist_ok=True)
    with open(STATE_FILE, "a", encoding="utf-8") as f:
        for k in keys: f.write(k + "\n")

def clean_url(url):
    if not url: return ""
    if url.startswith("//"): url = "https:" + url
    return urljoin(AVDBS_BASE, url)

def download_image(url):
    try:
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content
    except:
        pass
    return None

# === 크롤링 ===
def get_posts():
    r = session.get(LIST_URL, timeout=TIMEOUT)
    soup = BeautifulSoup(r.text, "html.parser")
    posts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/board/\d+", href):
            title = a.get_text(strip=True)
            url = clean_url(href)
            if title and url and url not in [p["url"] for p in posts]:
                posts.append({"title": title, "url": url})
    return posts

def parse_post(url):
    r = session.get(url, timeout=TIMEOUT)
    soup = BeautifulSoup(r.text, "html.parser")

    # 로그인/성인 페이지 차단
    if "로그인" in soup.text[:1000] or "성인 인증" in soup.text[:1000]:
        print(f"[warn] adult/login gate → skip {url}")
        return None

    container = soup.select_one("#bo_v_con") or soup.select_one(".view_content") or soup
    images = []
    videos = []

    for img in container.find_all("img"):
        src = img.get("src")
        if src and not any(x in src for x in EXCLUDE_IMG):
            images.append(clean_url(src))

    for iframe in container.find_all("iframe"):
        src = iframe.get("src", "")
        if any(dom in src for dom in VALID_VIDEO_DOMAINS):
            videos.append(clean_url(src))

    images = list(dict.fromkeys(images))
    videos = list(dict.fromkeys(videos))

    return {"title": soup.title.text.strip() if soup.title else "(제목 없음)", "url": url, "images": images, "videos": videos}

# === 실행 ===
def main():
    seen = load_seen()
    posts = get_posts()
    sent = []

    for post in posts:
        key = post["url"]
        if key in seen:
            continue

        data = parse_post(post["url"])
        if not data:
            continue

        title, url, images, videos = data["title"], data["url"], data["images"], data["videos"]

        if not images and not videos:
            print(f"[skip] no media {url}")
            continue

        # 사진
        for img in images[:10]:
            content = download_image(img)
            if content:
                tg_send_photo(content)
                time.sleep(1)

        # 동영상
        if videos:
            tg_send_text("🎬 영상 링크:\n" + "\n".join(videos))

        # 제목 + 원문 링크
        tg_send_text(f"<b>{title}</b>\n{url}")

        sent.append(key)
        time.sleep(2)

    save_seen(sent)
    print(f"[info] sent {len(sent)} new posts")

if __name__ == "__main__":
    main()
