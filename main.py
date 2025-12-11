import os
import sys
import logging
from dotenv import load_dotenv
import utils
from crawler import AVDBSClient
from notifier import TelegramNotifier

# Load environment variables from .env file if present
load_dotenv()

def main():
    utils.setup_logging()
    logger = logging.getLogger("main")
    
    # 1. Configuration
    user_id = os.environ.get("AVDBS_ID")
    user_pw = os.environ.get("AVDBS_PW")
    tg_token = os.environ.get("TELEGRAM_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not all([user_id, user_pw, tg_token, tg_chat_id]):
        logger.error("Missing configuration. Please set AVDBS_ID, AVDBS_PW, TELEGRAM_TOKEN, and TELEGRAM_CHAT_ID.")
        return

    notifier = TelegramNotifier(tg_token, tg_chat_id)
    history = utils.load_history()
    
    # 2. Boards to monitor
    # 2. Boards to monitor
    boards = [
        {"name": "국산야동", "url": "https://www.avdbs.com/board/t50"},
        {"name": "서양야동", "url": "https://www.avdbs.com/board/t22"}
    ]
    
    client = AVDBSClient(headless=True)
    
    try:
        # 3. Login
        if not client.login(user_id, user_pw):
            logger.error("Login failed. Aborting.")
            notifier.send_message("❌ AVDBS Crawler Login Failed. Check credentials.")
            return

        utils.prepare_temp_dir()

        # 4. Process Boards
        for board in boards:
            new_posts = client.get_new_posts(board['url'], history)
            
            for post in new_posts:
                logger.info(f"Processing post: {post['title']}")
                
                # Extract Media
                media_urls = client.extract_media(post['url'])
                
                # Download Media
                local_media = client.download_media(media_urls, referer_url=post['url'])
                
                # Send Notification
                # Adding Label to the message
                msg_text = f"[{board['name']}] <b>{post['title']}</b>\n<a href='{post['url']}'>{post['url']}</a>"
                notifier.send_message(msg_text, local_media)
                
                # Update history immediately to avoid duplicate sends on crash
                history.append(post['url'])
                utils.save_history(history)
                
    except Exception as e:
        logger.error(f"Global error: {e}")
        notifier.send_message(f"❌ AVDBS Crawler Error: {e}")
    finally:
        client.close()
        utils.cleanup_temp_dir()
        logger.info("Done.")

if __name__ == "__main__":
    main()
