from pymongo import MongoClient
from bson.objectid import ObjectId
import json
from datetime import datetime
import math
import logging
from collections import deque
import re
from collections import Counter





# --- Configuration: Weights and Thresholds ---
# Adjust these weights based on how indicative you feel each factor is of cheating.
WEIGHTS = {
    'length_very_short': 0,    # Copying very little is usually fine
    'length_medium': 5,      # Moderately long copy - slightly suspicious
    'length_long': 15,       # Long copy - more suspicious
    'length_very_long': 25,  # Very long copy - highly suspicious

    'code_keywords': 20,     # Presence of common programming keywords
    'code_structure': 15,    # Presence of code structure like {}, ;, ()
    'specific_solution_keywords': 35, # Keywords explicitly suggesting a solution
    'suspicious_source_domain': 10, # Copied from known solution sites (Lowered weight as some sites like leetcode/github are common)
    'non_code_mixed_with_code': 15, # Unusual mix of code and natural language
    'comment_suspicion': 30, # Suspicious content within comments
}

# Define thresholds for content length
LENGTH_THRESHOLDS = {
    'medium': 30,
    'long': 100,
    'very_long': 300,
}

# Keywords indicating code structure or common programming constructs
CODE_KEYWORDS = {
    # C++/Java/C# style
    'public', 'private', 'protected', 'class', 'struct', 'namespace', 'using',
    'void', 'int', 'string', 'char', 'bool', 'double', 'float', 'long',
    'vector', 'map', 'set', 'list', 'array', 'deque', 'queue', 'stack',
    'new', 'delete', 'return', 'if', 'else', 'for', 'while', 'switch', 'case',
    'break', 'continue', 'try', 'catch', 'throw', 'include', 'import', '#include',
    # Python style
    'def', 'class', 'import', 'from', 'return', 'if', 'elif', 'else', 'for',
    'while', 'try', 'except', 'finally', 'raise', 'with', 'yield', 'lambda',
    'list', 'dict', 'set', 'tuple',
    # JS style
    'function', 'var', 'let', 'const', 'class', 'return', 'if', 'else', 'for',
    'while', 'switch', 'case', 'break', 'continue', 'try', 'catch', 'throw',
    'import', 'export', 'require', 'module', '=>', 'async', 'await',
}

# Keywords strongly suggesting copying a solution or from specific sources
SPECIFIC_SOLUTION_KEYWORDS = {
    'solution', 'answer', 'approach', 'logic', 'algorithm',
    'leetcode solution', 'geeksforgeeks', 'stackoverflow', 'github',
    'tutorial', 'explain', 'submission', 'best solution', 'optimal',
    'hackerrank', 'codeforces', 'accepted', 'time complexity', 'space complexity',
    # Common default comments from online IDEs/templates if they are unusual for the contest platform
    'main function', 'driver code',
}

# Domains often associated with solutions/cheating
# Be careful with overly broad domains like github.com or leetcode.com itself
SUSPICIOUS_DOMAINS = {
    'stackoverflow.com',
    'geeksforgeeks.org',
    'github.com', # Context needed; copying own repo is fine, copying solutions isn't
    # 'leetcode.com', # Copying from the *same* problem page might be okay (e.g., problem statement), but less so from discussion/solutions
    'tutorialspoint.com',
    'programiz.com',
    'w3schools.com', # Less likely full solutions, but possible snippets
    'chegg.com', # Often associated with academic dishonesty
    'coursehero.com',
    # Add pastebin-like sites if relevant
    'pastebin.com',
    'jsfiddle.net',
    'codepen.io',
}

# --- Helper Functions ---

def calculate_suspicion_level(percentage):
    """Assigns a qualitative level based on the percentage."""
    if percentage == 0:
        return "None"
    elif percentage < 15:
        return "Very Low"
    elif percentage < 35:
        return "Low"
    elif percentage < 60:
        return "Medium"
    elif percentage < 80:
        return "High"
    else:
        return "Very High"

def _safe_get_int(data, key_path, default=0):
    """Safely retrieves and converts a nested value to int."""
    value = data
    try:
        for key in key_path:
            value = value[key]
        # Value found, attempt conversion
        return int(value)
    except (KeyError, TypeError, ValueError):
        # Key path not found, value is not dict-like, or value cannot be int
        return default

