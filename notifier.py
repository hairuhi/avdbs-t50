import os
import json
import logging
import requests
from typing import List, Tuple

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, text: str, media_files: List[Tuple[str, str]] = None):
        """
        Sends a message to Telegram, optionally with media.
        media_files: List of (media_type, file_path) tuples.
                     media_type should be 'photo' or 'video'.
        """
        if not media_files:
            self._send_text(text)
        else:
            self._send_media_group(text, media_files)

    def _send_text(self, text: str):
        url = f"{self.base_url}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        try:
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            logger.info("Telegram text sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send Telegram text: {e}")

    def _send_media_group(self, caption: str, media_files: List[Tuple[str, str]]):
        url = f"{self.base_url}/sendMediaGroup"
        
        media_group = []
        files_to_send = {}
        
        # Telegram allows max 10 items in a media group
        media_files = media_files[:10]

        for i, (m_type, m_path) in enumerate(media_files):
            file_key = f"media{i}"
            filename = os.path.basename(m_path)
            
            # Ensure correct media type string for Telegram
            tg_type = "photo" if m_type == "image" else "video" # mapping 'image' to 'photo' just in case, though 'photo' is correct.
            # actually our crawler might label it 'photo' or 'video' directly.
            
            media_item = {
                "type": m_type, # Expecting 'photo' or 'video'
                "media": f"attach://{file_key}"
            }
            
            # Attach caption to the first item
            if i == 0:
                media_item["caption"] = caption
                media_item["parse_mode"] = "HTML"
                
            media_group.append(media_item)
            
            try:
                f = open(m_path, "rb")
                files_to_send[file_key] = (filename, f)
            except IOError as e:
                logger.error(f"Could not open media file {m_path}: {e}")
                continue

        if not files_to_send:
            logger.warning("No valid files to send, falling back to text.")
            self._send_text(caption)
            return

        data = {
            "chat_id": self.chat_id, 
            "media": json.dumps(media_group)
        }
        
        try:
            response = requests.post(url, data=data, files=files_to_send, timeout=60)
            if response.status_code != 200:
                logger.error(f"Failed to send media group: {response.text}")
                # Fallback to text if media fails (e.g. file too big)
                self._send_text(caption) 
            else:
                logger.info("Telegram media group sent successfully.")
        except Exception as e:
            logger.error(f"Error sending media group: {e}")
            self._send_text(caption)
        finally:
            for _, f in files_to_send.values():
                f.close()
