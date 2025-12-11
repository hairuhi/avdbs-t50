import os
import time
import requests
import logging
from playwright.sync_api import sync_playwright, Page, BrowserContext

try:
    from playwright_stealth import stealth_sync
except ImportError:
    import playwright_stealth
    logging.error(f"Failed to import stealth_sync. Available attributes: {dir(playwright_stealth)}")
    # Define a dummy stealth_sync to prevent crash during import, but functionality will be missing
    def stealth_sync(page):
        logging.warning("Stealth mode disabled due to import error.")
from typing import List, Dict, Tuple, Optional
import utils

logger = logging.getLogger(__name__)

class AVDBSClient:
    def __init__(self, headless: bool = True):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        self.page = self.context.new_page()
        stealth_sync(self.page)
        self.session_cookies = None

    def login(self, user_id: str, user_pw: str) -> bool:
        """Logs into avdbs.com."""
        login_url = "https://www.avdbs.com/menu/member/login.php"
        logging.info(f"Navigating to login: {login_url}")
        
        try:
            self.page.goto(login_url, timeout=60000)
            self.page.wait_for_load_state("networkidle")

            # Check if already logged in or if input fields exist
            if self.page.is_visible("#member_uid"):
                logger.info("Filling login credentials...")
                self.page.fill("#member_uid", user_id)
                self.page.fill("#member_pwd", user_pw)
                
                with self.page.expect_navigation(timeout=60000):
                    self.page.click(".btn_login")
                
                # Verify login success (checking for logout button or similar)
                # Allowing some time for redirect
                self.page.wait_for_load_state("networkidle")
                
                if "login.php" in self.page.url:
                    logger.error("Login failed (still on login page). Check credentials.")
                    return False
                
                logger.info("Login successful.")
                self.session_cookies = self.context.cookies()
                return True
            else:
                logger.warning("Login fields not found. May be already logged in or blocked.")
                return False

        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def get_new_posts(self, board_url: str, history: List[str]) -> List[Dict[str, str]]:
        """Scrapes a board for new posts not in history."""
        logger.info(f"Scanning board: {board_url}")
        new_posts = []
        
        try:
            self.page.goto(board_url, timeout=60000)
            self.page.wait_for_load_state("networkidle")
            
            # Anti-bot check
            if "Access Denied" in self.page.title() or "Cloudflare" in self.page.title():
                logger.error(f"Blocked on {board_url}")
                return []

            # Select post links (adjust selector based on previous code: a.lnk.vstt)
            links = self.page.query_selector_all("a.lnk.vstt")
            
            for link in links:
                # Filter out notices (usually have a specific image or class)
                # Check for IMG inside H2 with class 'notice' based on old code
                is_notice = link.evaluate("el => el.querySelector('h2 img.notice') !== null")
                if is_notice:
                    continue

                href = link.get_attribute("href")
                if not href:
                    continue
                
                full_url = href if href.startswith("http") else f"https://www.avdbs.com{href}"
                
                # Check history
                if full_url in history:
                    continue
                
                # Get title
                title_el = link.query_selector("h2")
                title = title_el.inner_text().strip() if title_el else link.inner_text().strip()
                
                new_posts.append({"title": title, "url": full_url})
                if len(new_posts) >= 5: # Limit processing to 5 newest posts per run to avoid spam
                    break
            
            logger.info(f"Found {len(new_posts)} new posts on {board_url}")
            return new_posts

        except Exception as e:
            logger.error(f"Error scanning board {board_url}: {e}")
            return []

    def extract_media(self, post_url: str) -> List[str]:
        """Extracts image and video URLs from a post."""
        media_urls = []
        try:
            logger.info(f"Navigating to post: {post_url}")
            self.page.goto(post_url, timeout=60000)
            self.page.wait_for_load_state("domcontentloaded")
            
            # Scroll to bottom to trigger lazy loading
            for i in range(5):
                self.page.mouse.wheel(0, 500)
                self.page.wait_for_timeout(500)
            
            # Wait for any image to be present
            try:
                self.page.wait_for_selector(".view_content img, #bo_v_con img", timeout=5000)
            except:
                logger.warning("No images selector found immediately.")

            # Selectors
            imgs = self.page.query_selector_all(".view_content img, #bo_v_con img")
            logger.info(f"Found {len(imgs)} candidate image elements.")
            
            for img in imgs:
                # Check for lazy loading attributes first
                src = img.get_attribute("data-original") or img.get_attribute("data-src") or img.get_attribute("src")
                if src:
                    full_src = src if src.startswith("http") else f"https://www.avdbs.com{src}"
                    # Filter out common placeholders/icons
                    if any(x in full_src for x in ["blank.gif", "loading", "icon"]):
                        continue
                    media_urls.append(full_src)
            
            # Videos
            videos = self.page.query_selector_all("video source")
            for v in videos:
                src = v.get_attribute("src")
                if src:
                    full_src = src if src.startswith("http") else f"https://www.avdbs.com{src}"
                    media_urls.append(full_src)
            
            if not media_urls:
                logger.warning(f"No media found in {post_url}. Dumping content layout for debugging.")
                try:
                    content_html = self.page.inner_html("body")
                    # Log first 2000 chars of body or specific container to understand structure
                    logger.info(f"Page Content Sample: {content_html[:2000]}")
                    
                    # Try to find iframes commonly used for videos
                    iframes = self.page.query_selector_all("iframe")
                    for frame in iframes:
                        src = frame.get_attribute("src")
                        logger.info(f"Found iframe src: {src}")
                        if src and "youtube" in src:
                            media_urls.append(src) # Add youtube link directly?
                except Exception as e:
                    logger.error(f"Failed to dump debug HTML: {e}")

            logger.info(f"Extracted {len(media_urls)} valid media URLs.")
                    
        except Exception as e:
            logger.error(f"Error extracting media from {post_url}: {e}")
            
        return list(set(media_urls)) # Dedup

    def download_media(self, media_urls: List[str], referer_url: str = "https://www.avdbs.com/") -> List[Tuple[str, str]]:
        """Downloads media files to temp directory using requests (faster than playwright for downloading)."""
        downloaded = []
        if not media_urls:
            return []

        # Convert Playwright cookies to Requests cookies
        req_cookies = {}
        if self.session_cookies:
            for c in self.session_cookies:
                req_cookies[c['name']] = c['value']

        # Get User-Agent from playwright context if possible, or use fixed one
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        
        headers = {
            "User-Agent": ua,
            "Referer": referer_url
        }
        
        # Limit to 10 for telegram
        for i, url in enumerate(media_urls[:10]):
            try:
                r = requests.get(url, headers=headers, cookies=req_cookies, stream=True, timeout=15)
                if r.status_code == 200:
                    # Determine extension
                    path_clean = url.split("?")[0]
                    ext = os.path.splitext(path_clean)[1]
                    if not ext:
                        content_type = r.headers.get("Content-Type", "")
                        if "video" in content_type: ext = ".mp4"
                        elif "image" in content_type: ext = ".jpg"
                        else: ext = ".jpg"

                    filename = f"media_{int(time.time())}_{i}{ext}"
                    filepath = os.path.join(utils.TEMP_MEDIA_DIR, filename)

                    with open(filepath, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    m_type = "video" if ext.lower() in ['.mp4', '.mov', '.avi', '.webm'] else "photo"
                    downloaded.append((m_type, filepath))
                else:
                    logger.warning(f"Failed to download {url}: Status {r.status_code}")
            except Exception as e:
                logger.error(f"Exception downloading {url}: {e}")

        return downloaded

    def close(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()
