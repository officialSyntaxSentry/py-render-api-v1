import re
import sys
import math
from collections import Counter
import sys
from pymongo import MongoClient
from bson.objectid import ObjectId
import logging

# Get logger from main application or create a new one if imported directly
logger = logging.getLogger("py-api.checkcodetype")

def fetch_document_by_id(document_id):
    # Connect to MongoDB
    try:
        logger.info(f"Fetching document with ID: {document_id}")
        client = MongoClient("mongodb+srv://admin:7vNJvFHGPVvbWBRD@syntaxsentry.rddho.mongodb.net/?retryWrites=true&w=majority&appName=syntaxsentry")
        db = client["test"]  # Select database 'test'
        collection = db["activities"]  
        
        # Fetch document by _id
        document = collection.find_one({"_id": ObjectId(document_id)})
        
        if document:
            logger.info(f"Document found for ID: {document_id}")
            return document
        else:
            logger.warning(f"No document found with _id: {document_id}")
            return None
    except Exception as e:
        logger.error(f"Error fetching document with ID {document_id}: {str(e)}")
        return None


# --- Weights for Different Feature Types ---
# Higher weights mean stronger indicators
WEIGHTS = {
    'unique_keyword': 8,      # Keywords very specific to one language (e.g., 'yield' in Python/JS, 'synchronized' in Java)
    'common_keyword': 3,      # Keywords shared by some (e.g., 'class', 'if', 'for')
    'stdlib_indicator': 7,    # Use of standard library elements (e.g., 'java.util', 'std::', 'console.log')
    'syntax_pattern': 6,      # Characteristic syntax (e.g., '#include', 'def func():', '=>', 'System.out')
    'operator': 4,            # Operators somewhat unique (e.g., '===', '->', '::')
    'comment_style': 2,       # Comment types (# vs // vs /* */)
    'declaration': 5,         # Variable/function declaration styles
    'structure': 5,           # Overall structure hints (indentation vs braces, package decl)
    'common_practice': 3,     # Idiomatic usage (e.g., 'self' in Python, 'this' in Java/JS)
}

