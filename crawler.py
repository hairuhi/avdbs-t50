import os
import sys
import time
import json
import shutil
import requests
from playwright.sync_api import sync_playwright

HISTORY_FILE = "sent_posts.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def download_media(media_urls, session_headers=None):
    """
    Downloads media files to a temporary directory.
    Returns a list of tuples: (media_type, file_path)
    """
    if not media_urls:
        return []

    temp_dir = "temp_media"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    downloaded_files = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "Referer": "https://www.avdbs.com/"
    }
    if session_headers:
        headers.update(session_headers)

    for i, url in enumerate(media_urls[:10]): # Limit to 10 for Telegram
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=10)
            if r.status_code == 200:
                ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
                if not ext: ext = ".jpg"
                
                filename = f"media_{i}{ext}"
                filepath = os.path.join(temp_dir, filename)
                
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                media_type = "video" if ext.lower() in ['.mp4', '.mov', '.avi', '.webm'] else "photo"
                downloaded_files.append((media_type, filepath))
            else:
                print(f"Failed to download {url}: {r.status_code}")
        except Exception as e:
            print(f"Error downloading {url}: {e}")

    return downloaded_files

def send_telegram_message(token, chat_id, text, media_files=None):
    """
    Sends a message to Telegram. 
    media_files: list of (type, filepath) tuples.
    """
    base_url = f"https://api.telegram.org/bot{token}"
    
    # 1. Text Only
    if not media_files:
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

    # 2. Media Group (with local files)
    # Using multipart/form-data to upload files
    url = f"{base_url}/sendMediaGroup"
    
    media_group = []
    files_to_send = {}
    
    for i, (m_type, m_path) in enumerate(media_files):
        file_key = f"media{i}"
        filename = os.path.basename(m_path)
        
        # 'attach://<file_key>' tells Telegram to look in the multipart form data
        media_item = {
            "type": m_type,
            "media": f"attach://{file_key}"
        }
        if i == 0:
            media_item["caption"] = text
            media_item["parse_mode"] = "HTML"
            
        media_group.append(media_item)
        
        # Open file for reading in binary mode
        f = open(m_path, "rb")
        files_to_send[file_key] = (filename, f)

    data = {"chat_id": chat_id, "media": json.dumps(media_group)}
    
    try:
        r = requests.post(url, data=data, files=files_to_send)
        if r.status_code != 200:
            print(f"Failed to send media group: {r.text}. Falling back to text.")
            send_telegram_message(token, chat_id, text) # Fallback to text
        else:
            print("Telegram media sent.")
    except Exception as e:
        print(f"Error sending media: {e}")
        send_telegram_message(token, chat_id, text)
    finally:
        # Close all file handles
        for _, f in files_to_send.values():
            f.close()
        # Clean up temp dir
        shutil.rmtree("temp_media", ignore_errors=True)

def crawl_board(page, board_url, tg_token, tg_chat_id, history):
    print(f"Navigating to {board_url}...")
    page.goto(board_url)
    page.wait_for_load_state("networkidle")
    
    # Extract Post Links
    # Logic:
    # 1. Get all post links (a.lnk.vstt).
    # 2. Filter OUT those that contain <img class="notice"> inside their <h2>.
    # 3. Take the first 5 strictly normal posts.
    
    posts = []
    all_links = page.query_selector_all("a.lnk.vstt")
    
    for link in all_links:
        # Check if it's a notice
        is_notice = link.evaluate("el => el.querySelector('h2 img.notice') !== null")
        
        if not is_notice:
            href = link.get_attribute("href")
            title_el = link.query_selector("h2")
            text = title_el.inner_text().strip() if title_el else link.inner_text().strip()
            
            if href and text:
                full_url = href if href.startswith("http") else f"https://www.avdbs.com{href}"
                
                # Deduplication Check
                if full_url not in history:
                    posts.append({"title": text, "url": full_url})
        
        if len(posts) >= 5:
            break

    print(f"Found {len(posts)} NEW normal posts on {board_url}.")
    
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

            # Download Media
            local_media = []
            if media_urls:
                # We can try to grab cookies from playwright to use in requests if needed,
                # but for now let's try standard requests with Referer.
                local_media = download_media(media_urls)

            if tg_token and tg_chat_id:
                msg_text = f"<b>{post['title']}</b>\n<a href='{post['url']}'>{post['url']}</a>"
                send_telegram_message(tg_token, tg_chat_id, msg_text, local_media)
                
                # Add to history if sent successfully (or attempted)
                history.append(post['url'])
                save_history(history)
                
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
        
    # Load History
    history = load_history()
        
    # Debug: Notify start (only if verbose/debug mode, maybe skip for cron to reduce spam? user asks for duplicates off)
    # Let's keep it for now but maybe make it less intrusive or remove if not needed.
    # The user asked for "deduplication", so startup message is fine, but maybe redundant if it runs every 3h.
    # I'll comment it out to reduce noise based on user preference for "no duplicates".
    # if tg_token and tg_chat_id:
    #     send_telegram_message(tg_token, tg_chat_id, "🚀 Crawler Started")

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
                crawl_board(page, board, tg_token, tg_chat_id, history)


        except Exception as e:
            print(f"An error occurred: {e}")
            if tg_token and tg_chat_id:
                send_telegram_message(tg_token, tg_chat_id, f"❌ Crawler Error: {e}")
            raise
        finally:
            browser.close()

if __name__ == "__main__":
    run()