def analyze_copied_content(data_text, problem_title=None):
    """Analyzes the text content for suspicious elements."""
    analysis = {'reasons': [], 'score': 0}
    # Max score possible JUST from content analysis factors
    max_score_possible_for_content = (WEIGHTS['code_keywords'] +
                                    WEIGHTS['code_structure'] +
                                    WEIGHTS['specific_solution_keywords'] +
                                    WEIGHTS['non_code_mixed_with_code'] +
                                    WEIGHTS['comment_suspicion'])

    if not data_text or not isinstance(data_text, str):
        return analysis, max_score_possible_for_content # Return zero score if no data

    # Normalize text for analysis
    lower_text = data_text.lower()
    words = set(re.findall(r'\b\w+\b', lower_text)) # Extract unique words

    # 1. Check for Code Keywords
    found_code_keywords = words.intersection(CODE_KEYWORDS)
    # Use a ratio or threshold to avoid penalizing short snippets with few keywords
    keyword_density = len(found_code_keywords) / len(words) if words else 0
    if len(found_code_keywords) > 3 or (len(words) > 5 and keyword_density > 0.2):
        analysis['score'] += WEIGHTS['code_keywords']
        analysis['reasons'].append(f"Contains significant code keywords ({len(found_code_keywords)} found: {list(found_code_keywords)[:5]}...)")

    # 2. Check for Code Structure (simple checks)
    structure_score = 0
    # Check for balanced braces/parens (crude indicator)
    if data_text.count('{') > 0 and data_text.count('{') == data_text.count('}'): structure_score += 3
    elif data_text.count('{') > 1 or data_text.count('}') > 1: structure_score += 2 # Unbalanced but present

    if data_text.count('(') > 0 and data_text.count('(') == data_text.count(')'): structure_score += 2
    elif data_text.count('(') > 1 or data_text.count(')') > 1: structure_score += 1

    if data_text.count(';') > 2: structure_score += 5 # Semicolons are strong indicators for some languages
    # Check for significant indentation (e.g., lines starting with 2+ spaces/tabs) - more common in Python/structured code
    if re.search(r'^\s{2,}', data_text, re.MULTILINE): structure_score += 5

    if structure_score > 4: # Only add score if multiple indicators are present
        capped_structure_score = min(structure_score, WEIGHTS['code_structure']) # Cap the score
        analysis['score'] += capped_structure_score
        analysis['reasons'].append(f"Contains code-like structures (braces, semicolons, indentation). Score contribution: {capped_structure_score}")


    # 3. Check for Specific Solution Keywords
    found_specific_keywords = words.intersection(SPECIFIC_SOLUTION_KEYWORDS)
    # Also check for problem title variations if provided
    if problem_title:
        problem_words_processed = set(re.findall(r'\b\w+\b', problem_title.lower()))
        # Check if the function name from the example might be present (case-insensitive, ignore underscores)
        # Example: "Restore IP Addresses" -> "restoreipaddresses"
        potential_func_name = "".join(word for word in problem_title.split() if word.isalnum()).lower()
        if potential_func_name and potential_func_name in lower_text.replace("_",""):
             found_specific_keywords.add(f"problem-related name ('{potential_func_name}')")

    if found_specific_keywords:
        analysis['score'] += WEIGHTS['specific_solution_keywords']
        analysis['reasons'].append(f"Contains keywords suggesting external solution/explanation ({len(found_specific_keywords)} found: {list(found_specific_keywords)[:5]}...)")

    # 4. Check for Mix of Code and Non-Code Language (Heuristic)
    lines = data_text.strip().split('\n')
    non_code_like_lines = 0
    code_like_lines = 0
    common_words = {'is', 'am', 'the', 'a', 'this', 'that', 'find', 'found', 'work', 'try', 'trying', 'app', 'code', 'help', 'what', 'why'}

    for line in lines:
        trimmed_line = line.strip()
        if not trimmed_line: continue

        is_comment = re.match(r'^(//|#|/\*|\*)', trimmed_line)
        is_code_start = re.match(r'^(public|private|def|class|struct|int|void|vector|map|set|if|for|while|return|\}| \{)', trimmed_line.lower())
        ends_like_code = trimmed_line.endswith((';', '{', '}', ')', ',', ':'))

        # Count lines that look like potential code
        if is_code_start or ends_like_code or any(kw in trimmed_line.lower() for kw in CODE_KEYWORDS):
             code_like_lines += 1

        # Count lines that look like natural language mixed in (and are not comments)
        # Criteria: Not a comment, doesn't start like code, doesn't end like code, contains common English words.
        elif not is_comment and not is_code_start and not ends_like_code:
             line_words = set(re.findall(r'\b\w+\b', trimmed_line.lower()))
             if line_words.intersection(common_words):
                  non_code_like_lines += 1

    # Trigger if there's a mix (at least one of each type)
    if code_like_lines > 0 and non_code_like_lines > 0:
         # Scale score based on the proportion of non-code lines? (Optional)
         # score_contribution = min(WEIGHTS['non_code_mixed_with_code'], 5 + non_code_like_lines * 5) # Example scaling
         score_contribution = WEIGHTS['non_code_mixed_with_code'] # Fixed weight for now
         analysis['score'] += score_contribution
         analysis['reasons'].append(f"Potential mix of code ({code_like_lines} lines) and informal text ({non_code_like_lines} lines) detected.")


    # 5. Analyze Comments for Suspicious Content
    # Regex to find common comment styles
    comments = re.findall(r'(//.*?$|#.*?$|/\*.*?\*/)', data_text, re.MULTILINE | re.DOTALL)
    suspicious_comment_found = False
    suspicious_keywords_in_comments = ['solution from', 'copied from', 'source:', 'credit:', 'stackoverflow', 'geeksforgeeks', 'leetcode discussion', 'chegg', 'github solution']
    for comment in comments:
        comment_lower = comment.lower()
        # Check for keywords inside comments
        if any(keyword in comment_lower for keyword in suspicious_keywords_in_comments):
            suspicious_comment_found = True
            break
    if suspicious_comment_found:
         analysis['score'] += WEIGHTS['comment_suspicion']
         analysis['reasons'].append("Suspicious keywords found within comments.")


    return analysis, max_score_possible_for_content