# --- Language Feature Definitions ---
# Using regex patterns. \b ensures whole word matching.
FEATURES = {
    'Python': [
        # Unique Keywords / Syntax
        (r'\bdef\s+\w+\s*\(.*\):', WEIGHTS['syntax_pattern']),
        (r'\belif\b', WEIGHTS['unique_keyword']),
        (r'\b(yield|async|await)\b', WEIGHTS['unique_keyword']), # Also in JS, but context matters
        (r'^\s*@\w+', WEIGHTS['syntax_pattern']), # Decorators
        (r'^\s*from\s+[\w.]+\s+import\s+', WEIGHTS['syntax_pattern']),
        (r'^\s*import\s+[\w.]+(\s+as\s+\w+)?$', WEIGHTS['syntax_pattern']), # More specific import
        (r'\[.*?\s+for\s+\w+\s+in\s+.*?\]', WEIGHTS['syntax_pattern']), # List comprehension
        (r'f"|\'.*?{.*?}.*?\'|".*?{.*?}.*?"', WEIGHTS['syntax_pattern']), # f-strings
        (r'\b(True|False|None)\b', WEIGHTS['unique_keyword']),
        (r'"""|\'\'\'', WEIGHTS['syntax_pattern']), # Docstrings (often)
        # Common Keywords
        (r'\b(class|if|else|while|for|try|except|finally|return|in|is|lambda)\b', WEIGHTS['common_keyword']),
        # Standard Library / Common Practice
        (r'\bself\b', WEIGHTS['common_practice']),
        (r'\b__init__\b|\b__main__\b', WEIGHTS['common_practice']),
        (r'\b(os|sys|re|json|math|datetime|requests)\b', WEIGHTS['stdlib_indicator']),
        (r'\bprint\(', WEIGHTS['stdlib_indicator']), # Needs paren for Python 3
        # Structure
        (r':\s*$', WEIGHTS['structure']), # Colon for blocks (heuristic)
        # Comments
        (r'#.*', WEIGHTS['comment_style']),
    ],
    'C++': [
        # Unique Keywords / Syntax / Preprocessor
        (r'#include\s*<.*?>', WEIGHTS['syntax_pattern'] * 2), # Very strong indicator
        (r'#include\s*".*?"', WEIGHTS['syntax_pattern'] * 2),
        (r'#define|#ifdef|#ifndef|#endif', WEIGHTS['syntax_pattern']),
        (r'\b(std|boost)::', WEIGHTS['stdlib_indicator'] * 2), # Namespace usage
        (r'::', WEIGHTS['operator']), # Scope resolution
        (r'\b(template)\s*<.*?>', WEIGHTS['unique_keyword']),
        (r'\b(typename|nullptr|constexpr|auto|decltype)\b', WEIGHTS['unique_keyword']),
        (r'->', WEIGHTS['operator']), # Pointer member access
        (r'\b(new|delete)\b', WEIGHTS['unique_keyword']), # Manual memory management
        (r'\b(struct|enum)\b', WEIGHTS['common_keyword']), # Also in C, but common
        (r'\b(virtual|explicit|friend|mutable|static_cast|dynamic_cast)\b', WEIGHTS['unique_keyword']),
        # Common Keywords / Types
        (r'\b(class|if|else|while|for|do|switch|case|try|catch|return|namespace|using)\b', WEIGHTS['common_keyword']),
        (r'\b(int|float|double|char|void|bool|long|short|unsigned)\b', WEIGHTS['common_keyword']), # More specific C types
        # Standard Library / Common Practice
        (r'\b(cout|cin|cerr)\b', WEIGHTS['stdlib_indicator']),
        (r'\b(vector|string|map|set|list|deque|pair|tuple|algorithm|iostream|fstream|memory)\b', WEIGHTS['stdlib_indicator']),
         # Declaration / Structure
        (r'\b(int|void)\s+main\s*\(.*\)', WEIGHTS['structure'] * 2), # Main function signature
        (r'\w+\s*\*\s*\w+|\w+\s*\&\s*\w+', WEIGHTS['declaration']), # Pointer/Reference declaration
        (r'\b\w+\s*\(.*\)\s*const\b', WEIGHTS['declaration']), # Const methods
        (r';\s*$', WEIGHTS['structure']), # Semicolons
        (r'[{}]', WEIGHTS['structure']), # Braces
        # Comments
        (r'//.*', WEIGHTS['comment_style']),
        (r'/\*.*?\*/', WEIGHTS['comment_style']),
    ],
    'Java': [
        # Unique Keywords / Syntax
        (r'\b(import\s+java\.|import\s+javax\.|import\s+android\.)', WEIGHTS['stdlib_indicator'] * 2.5), # Very strong indicator
        (r'\b(public|private|protected|static|final|abstract|synchronized|transient|volatile)\b', WEIGHTS['unique_keyword']),
        (r'\b(package)\s+[\w.]+;', WEIGHTS['syntax_pattern']),
        (r'System\.(out|err)\.print(ln)?\(', WEIGHTS['stdlib_indicator'] * 2), # Very strong indicator
        (r'\b(String|Integer|Double|Boolean|ArrayList|HashMap|List|Map|File|Exception)\b', WEIGHTS['stdlib_indicator']), # Common classes
        (r'\b(extends|implements|throws|instanceof)\b', WEIGHTS['unique_keyword']),
        (r'@\w+', WEIGHTS['syntax_pattern']), # Annotations (@Override etc)
        (r'\b(try|catch|finally)\b', WEIGHTS['common_keyword']), # Exception handling is prominent
        (r'\b(new)\s+\w+\s*\(', WEIGHTS['common_keyword']), # Object creation syntax
         # Common Keywords / Types
        (r'\b(class|interface|enum|if|else|while|for|do|switch|case|return)\b', WEIGHTS['common_keyword']),
        (r'\b(int|float|double|char|void|boolean|long|short|byte)\b', WEIGHTS['common_keyword']), # Java primitive types
         # Declaration / Structure
        (r'\b(public|private|protected)\s+(static\s+)?\w+\s+\w+\s*\(.*\)\s*(throws\s+[\w,\s]+)?\s*{', WEIGHTS['declaration'] * 1.5), # Method signature
        (r'public\s+static\s+void\s+main\s*\(\s*String(\[\s*\]|\s+\.\.\.)\s+\w+\s*\)', WEIGHTS['structure'] * 3), # THE main method
        (r'\bthis\b', WEIGHTS['common_practice']),
        (r'\.\s*equals\(', WEIGHTS['common_practice']), # String comparison idiom
        (r'\bnull\b', WEIGHTS['unique_keyword']), # Lowercase null
        (r';\s*$', WEIGHTS['structure']), # Semicolons
        (r'[{}]', WEIGHTS['structure']), # Braces
        # Comments
        (r'//.*', WEIGHTS['comment_style']),
        (r'/\*.*?\*/', WEIGHTS['comment_style']),
    ],
    'JavaScript': [
        # Unique Keywords / Syntax
        (r'\b(function\*?|var|let|const)\b', WEIGHTS['declaration']), # Declaration keywords
        (r'\b(async|await|yield)\b', WEIGHTS['unique_keyword']), # Also in Python, context matters
        (r'=>', WEIGHTS['syntax_pattern']), # Arrow functions
        (r'`.*?${.*?}.*?`', WEIGHTS['syntax_pattern']), # Template literals
        (r'\b(import|export)\s+(default\s+)?({.*?}|\*)\s+from\s+[\'"].*?[\'"]', WEIGHTS['syntax_pattern']), # ES6 modules
        (r'require\s*\(.*?\)', WEIGHTS['stdlib_indicator']), # CommonJS modules
        (r'\b(console)\.(log|warn|error|info|debug)\(', WEIGHTS['stdlib_indicator'] * 1.5),
        (r'\b(document|window|navigator|location|history|fetch|alert|prompt|confirm)\b', WEIGHTS['stdlib_indicator'] * 2), # Browser APIs
        (r'\b(getElementById|querySelector|addEventListener)\b', WEIGHTS['stdlib_indicator'] * 1.5), # DOM methods
        (r'===|!==', WEIGHTS['operator']), # Strict equality
        (r'\b(Promise|resolve|reject|then|catch)\b', WEIGHTS['unique_keyword']), # Async patterns
        (r'\b(JSON)\.(parse|stringify)\b', WEIGHTS['stdlib_indicator']),
        (r'\b(typeof|instanceof)\b', WEIGHTS['operator']),
        (r'\b(undefined|NaN)\b', WEIGHTS['unique_keyword']),
        # Common Keywords
        (r'\b(class|if|else|while|for|do|switch|case|try|catch|finally|return|new|in|delete|this|super)\b', WEIGHTS['common_keyword']),
        # Structure / Practice
        (r'\bprototype\b', WEIGHTS['common_practice']),
        (r';\s*$', WEIGHTS['structure']), # Semicolons (optional but common)
        (r'[{}]', WEIGHTS['structure']), # Braces
        # Comments
        (r'//.*', WEIGHTS['comment_style']),
        (r'/\*.*?\*/', WEIGHTS['comment_style']),
    ]
}

