import httpx
import re
from typing import Optional

async def fetch_reddit_post(url: str) -> Optional[str]:
    """Fetch a Reddit post and format it as a case input for VERDICT."""
    
    # Convert to JSON API url
    clean = url.rstrip("/")
    if not clean.endswith(".json"):
        clean += ".json"

    headers = {"User-Agent": "VERDICT/1.0"}
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(clean, headers=headers, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()

    post = data[0]["data"]["children"][0]["data"]
    title = post.get("title", "")
    body = post.get("selftext", "")
    subreddit = post.get("subreddit", "")
    score = post.get("score", 0)

    # Get top comments
    comments = []
    try:
        comment_list = data[1]["data"]["children"]
        for c in comment_list[:3]:
            if c["kind"] == "t1":
                comment_body = c["data"].get("body", "")
                if len(comment_body) > 20:
                    comments.append(comment_body[:300])
    except:
        pass

    formatted = f"""
SOURCE: Reddit r/{subreddit}
TITLE: {title}

POST:
{body[:1500]}

TOP COMMENTS:
{chr(10).join(f'- {c}' for c in comments)}
    """.strip()

    return formatted


async def fetch_x_post(url: str) -> Optional[str]:
    """
    X (Twitter) requires API auth for full access.
    For now we extract what we can from the URL and prompt the user to paste content.
    """
    tweet_id = re.search(r'status/(\d+)', url)
    if tweet_id:
        return f"X Post ID: {tweet_id.group(1)} — Please paste the post content below for VERDICT to analyze."
    return None


async def ingest(source: str) -> str:
    """
    Takes a URL or raw text and returns formatted case input.
    Detects Reddit URLs automatically.
    """
    source = source.strip()

    if "reddit.com" in source:
        print(f"[INGEST] Fetching Reddit post...")
        result = await fetch_reddit_post(source)
        if result:
            print(f"[INGEST] Reddit post fetched successfully")
            return result

    if "twitter.com" in source or "x.com" in source:
        print(f"[INGEST] X post detected...")
        result = await fetch_x_post(source)
        if result:
            return result

    # Raw text input — pass through directly
    return source