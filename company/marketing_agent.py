"""
Marketing Agent — Lead Finder
Searches Hacker News for posts where people need help,
stores them as leads for the CEO Agent to review.

Uses HN's official Algolia API — completely open, no auth needed.
"""

import requests
import json
import time
from datetime import datetime

# Search queries that signal someone needs help
SEARCH_QUERIES = [
    "need help with",
    "looking for someone to",
    "can anyone help",
    "struggling with",
    "need advice on",
    "how do I",
    "need a developer",
    "need a consultant",
    "looking for recommendations",
]

# High value keywords that boost lead score
HIGH_VALUE_KEYWORDS = [
    "contract", "legal", "dispute", "business partner", "hr",
    "employee", "client", "payment", "lawsuit", "fired", "breach",
    "startup", "saas", "revenue", "customer", "product", "technical",
    "consulting", "freelance", "project", "budget"
]

# Low value keywords that reduce lead score
LOW_VALUE_KEYWORDS = [
    "homework", "school", "game", "fun", "meme",
    "joke", "random", "personal", "hobby"
]

HEADERS = {
    'User-Agent': 'NexusLeadFinder/1.0',
    'Accept': 'application/json',
}

def search_hn(query: str, limit: int = 10) -> list:
    """
    Search Hacker News using Algolia API.
    Focuses on Ask HN posts and comments where people ask for help.
    """
    url = "https://hn.algolia.com/api/v1/search"
    params = {
        "query": query,
        "tags": "ask_hn",  # Only "Ask HN" posts
        "hitsPerPage": limit,
        "numericFilters": "created_at_i>1700000000"  # Recent posts only
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("hits", [])
        else:
            print(f"[WARNING] HN search returned {resp.status_code} for '{query}'")
            return []
    except Exception as e:
        print(f"[ERROR] Failed to search HN for '{query}': {e}")
        return []

def is_relevant(post: dict) -> tuple[bool, str]:
    """
    Check if a post is relevant — someone asking for help
    with something the company could assist with.
    """
    title = post.get("title", "").lower()
    body = post.get("story_text") or post.get("comment_text") or ""
    body = body.lower()
    combined = f"{title} {body}"

    # Skip if too short
    if len(combined) < 30:
        return False, "too short"

    # Skip job postings
    skip_phrases = ["hiring", "we are looking for", "[who is hiring]", "job posting"]
    for phrase in skip_phrases:
        if phrase in combined:
            return False, "job posting"

    # Check for any of our search trigger phrases
    for phrase in SEARCH_QUERIES:
        if phrase.lower() in combined:
            return True, f"contains '{phrase}'"

    return True, "matched search query"

def score_lead(post: dict) -> int:
    """Score a lead 1-10 based on how promising it is."""
    score = 5

    title = post.get("title", "").lower()
    body = post.get("story_text") or post.get("comment_text") or ""
    body = body.lower()
    combined = f"{title} {body}"

    for term in HIGH_VALUE_KEYWORDS:
        if term in combined:
            score += 1

    for term in LOW_VALUE_KEYWORDS:
        if term in combined:
            score -= 2

    # Engagement
    points = post.get("points") or 0
    num_comments = post.get("num_comments") or 0
    if points > 10:
        score += 1
    if num_comments > 5:
        score += 1

    return max(1, min(10, score))

def find_leads() -> list[dict]:
    """
    Main function — searches HN and returns
    a list of relevant leads, sorted by score.
    """
    print("\n" + "="*60)
    print("MARKETING AGENT — Lead Finder (Hacker News)")
    print("="*60)
    print(f"Running {len(SEARCH_QUERIES)} searches...\n")

    seen_ids = set()
    all_leads = []

    for query in SEARCH_QUERIES:
        print(f"[→] Searching: '{query}'...")
        posts = search_hn(query, limit=10)

        relevant = 0
        for post in posts:
            post_id = post.get("objectID")

            # Skip duplicates
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            is_rel, reason = is_relevant(post)
            if is_rel:
                score = score_lead(post)
                lead = {
                    "id": post_id,
                    "title": post.get("title", "No title"),
                    "body": (post.get("story_text") or "")[:500],
                    "author": post.get("author"),
                    "url": f"https://news.ycombinator.com/item?id={post_id}",
                    "hn_url": post.get("url", ""),
                    "points": post.get("points") or 0,
                    "comments": post.get("num_comments") or 0,
                    "score": score,
                    "relevance_reason": reason,
                    "found_at": datetime.now().isoformat(),
                    "status": "pending_ceo_review",
                    "platform": "hackernews"
                }
                all_leads.append(lead)
                relevant += 1

        print(f"    Found {relevant} relevant leads")
        time.sleep(0.5)  # be polite

    # Sort by score
    all_leads.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate by title similarity
    final_leads = []
    seen_titles = set()
    for lead in all_leads:
        title_key = lead["title"][:50].lower()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            final_leads.append(lead)

    print(f"\n{'='*60}")
    print(f"TOTAL UNIQUE LEADS FOUND: {len(final_leads)}")
    print(f"{'='*60}\n")

    # Display top 5
    for i, lead in enumerate(final_leads[:5], 1):
        print(f"[{i}] Score: {lead['score']}/10")
        print(f"    Title: {lead['title'][:80]}")
        print(f"    Why: {lead['relevance_reason']}")
        print(f"    Points: {lead['points']} | Comments: {lead['comments']}")
        print(f"    URL: {lead['url']}")
        print()

    # Save for CEO Agent
    with open("company/leads.json", "w") as f:
        json.dump(final_leads, f, indent=2)
    print(f"[✓] {len(final_leads)} leads saved to company/leads.json")

    return final_leads

if __name__ == "__main__":
    leads = find_leads()
    print(f"\nDone. {len(leads)} leads ready for CEO review.")