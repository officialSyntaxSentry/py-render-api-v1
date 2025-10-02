from pymongo import MongoClient
from bson.objectid import ObjectId
import json
from datetime import datetime
import math
import logging
from collections import deque
import re
import sys



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




# --- Configuration: Weights for Suspicion Factors ---
# Adjust these weights based on how much each factor should contribute to suspicion.
# Higher weight means the factor is considered more suspicious.
FACTOR_WEIGHTS = {
    "length": 15,           # Max contribution based on length
    "is_code": 30,          # High importance if it looks like code
    "has_comments": 20,     # Comments in pasted content are suspicious
    "ai_markers": 15,       # Markers suggesting AI generation (heuristic)
    "code_density": 10,     # Ratio of code-like symbols/keywords
    "excessive_blanks": 5,  # Unusual formatting (many blank lines)
    "non_code_text": 5,     # Presence of significant non-code text mixed in
}

# Calculate the maximum possible score based on weights
MAX_POSSIBLE_SCORE = sum(FACTOR_WEIGHTS.values())

# --- Heuristic Definitions ---

# Keywords common across many programming languages
COMMON_KEYWORDS = {
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'return', 'break',
    'continue', 'class', 'struct', 'function', 'def', 'lambda', 'import', 'include',
    'using', 'namespace', 'public', 'private', 'protected', 'static', 'void',
    'int', 'float', 'double', 'char', 'string', 'bool', 'true', 'false', 'null',
    'new', 'delete', 'try', 'catch', 'finally', 'throw', 'const', 'let', 'var'
}

# Symbols common in programming languages
CODE_SYMBOLS = r'[\{\}\(\)\[\];,=\+\-\*\/%<>&\|!~\^\.:]'

# Regex for common comment types (single-line C++/Java/JS, Python, multi-line C-style)
COMMENT_REGEX = re.compile(r'(//.*)|(#.*)|(/\*.*?\*/)', re.DOTALL)

# Regex for potential AI markers or common boilerplate/explanation phrases
AI_MARKER_REGEX = re.compile(
    r'(```\w*|Here is a solution|The code below|Explanation:|Analysis:|Time Complexity:|Space Complexity:)',
    re.IGNORECASE
)

# Regex to find words (for keyword and text analysis)
WORD_REGEX = re.compile(r'\b\w+\b')

# --- Analysis Functions ---

def analyze_length(text):
    """Scores suspicion based on the length of the pasted text."""
    length = len(text)
    # Sigmoid-like scaling: Very short = low score, plateaus for very long
    # Adjust the parameters (scale, midpoint) as needed
    scale = 0.01
    midpoint = 150
    score = 1 / (1 + math.exp(-scale * (length - midpoint)))
    return score * FACTOR_WEIGHTS["length"]

def analyze_is_code(text, words, symbols_count, num_lines):
    """Scores suspicion based on indicators that the text is source code."""
    if not text.strip():
        return 0 # Empty paste isn't code

    keyword_count = sum(1 for word in words if word.lower() in COMMON_KEYWORDS)
    symbol_density = symbols_count / len(text) if len(text) > 0 else 0
    keyword_density = keyword_count / len(words) if len(words) > 0 else 0

    # Heuristic: combination of keywords, symbols, and line structure
    score = 0
    if keyword_count > 1 and symbols_count > 3:
        score += 0.5
    if symbol_density > 0.05: # More than 5% symbols
         score += 0.3
    if keyword_density > 0.02: # More than 2% keywords
         score += 0.2
    if num_lines > 3 and (text.strip().endswith('}') or text.strip().endswith(';')):
         score += 0.1 # Common code endings

    # Normalize score (0 to 1) - cap at 1
    normalized_score = min(score, 1.0)

    # If it looks like code, assign the full weight, otherwise very little
    # Use a threshold to decide if it's "codey" enough
    is_code_threshold = 0.4
    final_score = FACTOR_WEIGHTS["is_code"] if normalized_score >= is_code_threshold else normalized_score * 5 # Give some points even if unsure

    # Bonus points if code density analysis also agrees
    code_density_score = analyze_code_density(text, words, symbols_count)
    if code_density_score > FACTOR_WEIGHTS["code_density"] * 0.5: # If density score is > half its max
        final_score = min(final_score + 5, FACTOR_WEIGHTS["is_code"]) # Add small bonus, capped

    return final_score, normalized_score >= is_code_threshold # Return score and boolean flag

def analyze_has_comments(text):
    """Scores suspicion based on the presence of code comments."""
    if COMMENT_REGEX.search(text):
        return FACTOR_WEIGHTS["has_comments"]
    return 0

def analyze_ai_markers(text):
    """Scores suspicion based on heuristic markers of AI generation."""
    if AI_MARKER_REGEX.search(text):
        return FACTOR_WEIGHTS["ai_markers"]
    return 0

def analyze_code_density(text, words, symbols_count):
    """Scores suspicion based on the density of code-like elements."""
    if not text.strip():
        return 0

    keyword_count = sum(1 for word in words if word.lower() in COMMON_KEYWORDS)
    total_elements = len(words) + symbols_count
    code_elements = keyword_count + symbols_count

    density = code_elements / total_elements if total_elements > 0 else 0

    # Scale score based on density - higher density is more suspicious (up to a point)
    # Simple linear scaling for this example
    score = min(density * 2, 1.0) # Max score at 50% density
    return score * FACTOR_WEIGHTS["code_density"]