# --- Helper Functions ---

def preprocess_code(code_snippet):
    """Remove comments and potentially normalize whitespace."""
    logger.debug("Preprocessing code snippet")
    try:
        # Remove multi-line /* ... */ comments
        code = re.sub(r'/\*.*?\*/', '', code_snippet, flags=re.DOTALL)
        # Remove single-line // comments
        code = re.sub(r'//.*', '', code)
        # Remove single-line # comments (mainly for Python)
        code = re.sub(r'#.*', '', code)
        # Optional: Collapse multiple spaces/tabs? For now, keep original spacing.
        lines = [line.strip() for line in code.splitlines() if line.strip()]
        logger.debug(f"Code preprocessing complete. Processed {len(lines)} lines")
        return "\n".join(lines), lines # Return both processed string and list of lines
    except Exception as e:
        logger.error(f"Error during code preprocessing: {str(e)}")
        return code_snippet, code_snippet.splitlines()

def analyze_code(code_snippet):
    """Analyzes the code snippet and returns scores for each language."""
    logger.info("Starting code analysis")
    scores = {'Python': 0, 'C++': 0, 'Java': 0, 'JavaScript': 0}
    
    try:
        processed_code, lines = preprocess_code(code_snippet)

        if not processed_code:
            logger.warning("No code content after preprocessing")
            return scores # No code left after preprocessing

        total_lines = len(lines)

        # --- Feature Matching ---
        for lang, patterns in FEATURES.items():
            lang_score = 0
            for pattern, weight in patterns:
                try:
                    # Find all occurrences, not just the first one
                    matches = re.findall(pattern, processed_code, flags=re.MULTILINE)
                    if matches:
                        # Score based on weight and frequency (log scale to avoid runaway scores)
                        # Add 1 to count to handle log(0) and give base score
                        pattern_score = weight * (1 + math.log1p(len(matches)))
                        lang_score += pattern_score
                        if len(matches) > 5:  # Only log significant matches
                            logger.debug(f"Found {len(matches)} matches for {lang} pattern with weight {weight}")
                except re.error as e:
                    logger.warning(f"Regex error for {lang} pattern: {str(e)}")
                    pass # Ignore regex errors for resilience
            
            scores[lang] += lang_score
            logger.debug(f"{lang} initial score: {lang_score}")

        # --- Structural Analysis ---

        # 1. Semicolon usage
        semicolon_lines = sum(1 for line in lines if line.endswith(';'))
        if total_lines > 0:
            semicolon_ratio = semicolon_lines / total_lines
            logger.debug(f"Semicolon ratio: {semicolon_ratio:.2f}")
            if semicolon_ratio > 0.7:  # High usage -> Java, C++ favoured
                scores['Java'] += WEIGHTS['structure'] * 2
                scores['C++'] += WEIGHTS['structure'] * 2
                scores['JavaScript'] += WEIGHTS['structure'] * 0.5 # Less strict in JS
                scores['Python'] -= WEIGHTS['structure'] # Penalize Python
            elif semicolon_ratio < 0.1 and total_lines > 2: # Low usage -> Python favoured
                scores['Python'] += WEIGHTS['structure'] * 2
                scores['JavaScript'] += WEIGHTS['structure'] * 0.5 # JS can also have few
                scores['Java'] -= WEIGHTS['structure']
                scores['C++'] -= WEIGHTS['structure']

        # 2. Indentation vs. Braces
        brace_count = processed_code.count('{') + processed_code.count('}')
        colon_at_eol_count = sum(1 for line in lines if line.endswith(':'))
        indentation_changes = 0
        last_indent = 0
        for line in lines:
            indent = len(line) - len(line.lstrip(' '))
            if indent != last_indent:
                indentation_changes +=1
            last_indent = indent

        if brace_count > colon_at_eol_count + 2 and brace_count > total_lines * 0.1: # More braces than colons suggests C-style
            scores['C++'] += WEIGHTS['structure']
            scores['Java'] += WEIGHTS['structure']
            scores['JavaScript'] += WEIGHTS['structure']
            scores['Python'] -= WEIGHTS['structure'] * 0.5 # Less likely Python
        elif colon_at_eol_count > brace_count + 1 and indentation_changes > total_lines * 0.2: # More colons and indentation changes suggest Python
            scores['Python'] += WEIGHTS['structure'] * 1.5
            scores['C++'] -= WEIGHTS['structure'] * 0.5
            scores['Java'] -= WEIGHTS['structure'] * 0.5
            scores['JavaScript'] -= WEIGHTS['structure'] * 0.5

        # Adjust for async/await ambiguity (common in both Py & JS)
        # If both have high scores and async/await was found, look for other clues
        if scores['Python'] > 0 and scores['JavaScript'] > 0 and \
           (re.search(r'\b(async|await)\b', processed_code)):
            if scores['Python'] > scores['JavaScript']:
                if re.search(r'\b(def|self|elif|None|True|False)\b', processed_code):
                    scores['Python'] += WEIGHTS['unique_keyword'] # Boost Python if other Pythonic things exist
                else:
                     scores['JavaScript'] += WEIGHTS['common_keyword'] # Nudge JS otherwise
            elif scores['JavaScript'] > scores['Python']:
                 if re.search(r'=>|\b(let|const|var|function|console|document)\b', processed_code):
                     scores['JavaScript'] += WEIGHTS['unique_keyword'] # Boost JS
                 else:
                     scores['Python'] += WEIGHTS['common_keyword'] # Nudge Python

        logger.info(f"Analysis complete. Final scores: {scores}")
        return scores
        
    except Exception as e:
        logger.error(f"Error during code analysis: {str(e)}", exc_info=True)
        return scores

