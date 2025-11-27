import os
import sys
import time
import requests
from playwright.sync_api import sync_playwright

def send_telegram_message(token, chat_id, text, media_urls=None):
    """
    Sends a message to Telegram. If media_urls is provided, sends them as a media group (album)
    or single photo/video.
    """
    base_url = f"https://api.telegram.org/bot{token}"
    
    # 1. Send Text Message first (or as caption if single media)
    if not media_urls:
        url = f"{base_url}/sendMessage"
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        try:
            r = requests.post(url, data=data)
            if r.status_code != 200:
                print(f"Telegram Error: {r.text}")
            else:
                print("Telegram text sent.")
        except Exception as e:
            print(f"Failed to send Telegram text: {e}")
        return

    # 2. Send Media
    # Telegram limits: 10 items per media group.
    media_group = []
    for i, m_url in enumerate(media_urls[:10]):
        media_type = "photo"
        if m_url.lower().endswith(('.mp4', '.mov', '.avi')):
            media_type = "video"
        
        media_item = {
            "type": media_type,
            "media": m_url
        }
        if i == 0:
            media_item["caption"] = text
            media_item["parse_mode"] = "HTML"
            
        media_group.append(media_item)

    if media_group:
        import json
        url = f"{base_url}/sendMediaGroup"
        data = {"chat_id": chat_id, "media": json.dumps(media_group)}
        
        try:
            r = requests.post(url, data=data)
            if r.status_code != 200:
                print(f"Failed to send media group: {r.text}. Falling back to text only.")
                send_telegram_message(token, chat_id, text)
            else:
                print("Telegram media sent.")
        except Exception as e:
            print(f"Error sending media: {e}")
            send_telegram_message(token, chat_id, text)

def crawl_board(page, board_url, tg_token, tg_chat_id):
    print(f"Navigating to {board_url}...")
    page.goto(board_url)
    page.wait_for_load_state("networkidle")
    
    # Extract Post Links using improved selector
    posts = []
    # Selector found: a.lnk.vstt (contains h2 with title)
    links = page.query_selector_all("a.lnk.vstt")
    
    if not links:
        print(f"Selector a.lnk.vstt not found on {board_url}. Trying generic fallback...")
        all_links = page.query_selector_all("a")
        for link in all_links:
            href = link.get_attribute("href")
            text = link.inner_text().strip()
            if href and "wr_id" in href and text and "board" in href:
                full_url = href if href.startswith("http") else f"https://www.avdbs.com{href}"
                posts.append({"title": text, "url": full_url})
                if len(posts) >= 5: break
    else:
        for link in links:
            href = link.get_attribute("href")
            # Title is usually inside h2, but sometimes direct text. Try both.
            title_el = link.query_selector("h2")
            text = title_el.inner_text().strip() if title_el else link.inner_text().strip()
            
            if href and text:
                full_url = href if href.startswith("http") else f"https://www.avdbs.com{href}"
                posts.append({"title": text, "url": full_url})
            if len(posts) >= 5: break

    print(f"Found {len(posts)} posts on {board_url}.")
    
    if len(posts) == 0:
        print(f"No posts found on {board_url}!")
        if tg_token and tg_chat_id:
            send_telegram_message(tg_token, tg_chat_id, f"⚠️ No posts found on {board_url}. Check logs.")
    
    for post in posts:
        print(f"Processing: {post['title']}")
        try:
            page.goto(post['url'])
            page.wait_for_load_state("domcontentloaded")
            
            media_urls = []
            # Images
            imgs = page.query_selector_all(".view_content img") 
            if not imgs: imgs = page.query_selector_all("#bo_v_con img")
            
            for img in imgs:
                src = img.get_attribute("src")
                if src:
                    full_src = src if src.startswith("http") else f"https://www.avdbs.com{src}"
                    media_urls.append(full_src)
                    
            # Videos
            videos = page.query_selector_all("video source")
            for v in videos:
                src = v.get_attribute("src")
                if src:
                    full_src = src if src.startswith("http") else f"https://www.avdbs.com{src}"
                    media_urls.append(full_src)

            if tg_token and tg_chat_id:
                msg_text = f"<b>{post['title']}</b>\n<a href='{post['url']}'>{post['url']}</a>"
                send_telegram_message(tg_token, tg_chat_id, msg_text, media_urls)
                
            time.sleep(2)
            
        except Exception as e:
            print(f"Error processing post {post['title']}: {e}")
            continue

def run():
    user_id = os.environ.get("AVDBS_ID")
    user_pw = os.environ.get("AVDBS_PW")
    tg_token = os.environ.get("TELEGRAM_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not user_id or not user_pw:
        print("Error: AVDBS_ID and AVDBS_PW environment variables must be set.")
        sys.exit(1)
        
    # Debug: Notify start
    if tg_token and tg_chat_id:
        send_telegram_message(tg_token, tg_chat_id, "🚀 Crawler Started")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # 1. Login
            print("Navigating to login page...")
            page.goto("https://www.avdbs.com/menu/member/login.php")
            
            try:
                page.wait_for_selector("#member_uid", state="visible", timeout=10000)
            except:
                print("Login input not found. Already logged in or page changed?")
            
            print("Filling credentials...")
            page.fill("#member_uid", user_id)
            page.fill("#member_pwd", user_pw)
            
            print("Submitting login form...")
            with page.expect_navigation(timeout=30000):
                page.click(".btn_login")
            
            # 2. Crawl Boards
            boards = [
                "https://www.avdbs.com/board/t50",
                "https://www.avdbs.com/board/t22"
            ]
            
            for board in boards:
                crawl_board(page, board, tg_token, tg_chat_id)

        except Exception as e:
            print(f"An error occurred: {e}")
            if tg_token and tg_chat_id:
                send_telegram_message(tg_token, tg_chat_id, f"❌ Crawler Error: {e}")
            raise
        finally:
            browser.close()

if __name__ == "__main__":
    run()
