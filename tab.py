
# --- START OF FILE tab.py ---

import json
import re
import sys
from datetime import datetime
from urllib.parse import urlparse
from pymongo import MongoClient

from bson import ObjectId

# --- Suspicion Patterns ---

# Domains known for AI assistance
AI_DOMAINS = {
    "openai.com",        # Includes ChatGPT
    "chatgpt.com",
    "claude.ai",
    "anthropic.com",
    "gemini.google.com",
    "bard.google.com",
    "perplexity.ai",
    "blackbox.ai",       # AI code generation/search
    "phind.com",         # AI search for developers
}

# Domains known for coding solutions, forums, and tutorials
# Note: The platform domain itself (e.g., leetcode.com) is handled specially
SOLUTION_DOMAINS = {
    "stackoverflow.com",
    "github.com",        # Can host solutions, needs context (keywords)
    "geeksforgeeks.org",
    "leetcode.com",      # Specifically check for /discuss/, solutions, or different problems - HANDLED AS PLATFORM
    "medium.com",        # Often hosts coding tutorials/solutions
    "dev.to",            # Blogging platform for developers
    "tutorialspoint.com",
    "w3schools.com",     # More foundational, less likely direct cheating
    "programiz.com",
    "chegg.com",         # Known for academic answers
    "coursehero.com",    # Known for academic answers
    # Add platform domains here if they shouldn't be treated as external solutions by default
}

# General search engine domains
SEARCH_DOMAINS = {
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "yahoo.com",
    "baidu.com",
    "yandex.com",
}

# Keywords often found in titles or URLs related to getting help/solutions
# Be careful with keywords like "code" if they appear in legitimate platform URLs
SUSPICIOUS_KEYWORDS = [
    "solution", "answer", #"code", # 'code' might be too common in platform URLs, reconsider adding
    "solve", "cheat", "hack",
    "discussion", "discuss", "forum", "community", # Context dependent
    "tutorial", "guide", "example", "reference", # Can be legitimate learning
    "pastebin", "jsfiddle", "codepen", # Code sharing sites
    "gpt", "claude", "gemini", "bard", "ai", "llm", # AI terms
    "translate", # Sometimes used to understand problem statements
]

# Keywords indicating legitimate activity within the coding platform
# Used to AVOID flagging when switching between problems/lists on the same platform
LEGITIMATE_PLATFORM_KEYWORDS = [
    "problems", "problemset", "list", "submissions", "contest", "profile",
    "explore", "ranking", "editorial", # Editorials *might* be disallowed during contests but are part of platform
    "description", "submit", "run", "testcases", # Common problem page elements
]

# --- Scoring Weights ---
# These contribute to a raw score which is then converted to a percentage
SCORE_WEIGHTS = {
    "TO_AI": 10,
    "TO_SOLUTION_DOMAIN_WITH_KEYWORDS": 8, # External solution site + keyword
    "TO_SOLUTION_DOMAIN_GENERIC": 5, # External solution site, no specific keyword found
    "TO_GITHUB_REPO": 6, # Possible solution repo
    "TO_SEARCH_ENGINE_WITH_PROBLEM": 5, # Search engine + problem title/ID/keyword
    "TO_SEARCH_ENGINE_GENERIC": 3, # Generic search engine use
    "TO_EXTERNAL_APPLICATION": 5, # Ambiguous intent
    "TO_SUSPICIOUS_KEYWORD_ONLY": 3, # Title/URL has keyword, domain not flagged otherwise
    "FROM_AI": 1, # Indicates they *were* on an AI site recently
    "FROM_SOLUTION": 1, # Indicates they *were* on a solution site recently
    "WITHIN_PLATFORM_TO_DIFFERENT_PROBLEM": 4, # Looking at other problems? (If not legit list nav)
    "WITHIN_PLATFORM_TO_DISCUSSION": 6, # Looking at discussions/forums on platform?
}

MAX_RAW_SCORE = 12 # Adjust this based on weights to set the ceiling for 100%

# --- Helper Functions ---

def get_domain(url):
    """Extracts the domain name (e.g., 'google.com') from a URL."""
    if not url or not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return None
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        # Remove 'www.' prefix if present
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain.lower()
    except ValueError:
        return None

def contains_keywords(text, keywords):
    """Checks if a string contains any of the specified keywords (case-insensitive)."""
    if not text or not isinstance(text, str):
        return False, None
    text_lower = text.lower()
    for keyword in keywords:
        keyword_lower = keyword.lower()
        # Use word boundaries for longer keywords to avoid partial matches
        # Allow short keywords (<=3) or specific AI terms to match without boundaries
        try:
            if len(keyword_lower) <= 3 or keyword_lower in ["ai", "gpt", "llm"] or re.search(r'\b' + re.escape(keyword_lower) + r'\b', text_lower):
                 return True, keyword
        except re.error: # Handle potential regex errors with complex keywords
             pass
        # Fallback for keywords potentially attached to punctuation
        if keyword_lower in text_lower:
             return True, keyword # Less precise match
    return False, None