def analyze_excessive_blanks(text, num_lines):
    """Scores suspicion based on an unusually high number of blank lines."""
    if num_lines <= 1:
        return 0
    blank_lines = sum(1 for line in text.splitlines() if not line.strip())
    blank_ratio = blank_lines / num_lines

    # Suspicious if > 30% of lines are blank (adjust threshold as needed)
    if blank_ratio > 0.3 and num_lines > 5: # Only apply to slightly longer pastes
         # Scale score based on how much it exceeds the threshold
        score = min((blank_ratio - 0.3) / 0.7, 1.0) # Normalize excess ratio
        return score * FACTOR_WEIGHTS["excessive_blanks"]
    return 0

def analyze_non_code_text(text, words, is_likely_code):
    """Scores suspicion if there's significant natural language text mixed *with* code."""
    if not is_likely_code or not words: # Only relevant if it seems to be code
        return 0

    non_keyword_words = [word for word in words if word.lower() not in COMMON_KEYWORDS and not word.isdigit()]

    # Simple heuristic: check if there are many non-keyword words longer than 3 chars
    # This tries to filter out variable names (often short or camelCase) vs sentences
    long_natural_words = sum(1 for word in non_keyword_words if len(word) > 3 and word.isalpha())
    natural_word_ratio = long_natural_words / len(words) if len(words) > 0 else 0

    # Suspicious if a significant portion looks like natural language within code context
    if natural_word_ratio > 0.15 and len(words) > 10: # Adjust threshold
        # Scale score based on the ratio
        score = min((natural_word_ratio - 0.15) / 0.35, 1.0) # Normalize excess ratio
        return score * FACTOR_WEIGHTS["non_code_text"]
    return 0

# --- Main Analysis Function ---

def analyze_paste_suspicion(paste_data_json):
    """
    Analyzes a JSON object representing a paste event and returns a suspicion score.

    Args:
        paste_data_json (str or dict): The JSON string or loaded dictionary.

    Returns:
        dict: A dictionary containing the 'suspicion_percentage' and 'factor_scores'.
              Returns None if input is invalid or 'data' field is missing.
    """
    try:
        if isinstance(paste_data_json, str):
            event_data = json.loads(paste_data_json)
        else:
            event_data = paste_data_json # Assume it's already a dict

        pasted_text = event_data.get("data")
        if pasted_text is None:
            print("Error: 'data' field not found in JSON.")
            return None

    except json.JSONDecodeError:
        print("Error: Invalid JSON input.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during JSON processing: {e}")
        return None

    # --- Pre-calculate common elements ---
    pasted_text = pasted_text or "" # Ensure it's a string, even if empty
    lines = pasted_text.splitlines()
    num_lines = len(lines)
    words = WORD_REGEX.findall(pasted_text)
    symbols_count = len(re.findall(CODE_SYMBOLS, pasted_text))

    # --- Calculate scores for each factor ---
    factor_scores = {}
    total_score = 0

    # Length
    score = analyze_length(pasted_text)
    factor_scores["length"] = score
    total_score += score

    # Is Code (also returns boolean flag for use in other analyses)
    score, is_likely_code = analyze_is_code(pasted_text, words, symbols_count, num_lines)
    factor_scores["is_code"] = score
    total_score += score

    # Has Comments
    score = analyze_has_comments(pasted_text)
    factor_scores["has_comments"] = score
    total_score += score

    # AI Markers
    score = analyze_ai_markers(pasted_text)
    factor_scores["ai_markers"] = score
    total_score += score

    # Code Density (re-use calculation if needed, or rely on 'is_code')
    # We calculate it separately here for clarity, though parts overlap with 'is_code'
    score = analyze_code_density(pasted_text, words, symbols_count)
    factor_scores["code_density"] = score
    # Note: We might choose *not* to add this score directly if 'is_code' already
    # incorporates density heavily, to avoid double-counting. Here we add it.
    total_score += score

    # Excessive Blanks
    score = analyze_excessive_blanks(pasted_text, num_lines)
    factor_scores["excessive_blanks"] = score
    total_score += score

    # Non-code Text (only relevant if it looks like code)
    score = analyze_non_code_text(pasted_text, words, is_likely_code)
    factor_scores["non_code_text"] = score
    total_score += score


    # --- Calculate Final Percentage ---
    suspicion_percentage = 0
    if MAX_POSSIBLE_SCORE > 0:
        # Clamp score between 0 and max possible before calculating percentage
        clamped_score = max(0, min(total_score, MAX_POSSIBLE_SCORE))
        suspicion_percentage = (clamped_score / MAX_POSSIBLE_SCORE) * 100

    return {
        "suspicion_percentage": round(suspicion_percentage, 2),
        "factor_scores": {k: round(v, 2) for k, v in factor_scores.items()},
        "is_likely_code_flag": is_likely_code # Include the flag for context
    }


if __name__ == "__main__":
    
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing object_id argument"}))
        sys.exit(1)

    document_id = sys.argv[1]  # Get object_id from command line argument

    doc_content = fetch_document_by_id(document_id)
    if doc_content:
        analysis_result = analyze_paste_suspicion(doc_content)

        if analysis_result:
           
            json_output = json.dumps(analysis_result, indent=4, default=str)
            print(json_output)
        else:
            print("Analysis could not be performed on the document.")


