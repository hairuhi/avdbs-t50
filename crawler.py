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
            r.raise_for_status()
            print("Telegram text sent.")
        except Exception as e:
            print(f"Failed to send Telegram text: {e}")
        return

    # 2. Send Media
    # Telegram limits: 10 items per media group.
    # We'll just send the first 10 items.
    media_group = []
    for i, m_url in enumerate(media_urls[:10]):
        # Simple heuristic: check extension or assume photo if not obviously video
        media_type = "photo"
        if m_url.lower().endswith(('.mp4', '.mov', '.avi')):
            media_type = "video"
        
        media_item = {
            "type": media_type,
            "media": m_url
        }
        # Add caption to the first item
        if i == 0:
            media_item["caption"] = text
            media_item["parse_mode"] = "HTML"
            
        media_group.append(media_item)

    if media_group:
        url = f"{base_url}/sendMediaGroup"
        data = {"chat_id": chat_id, "media": str(media_group).replace("'", '"')} # JSON-like string for media
        # Note: requests can handle json parameter, but sendMediaGroup expects a JSON string in the 'media' field form-data or query param.
        # Let's use the json parameter of requests for simplicity if the endpoint supports it, 
        # but standard Bot API often prefers POST fields.
        # Better approach for 'media' parameter is sending it as a JSON string in data.
        import json
        data = {"chat_id": chat_id, "media": json.dumps(media_group)}
        
        try:
            r = requests.post(url, data=data)
            if r.status_code != 200:
                print(f"Failed to send media group: {r.text}. Falling back to text only.")
                # Fallback
                send_telegram_message(token, chat_id, text)
            else:
                print("Telegram media sent.")
        except Exception as e:
            print(f"Error sending media: {e}")
            send_telegram_message(token, chat_id, text)

def run():
    user_id = os.environ.get("AVDBS_ID")
    user_pw = os.environ.get("AVDBS_PW")
    tg_token = os.environ.get("TELEGRAM_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not user_id or not user_pw:
        print("Error: AVDBS_ID and AVDBS_PW environment variables must be set.")
        sys.exit(1)
        
    if not tg_token or not tg_chat_id:
        print("Warning: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set. Notifications will be skipped.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # 1. Login
            print("Navigating to login page...")
            page.goto("https://www.avdbs.com/menu/member/login.php")
            page.wait_for_selector("#member_uid", state="visible")
            
            print("Filling credentials...")
            page.fill("#member_uid", user_id)
            page.fill("#member_pwd", user_pw)
            
            print("Submitting login form...")
            with page.expect_navigation(timeout=15000):
                page.click(".btn_login")
            
            # 2. Navigate to target board
            target_url = "https://www.avdbs.com/board/t50"
            print(f"Navigating to {target_url}...")
            page.goto(target_url)
            
            # 3. Extract Post Links
            # We'll grab the first 5 posts to avoid spamming and timeouts
            posts = []
            rows = page.query_selector_all(".list_subject") # Adjust selector based on actual site structure if needed
            # Fallback if class not found, try generic links
            if not rows:
                links = page.query_selector_all("a")
                for link in links:
                    href = link.get_attribute("href")
                    text = link.inner_text().strip()
                    if href and "wr_id" in href and text:
                        full_url = href if href.startswith("http") else f"https://www.avdbs.com{href}"
                        posts.append({"title": text, "url": full_url})
                        if len(posts) >= 5: break
            
            print(f"Found {len(posts)} posts. Processing...")

            for post in posts:
                print(f"Processing: {post['title']}")
                try:
                    # Visit post detail
                    page.goto(post['url'])
                    page.wait_for_load_state("domcontentloaded")
                    
                    # Extract Media
                    media_urls = []
                    
                    # Images
                    imgs = page.query_selector_all(".view_content img") # Common class for content
                    if not imgs:
                        imgs = page.query_selector_all("#bo_v_con img") # Another common ID
                    
                    for img in imgs:
                        src = img.get_attribute("src")
                        if src:
                            full_src = src if src.startswith("http") else f"https://www.avdbs.com{src}"
                            media_urls.append(full_src)
                            
                    # Videos (HTML5 video tags)
                    videos = page.query_selector_all("video source")
                    for v in videos:
                        src = v.get_attribute("src")
                        if src:
                            full_src = src if src.startswith("http") else f"https://www.avdbs.com{src}"
                            media_urls.append(full_src)

                    # Send to Telegram
                    if tg_token and tg_chat_id:
                        msg_text = f"<b>{post['title']}</b>\n<a href='{post['url']}'>{post['url']}</a>"
                        send_telegram_message(tg_token, tg_chat_id, msg_text, media_urls)
                        
                    # Polite delay
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"Error processing post {post['title']}: {e}")
                    continue

        except Exception as e:
            print(f"An error occurred: {e}")
            page.screenshot(path="error_screenshot.png")
            raise
        finally:
            browser.close()

if __name__ == "__main__":
    run()