def normalize_problem_identifier(problem_name_or_id):
    """Attempts to get a consistent identifier (like number or slug) from name/id."""
    if not problem_name_or_id: return None
    s_problem = str(problem_name_or_id).lower().strip()
    # Try to extract number from start or common patterns like '/problems/123/'
    match_num = re.match(r'^(\d+)', s_problem) or re.search(r'/(\d+)[-/]', s_problem)
    if match_num: return match_num.group(1)

    # Try to extract slug from URL path like '/problems/two-sum/'
    match_slug = re.search(r'/problems/([^/]+)', s_problem)
    if match_slug: return match_slug.group(1)

    # Basic slug from title/name
    slug = re.sub(r'[^a-z0-9\s-]', '', s_problem) # Keep letters, numbers, spaces, hyphens
    slug = re.sub(r'\s+', '-', slug).strip('-')    # Replace spaces with hyphens
    return slug if slug else None


# --- Core Analysis Logic ---

def analyze_tab_switch(doc):
    """
    Analyzes a single tab switch document for suspicious activity.
    Returns a score as a percentage.
    """
    raw_suspicion_score = 0
    reasons = []

    # Basic info extraction
    doc_id = str(doc.get("_id", "N/A"))
    username = doc.get("username", "N/A")
    problem_id = doc.get("problemId", None) # Keep as None if missing
    problem_title = doc.get("problemTitle", None) # Keep as None if missing
    platform = doc.get("platform", "").lower() # Ensure platform is lower case string
    timestamp_val = doc.get("timestamp")

    timestamp_ms = None
    timestamp_iso = "N/A" # Default value

    # Handle different timestamp formats (datetime object or BSON $date)
    if isinstance(timestamp_val, datetime):
        try:
            # Convert naive datetime to UTC assuming it represents UTC, or use timezone info if present
            if timestamp_val.tzinfo is None:
                 # Assuming timestamp is UTC if no timezone info
                 timestamp_ms = int(timestamp_val.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
            else:
                 timestamp_ms = int(timestamp_val.timestamp() * 1000)
            timestamp_iso = datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            timestamp_ms = None
            timestamp_iso = "N/A"
    elif isinstance(timestamp_val, dict):
         try:
             # Handle BSON $date format
             ts_val = timestamp_val.get("$date")
             if isinstance(ts_val, str): # ISO format string
                  dt_obj = datetime.fromisoformat(ts_val.replace('Z', '+00:00'))
                  timestamp_ms = int(dt_obj.timestamp() * 1000)
                  timestamp_iso = dt_obj.isoformat().replace("+00:00", "Z")
             elif isinstance(ts_val, dict): # $numberLong format
                 ts_long = ts_val.get("$numberLong")
                 if ts_long:
                     timestamp_ms = int(ts_long)
                     # Ensure milliseconds timestamp is valid
                     if timestamp_ms > 0:
                         timestamp_iso = datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                     else:
                         timestamp_iso = "N/A" # Invalid timestamp value
             elif isinstance(ts_val, (int, float)): # Direct milliseconds timestamp
                 timestamp_ms = int(ts_val)
                 if timestamp_ms > 0:
                    timestamp_iso = datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                 else:
                    timestamp_iso = "N/A" # Invalid timestamp value

         except Exception:
              timestamp_iso = "N/A" # Fallback if parsing fails


    from_url = doc.get("fromUrl", "")
    from_title = doc.get("fromTitle", "")
    to_url = doc.get("toUrl", "")
    to_title = doc.get("toTitle", "")

    # --- Analyze the Destination (toUrl, toTitle) ---
    to_domain = get_domain(to_url)
    to_text = f"{to_url} {to_title}".lower() # Combine URL and Title for keyword search

    # Platform domain identification (e.g., "leetcode.com")
    platform_domain = f"{platform}.com" if platform else None

    # Combine problem identifiers for search keyword check
    search_keywords = SUSPICIOUS_KEYWORDS[:] # Copy base list
    current_problem_norm = None
    if problem_id or problem_title:
        current_problem_norm = normalize_problem_identifier(problem_id) or normalize_problem_identifier(problem_title)
        if problem_title: # Add problem title words to keywords for search check
            search_keywords.extend(re.findall(r'\b\w+\b', problem_title.lower()))
        if problem_id:
             search_keywords.append(str(problem_id)) # Add problem ID


    if to_url == "external_application":
        raw_suspicion_score += SCORE_WEIGHTS["TO_EXTERNAL_APPLICATION"]
        reasons.append(f"Switched to External Application (Intent unknown)")
    elif to_domain:
        # 1. Check for AI domains
        if to_domain in AI_DOMAINS:
            raw_suspicion_score += SCORE_WEIGHTS["TO_AI"]
            reasons.append(f"Switched TO AI Domain: {to_domain}")

        # 2. Check for Navigation WITHIN the Platform (e.g., LeetCode -> LeetCode)
        elif platform_domain and to_domain == platform_domain:
            is_suspicious_platform_nav = False
            # Check for navigation to discussion forums
            if "/discuss/" in to_url.lower() or contains_keywords(to_text, ["discussion", "discuss", "forum", "community"])[0]:
                 # Avoid flagging if it's part of a legitimate context (e.g. problem description mentioning discussion link)
                 if not contains_keywords(to_text, LEGITIMATE_PLATFORM_KEYWORDS)[0]:
                     raw_suspicion_score += SCORE_WEIGHTS["WITHIN_PLATFORM_TO_DISCUSSION"]
                     reasons.append(f"Switched TO {platform} discussion forum: {to_title or to_url}")
                     is_suspicious_platform_nav = True

            # Check for navigation to a *different* problem (if not discussion)
            if not is_suspicious_platform_nav and current_problem_norm:
                 to_problem_norm = normalize_problem_identifier(to_url) or normalize_problem_identifier(to_title)
                 if to_problem_norm and to_problem_norm != current_problem_norm:
                     # Avoid penalizing switches to general problem lists/legit pages
                     found_legit_kw, _ = contains_keywords(to_text, LEGITIMATE_PLATFORM_KEYWORDS)
                     # Allow if the URL/title explicitly contains the *current* problem identifier (might be nav bar links)
                     contains_current_problem_ref = current_problem_norm in to_text
                     if not found_legit_kw and not contains_current_problem_ref:
                         raw_suspicion_score += SCORE_WEIGHTS["WITHIN_PLATFORM_TO_DIFFERENT_PROBLEM"]
                         reasons.append(f"Switched TO different problem page/URL on {platform}: {to_title or to_url}")
                         is_suspicious_platform_nav = True

            # If no specific suspicious pattern found within platform, consider it legitimate navigation
            if not is_suspicious_platform_nav:
                 reasons.append(f"Navigated within platform ({platform_domain}).") # Add neutral reason if needed later

        # 3. Check for Solution domains (EXTERNAL to the platform)
        elif to_domain in SOLUTION_DOMAINS:
            found_kw, matched_kw = contains_keywords(to_text, SUSPICIOUS_KEYWORDS)
            is_github_repo = to_domain == "github.com" and len(urlparse(to_url).path.split('/')) > 2 # Basic check for repo path

            if is_github_repo:
                raw_suspicion_score += SCORE_WEIGHTS["TO_GITHUB_REPO"]
                reasons.append(f"Switched TO GitHub repository: {to_url}")
                if found_kw:
                    raw_suspicion_score += 1 # Bonus point
                    reasons.append(f"  (URL/Title also contains suspicious keyword: '{matched_kw}')")
            elif found_kw:
                raw_suspicion_score += SCORE_WEIGHTS["TO_SOLUTION_DOMAIN_WITH_KEYWORDS"]
                reasons.append(f"Switched TO External Solution Domain ({to_domain}) with keyword: '{matched_kw}'")
            else:
                 raw_suspicion_score += SCORE_WEIGHTS["TO_SOLUTION_DOMAIN_GENERIC"]
                 reasons.append(f"Switched TO potential External Solution Domain: {to_domain}")

        # 4. Check for Search Engines
        elif to_domain in SEARCH_DOMAINS:
            found_prob_kw, matched_prob_kw = contains_keywords(to_text, search_keywords) # Check against problem details + suspicious words
            if found_prob_kw:
                 raw_suspicion_score += SCORE_WEIGHTS["TO_SEARCH_ENGINE_WITH_PROBLEM"]
                 reasons.append(f"Switched TO Search Engine ({to_domain}) with relevant keyword: '{matched_prob_kw}'")
            else:
                 raw_suspicion_score += SCORE_WEIGHTS["TO_SEARCH_ENGINE_GENERIC"]
                 reasons.append(f"Switched TO Search Engine: {to_domain}")

        # 5. Check for suspicious keywords if domain wasn't flagged otherwise (and not platform)
        else:
            found_kw, matched_kw = contains_keywords(to_text, SUSPICIOUS_KEYWORDS)
            if found_kw:
                raw_suspicion_score += SCORE_WEIGHTS["TO_SUSPICIOUS_KEYWORD_ONLY"]
                reasons.append(f"Switched TO URL/Title on '{to_domain}' containing suspicious keyword: '{matched_kw}'")

    # --- Analyze the Source (fromUrl) ---
    # Less weight, indicates previous context
    from_domain = get_domain(from_url)
    if from_domain:
        # Ignore if FROM is the platform itself
        if platform_domain and from_domain == platform_domain:
            pass # User was previously on the platform, expected behavior
        elif from_domain in AI_DOMAINS:
            raw_suspicion_score += SCORE_WEIGHTS["FROM_AI"]
            reasons.append(f"Switched FROM AI Domain: {from_domain}")
        elif from_domain in SOLUTION_DOMAINS:
            raw_suspicion_score += SCORE_WEIGHTS["FROM_SOLUTION"]
            reasons.append(f"Switched FROM potential Solution Domain: {from_domain}")


    # --- Final Score Calculation (Percentage) ---
    # Cap the raw score at MAX_RAW_SCORE before calculating percentage
    capped_raw_score = min(raw_suspicion_score, MAX_RAW_SCORE)

    # Calculate percentage
    if MAX_RAW_SCORE > 0:
         suspicion_percentage = round((capped_raw_score / MAX_RAW_SCORE) * 100)
    else:
         suspicion_percentage = 0 # Avoid division by zero

    # Ensure percentage is between 0 and 100
    final_percentage = max(0, min(suspicion_percentage, 100))

    # If score is 0, ensure there's a neutral reason if none were added
    if final_percentage == 0 and not reasons:
        reasons.append("No suspicious activity detected in this switch.")
    elif final_percentage > 0 and not reasons:
         # Should not happen if scoring logic is correct, but as a fallback
         reasons.append("Suspicious activity detected based on scoring rules.")
    elif "Navigated within platform" in reasons and final_percentage > 0:
        # Remove the neutral platform navigation message if other reasons caused a score > 0
        reasons = [r for r in reasons if r != f"Navigated within platform ({platform_domain})."]


    return {
        "document_id": doc_id,
        "username": username,
        "problem_id": problem_id,
        "problem_title": problem_title, # Added problem title to output
        "platform": platform,
        "timestamp": timestamp_iso,
        "suspicion_percentage": final_percentage, # Changed field name
        "raw_score": capped_raw_score, # Optional: include raw score before percentage calc
        "max_possible_score": MAX_RAW_SCORE, # Optional: include max possible score for context
        "reasons": reasons,
        "details": {
            "from": {"url": from_url, "title": from_title},
            "to": {"url": to_url, "title": to_title}
        }
    }


# --- MongoDB Connection and Main Execution ---
MONGO_URI = "mongodb+srv://admin:7vNJvFHGPVvbWBRD@syntaxsentry.rddho.mongodb.net/?retryWrites=true&w=majority&appName=syntaxsentry"
DATABASE_NAME = "test"
COLLECTION_NAME = "activities"

def fetch_document_by_id(document_id):
    """Fetches a single document from MongoDB by its _id."""
    client = None # Initialize client to None
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) # Added timeout
        # Test connection
        client.admin.command('ping')
        db = client[DATABASE_NAME]
        collection = db[COLLECTION_NAME]

        # Validate ObjectId
        try:
            obj_id = ObjectId(document_id)
        except Exception:
            return None, f"Invalid ObjectId format: {document_id}"

        document = collection.find_one({"_id": obj_id})

        if document:
            return document, None
        else:
            return None, f"No document found with _id: {document_id}"
    except Exception as e:
        return None, f"Database connection or query error: {e}"
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    # Check arguments
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing object_id argument"}))
        sys.exit(1)

    document_id = sys.argv[1]
    doc_content, error = fetch_document_by_id(document_id)

    if error:
        print(json.dumps({"error": error}))
        sys.exit(1)

    if doc_content:
        if doc_content.get("eventType") not in ["tab_switch", "tab_deactivated", "tab_activated", "window_blurred","window_focused","url_change"]:
            print(json.dumps({"error": f"Document {document_id} is not a 'tab_switch' event (eventType: {doc_content.get('eventType')})"}))
            sys.exit(1)

        # Perform analysis and return the result
        try:
            analysis_result = analyze_tab_switch(doc_content)
            # Print ONLY the JSON result to stdout, compact format
            print(json.dumps(analysis_result, default=str, separators=(',', ':')))
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"error": f"Error during analysis: {e}", "document_id": document_id}))
            sys.exit(1)

    else:
        # fetch_document_by_id already returned an error message if retrieval failed
        # This case should ideally not be reached if error handling above is correct
        print(json.dumps({"error": f"Failed to retrieve document {document_id}, specific reason not provided."}))
        sys.exit(1)
# --- END OF FILE tab.py ---