# --- Main Analysis Function ---

def analyze_copy_event(log_entry_json):
    """
    Analyzes a JSON log entry for a 'copy' event to determine suspicion level.

    Args:
        log_entry_json (str or dict): The JSON string or parsed dictionary
                                       representing the log entry.

    Returns:
        dict: An analysis result containing suspicion score, percentage,
              level, and reasons. Returns None if the input is invalid
              or not a 'copy' event.
    """
    try:
        if isinstance(log_entry_json, str):
            log_entry = json.loads(log_entry_json)
        elif isinstance(log_entry_json, dict):
            log_entry = log_entry_json
        else:
            raise ValueError("Input must be a JSON string or dictionary")

        # Basic validation
        if log_entry.get("eventType") != "copy":
            # print("Event type is not 'copy'. Skipping analysis.") # Optional logging
            return None
        if "data" not in log_entry:
            # print("Missing 'data' field. Skipping analysis.") # Optional logging
            return None

        # Extract relevant data
        copied_data = log_entry.get("data", "") # Use get with default for safety
        problem_title = log_entry.get("problemTitle") # Get problem context if available
        page_info = log_entry.get("page", {})
        source_hostname = page_info.get("hostname")

        # --- Calculate Content Length Safely ---
        # Default to length of the actual data string if field is missing/invalid
        default_length = len(copied_data) if isinstance(copied_data, str) else 0
        # Use helper to safely get and convert $numberInt
        content_length = _safe_get_int(log_entry, ["contentLength", "$numberInt"], default=default_length)
        # Fallback safety: if content_length is still 0 but copied_data isn't, use len(copied_data)
        if content_length == 0 and default_length > 0:
             content_length = default_length
        # --- End Content Length Calculation ---


        # Initialize scoring
        suspicion_score = 0
        # Calculate the theoretical maximum possible score based on configured weights
        max_possible_score = (max(WEIGHTS['length_very_short'], WEIGHTS['length_medium'], WEIGHTS['length_long'], WEIGHTS['length_very_long']) +
                              WEIGHTS['code_keywords'] +
                              WEIGHTS['code_structure'] +
                              WEIGHTS['specific_solution_keywords'] +
                              WEIGHTS['suspicious_source_domain'] +
                              WEIGHTS['non_code_mixed_with_code'] +
                              WEIGHTS['comment_suspicion']
                             )
        reasons = []

        # --- Perform Checks ---

        # 1. Check Content Length
        length_reason = ""
        length_score = 0
        length_weight_category = WEIGHTS['length_very_short'] # Default weight if short
        if content_length >= LENGTH_THRESHOLDS['very_long']:
            length_score = WEIGHTS['length_very_long']
            length_reason = f"Very long content copied ({content_length} chars)"
            length_weight_category = WEIGHTS['length_very_long']
        elif content_length >= LENGTH_THRESHOLDS['long']:
            length_score = WEIGHTS['length_long']
            length_reason = f"Long content copied ({content_length} chars)"
            length_weight_category = WEIGHTS['length_long']
        elif content_length >= LENGTH_THRESHOLDS['medium']:
            length_score = WEIGHTS['length_medium']
            length_reason = f"Medium length content copied ({content_length} chars)"
            length_weight_category = WEIGHTS['length_medium']
        else: # Short or very short
             length_score = WEIGHTS['length_very_short']
             length_reason = f"Short content copied ({content_length} chars)"
             # length_weight_category remains very_short

        if length_score > 0:
            suspicion_score += length_score
            reasons.append(length_reason)
        # Note: max_possible_score already includes the max possible length weight


        # 2. Analyze Content (Keywords, Structure, etc.)
        # Pass problem_title for better context
        content_analysis, max_content_score_contribution = analyze_copied_content(copied_data, problem_title)
        suspicion_score += content_analysis['score']
        reasons.extend(content_analysis['reasons'])
        # Note: max_possible_score calculation already includes these weights


        # 3. Check Source Domain
        if source_hostname:
            # Normalize domain (e.g., www.geeksforgeeks.org -> geeksforgeeks.org)
            # Handle potential edge cases like short domains or IPs if needed
            parts = source_hostname.split('.')
            if len(parts) >= 2:
                normalized_hostname = '.'.join(parts[-2:])
                if normalized_hostname in SUSPICIOUS_DOMAINS:
                    # Specific check for leetcode.com - only flag if not on the *same* problem page path (if available)
                    page_path = page_info.get("path")
                    problem_path_segment = f"/problems/{problem_title.lower().replace(' ', '-')}/" if problem_title else None # Approximate path segment

                    is_suspicious_leetcode = True
                    if normalized_hostname == 'leetcode.com' and problem_path_segment and page_path and problem_path_segment in page_path:
                         # Allow copying from the same problem page (e.g., description, examples)
                         # Still could be discussion/solutions tab, but less likely to trigger just based on domain
                         is_suspicious_leetcode = False
                         reasons.append(f"Copied from leetcode.com (problem page: {page_path}) - domain not flagged as suspicious.")


                    if normalized_hostname != 'leetcode.com' or is_suspicious_leetcode:
                        suspicion_score += WEIGHTS['suspicious_source_domain']
                        reasons.append(f"Copied from a potentially suspicious domain: {source_hostname}")
            else:
                 reasons.append(f"Could not normalize source domain: {source_hostname}")
        # Note: max_possible_score already includes the weight for suspicious_source_domain


        # --- Calculate Final Score and Level ---
        if max_possible_score <= 0: # Avoid division by zero if all weights are 0
             suspicion_percentage = 0.0
        else:
             # Ensure score doesn't exceed max possible (due to potential overlap or logic errors)
             # And ensure score is not negative
             suspicion_score = max(0, min(suspicion_score, max_possible_score))
             suspicion_percentage = round((suspicion_score / max_possible_score) * 100, 2)

        suspicion_level = calculate_suspicion_level(suspicion_percentage)

        # --- Format Output ---
        result = {
            "username": log_entry.get("username", "unknown"),
            "problemName": log_entry.get("problemName", "unknown"),
            "problemTitle": problem_title or log_entry.get("problemName", "unknown"), # Use title if available
            "timestamp_ms": _safe_get_int(log_entry, ["timestamp", "$date", "$numberLong"], default=None), # Get timestamp if needed
            "copied_text_preview": (copied_data[:100] + '...' if len(copied_data) > 100 else copied_data) if isinstance(copied_data, str) else "[Invalid Data Type]",
            "content_length": content_length,
            "source_hostname": source_hostname,
            "suspicion_score": suspicion_score,
            "max_possible_score": max_possible_score,
            "suspicion_percentage": suspicion_percentage,
            "suspicion_level": suspicion_level,
            "reasons": reasons if reasons else ["No specific suspicious factors identified."]
        }

        return result

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during analysis: {e}")
        import traceback # Import here for debugging if needed
        # traceback.print_exc() # Uncomment for detailed traceback
        return None




def fetch_document_by_id(document_id):
    # Connect to MongoDB
    client = MongoClient("mongodb+srv://admin:7vNJvFHGPVvbWBRD@syntaxsentry.rddho.mongodb.net/?retryWrites=true&w=majority&appName=syntaxsentry")
    db = client["test"]  # Select database 'test'
    collection = db["activities"]  
    
    # Fetch document by _id
    document = collection.find_one({"_id": ObjectId(document_id)})
    
    if document:
        return document
    else:
        print("No document found with _id:", document_id)


if __name__ == "__main__":
    document_id = "67e58bd911f5e4a410748e31"  # Replace with actual _id
    doc_cotent = fetch_document_by_id(document_id)
    analysis_result = analyze_copy_event(doc_cotent)
    print(json.dumps(analysis_result, indent=2))