def detect_language(code_snippet):
    """
    Detects the language of a code snippet based on feature analysis.

    Args:
        code_snippet (str): The code snippet to analyze.

    Returns:
        str: The name of the most likely language ('Python', 'C++', 'Java', 'JavaScript')
             or 'Undetermined' if insufficient evidence.
    """
    try:
        if not code_snippet or len(code_snippet.strip()) < 10:
            logger.warning("Code snippet too short for reliable detection")
            return "Undetermined"
            
        logger.info("Starting language detection")
        scores = analyze_code(code_snippet)
        
        # Find the language with the highest score
        max_score = max(scores.values())
        max_lang = max(scores, key=scores.get)
        
        # Require a minimum score to make a determination
        # This helps avoid false positives on very short or ambiguous snippets
        if max_score < 10:
            logger.warning(f"Insufficient evidence for language detection. Max score: {max_score}")
            return "Undetermined"
            
        # Check if the highest score is significantly higher than the second highest
        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) > 1 and sorted_scores[0] < sorted_scores[1] * 1.2:
            logger.warning(f"Language detection ambiguous. Top scores too close: {scores}")
            # If scores are close, we might want to return "Ambiguous" or the top 2 candidates
            # For now, we'll still return the top language but with a warning
            
        logger.info(f"Detected language: {max_lang} with score {max_score}")
        return max_lang
    except Exception as e:
        logger.error(f"Error during language detection: {str(e)}", exc_info=True)
        return "Undetermined"
