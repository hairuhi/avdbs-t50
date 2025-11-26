# GitHub Actions Crawler for AVDBS

## Goal
Create a stable, scheduled crawler for `https://www.avdbs.com/board/t50` that runs on GitHub Actions. The crawler must handle the site's login requirement and JavaScript-based browser verification.
**Update**: The crawler will now send notifications to a Telegram Bot with post titles, links, and attached media (images/videos).

## User Review Required
> [!IMPORTANT]
> **Credentials Security**: You must NOT commit your password to the code. You will need to add `AVDBS_ID` and `AVDBS_PW` as **Secrets** in your GitHub repository settings.
> **Telegram Secrets**: You should also add `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` as Secrets.

## Proposed Changes

### Root Directory
#### [MODIFY] [crawler.py](file:///C:/Users/gereg/.gemini/antigravity/brain/d1ae1af9-45db-43e6-9b50-fc57cb566fd3/crawler.py)
- **New Logic**:
    - Iterate through the list of posts on the board.
    - For each post (limit to top 5-10 to prevent timeouts/spam):
        - Click/Navigate to the post detail page.
        - Extract the **Title**.
        - Extract **Image/Video URLs** from the content.
        - Call `send_telegram_message(token, chat_id, message, media_urls)`.
- **Dependencies**: Import `requests`.

#### [MODIFY] [requirements.txt](file:///C:/Users/gereg/.gemini/antigravity/brain/d1ae1af9-45db-43e6-9b50-fc57cb566fd3/requirements.txt)
- Add `requests`.

### GitHub Workflows
#### [MODIFY] [.github/workflows/crawl.yml](file:///C:/Users/gereg/.gemini/antigravity/brain/d1ae1af9-45db-43e6-9b50-fc57cb566fd3/.github/workflows/crawl.yml)
- Add environment variables for Telegram:
    - `TELEGRAM_TOKEN`: `${{ secrets.TELEGRAM_TOKEN }}`
    - `TELEGRAM_CHAT_ID`: `${{ secrets.TELEGRAM_CHAT_ID }}`

## Verification Plan

### Manual Verification
1.  **Local Test**:
    - User runs `python crawler.py` with all 4 environment variables set.
    - Verify that the Telegram bot receives messages with images/videos.
