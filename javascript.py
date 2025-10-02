import re
import json
import math
import statistics
import ast
import tokenize
import io
import json
import re
import math
from collections import defaultdict
import sys
from pymongo import MongoClient
from bson.objectid import ObjectId



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





# --- Configuration ---
# Weights for different analysis factors (adjust as needed)
WEIGHTS = {
    "comments": 1.5,
    "formatting": 1.0,
    "naming": 1.2,
    "complexity": 1.0,
    "constructs": 1.0,
    "structure": 0.8,
}

# Thresholds (adjust based on empirical testing)
COMMENT_RATIO_AI_THRESHOLD = 0.15  # More than 15% comment lines might be AI
COMMENT_RATIO_HUMAN_THRESHOLD = 0.02 # Less than 2% comment lines might be human
AVG_NAME_LENGTH_AI_THRESHOLD = 8    # Average var/func name length suggesting AI
AVG_NAME_LENGTH_HUMAN_THRESHOLD = 4 # Average var/func name length suggesting human
INDENT_STDDEV_AI_THRESHOLD = 0.5  # Very low std dev in indentation suggests AI
COMPLEXITY_NESTING_THRESHOLD = 4 # Deep nesting might be less common in clean AI code
SHORT_FUNC_THRESHOLD = 3        # Lines defining a "very short" function

# --- Helper Functions ---

def normalize_code(code):
    """Removes comments and standardizes whitespace for certain analyses."""
    # Remove block comments
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    # Remove line comments
    code = re.sub(r'//.*', '', code)
    # Normalize whitespace (helps with some checks, but use original for others)
    # code = re.sub(r'\s+', ' ', code).strip()
    return code

def get_code_lines(code):
    """Splits code into lines, ignoring empty lines."""
    return [line for line in code.splitlines() if line.strip()]

def get_comments(code):
    """Extracts both line and block comments."""
    line_comments = re.findall(r'//(.*)', code)
    block_comments = re.findall(r'/\*(.*?)\*/', code, re.DOTALL)
    # Basic cleaning of comment content
    line_comments = [c.strip() for c in line_comments]
    block_comments = [c.strip().replace('\n', ' ').replace('\r', '') for c in block_comments]
    return line_comments, block_comments

# --- Analysis Functions ---

def analyze_comments(code, code_lines):
    """Analyzes comment style, frequency, and content."""
    score = 0
    justification = []
    patterns = []
    
    line_comments, block_comments = get_comments(code)
    all_comments = line_comments + block_comments
    num_comment_lines = len(line_comments) + code.count('/*') # Approximate block comments lines
    total_lines = len(code.splitlines())
    
    if not total_lines:
        return 0, justification, patterns

    comment_ratio = num_comment_lines / total_lines if total_lines > 0 else 0

    # Frequency
    if not all_comments:
        score -= 5
        justification.append("Lack of comments often indicates human authorship under time pressure or simple code.")
        patterns.append("COMMENT_ABSENCE")
    elif comment_ratio > COMMENT_RATIO_AI_THRESHOLD:
        score += 10
        justification.append(f"High comment-to-code ratio ({comment_ratio:.1%}) can be typical of AI explaining standard code.")
        patterns.append("HIGH_COMMENT_RATIO")
    elif comment_ratio < COMMENT_RATIO_HUMAN_THRESHOLD:
         score -= 3
         justification.append(f"Very low comment-to-code ratio ({comment_ratio:.1%}) suggests minimal explanation, possibly human.")
         patterns.append("LOW_COMMENT_RATIO")

    # Style & Content
    perfect_grammar_count = 0
    human_markers = 0
    jsdoc_count = 0
    for comment in all_comments:
        comment_lower = comment.lower()
        # AI-like: Perfect sentences, descriptive JSDoc
        if comment.endswith('.') or comment.endswith('?') or comment.endswith('!'):
             if len(comment.split()) > 4: # Avoid short notes
                 perfect_grammar_count += 1
        if re.match(r'@(param|returns?|type|typedef|class|const|memberof|description|example)', comment):
             jsdoc_count +=1
        # Human-like: Informal markers, questions, placeholders
        if any(marker in comment_lower for marker in ['todo', 'fixme', 'hack', 'xxx', 'later', 'temp', 'debug']):
            human_markers += 1
            patterns.append("HUMAN_COMMENT_MARKER")
        if '?' in comment and not comment.endswith('?'): # Question mid-comment
             human_markers += 1
        if re.search(r'[a-zA-Z]\s+[a-zA-Z]', comment) and not comment.endswith('.'): # Missing punctuation
             human_markers += 0.5 # Less strong indicator

    if jsdoc_count > 0 and jsdoc_count >= len(block_comments) * 0.5: # Significant JSDoc usage
        score += 6
        justification.append("Extensive or perfectly formatted JSDoc comments suggest programmatic generation.")
        patterns.append("JSDOC_USAGE")

    if perfect_grammar_count > len(all_comments) * 0.6 and len(all_comments) > 2:
        score += 5
        justification.append("Comments predominantly use formal sentence structure and punctuation, potentially AI-like.")
        patterns.append("FORMAL_COMMENTS")

    if human_markers > 0:
        score -= human_markers * 4 # Strong indicator
        justification.append(f"Detected {human_markers} human-like comment markers (TODO, FIXME, informal notes, etc.).")
        

    return score, justification, patterns

def analyze_formatting(code, code_lines):
    """Analyzes indentation, spacing, and block structure consistency."""
    score = 0
    justification = []
    patterns = []

    if not code_lines:
        return 0, justification, patterns

    indentations = []
    spacing_inconsistencies = 0
    operator_spacing_consistent = True
    trailing_whitespace = 0
    bracket_styles = {'opening': [], 'closing': []} # K&R vs Allman etc. - basic check

    # Common operators/delimiters to check spacing around
    spacing_chars = ['=', '+', '-', '*', '/', '%', '==', '===', '!=', '!==', '>', '<', '>=', '<=', '&&', '||', '?', ':']
    
    last_indent = 0
    indent_chars = None # Track if tabs or spaces used

    for i, line in enumerate(code_lines):
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith(("//", "/*", "*")): # Ignore comments/empty for indent
            continue

        leading_whitespace = line[:len(line) - len(line.lstrip())]
        indent_level = len(leading_whitespace)
        
        # Track indent character type
        if indent_level > 0 and indent_chars is None:
            indent_chars = '\t' if leading_whitespace.startswith('\t') else ' '
        elif indent_level > 0:
            if (indent_chars == '\t' and ' ' in leading_whitespace) or \
               (indent_chars == ' ' and '\t' in leading_whitespace):
                spacing_inconsistencies += 5 # Major inconsistency: mixed tabs/spaces
                patterns.append("MIXED_INDENT_CHARS")

        indentations.append(indent_level)
        
        # Check spacing around operators (basic check)
        for char in spacing_chars:
            # Find operator not inside strings
            for match in re.finditer(re.escape(char), stripped_line):
                 start = match.start()
                 # Very basic check to avoid triggers inside strings/regex literals
                 if stripped_line[:start].count("'") % 2 == 0 and \
                    stripped_line[:start].count('"') % 2 == 0 and \
                    stripped_line[:start].count("`") % 2 == 0:
                     
                    left_char = stripped_line[start-1] if start > 0 else ' '
                    right_char = stripped_line[start+len(char)] if start+len(char) < len(stripped_line) else ' '
                    
                    is_left_spaced = left_char.isspace()
                    is_right_spaced = right_char.isspace()
                    
                    # Simple check: expecting space on both sides (most common AI style)
                    # This is naive, doesn't handle unary operators well, etc.
                    if not (is_left_spaced and is_right_spaced) and \
                       not (char in ['++', '--'] and (not is_left_spaced or not is_right_spaced)): # Allow x++/--x
                         spacing_inconsistencies += 1
                         patterns.append("INCONSISTENT_OPERATOR_SPACING")
                         operator_spacing_consistent = False # Flag it


        # Check for trailing whitespace
        if line.rstrip() != line:
            trailing_whitespace += 1
            patterns.append("TRAILING_WHITESPACE")

        # Rudimentary check for bracket style consistency (opening brace placement)
        if '{' in stripped_line:
            if stripped_line.endswith('{'):
                 bracket_styles['opening'].append('same_line') # K&R style
            elif stripped_line.strip() == '{':
                 bracket_styles['opening'].append('new_line') # Allman style
        # Closing brace usually on its own line, harder to check simply
        
    # Analyze Indentation Consistency
    if len(indentations) > 1:
        try:
            indent_stddev = statistics.stdev([i for i in indentations if i > 0]) # Std dev of non-zero indents
            # Low std dev suggests high consistency (AI-like)
            # This is very approximate, step changes are normal
            if indent_stddev < INDENT_STDDEV_AI_THRESHOLD:
                score += 7
                justification.append(f"Indentation is highly consistent (stddev={indent_stddev:.2f}), suggesting automated formatting.")
                patterns.append("CONSISTENT_INDENTATION")
            elif indent_stddev > INDENT_STDDEV_AI_THRESHOLD * 3: # High variation might be human
                 score -= 4
                 justification.append(f"Indentation shows significant variation (stddev={indent_stddev:.2f}), potentially human-like inconsistency.")
                 patterns.append("INCONSISTENT_INDENTATION")

        except statistics.StatisticsError:
            # Handle case with too few data points (or all same indent)
             if len(set(indentations)) == 1 and len(indentations) > 2:
                 score += 5 # All same indent is consistent
                 justification.append("Indentation level is uniform across relevant lines.")
                 patterns.append("CONSISTENT_INDENTATION")

    # Analyze Spacing
    if spacing_inconsistencies > 3: # Allow a few minor slips
        score -= 5
        justification.append(f"Detected {spacing_inconsistencies} potential spacing inconsistencies around operators or mixed indent chars.")
    elif operator_spacing_consistent and len(code_lines) > 5: # Needs enough lines to judge
        score += 3
        justification.append("Spacing around operators appears consistent.")
        patterns.append("CONSISTENT_SPACING")
        
    if trailing_whitespace > 0:
        score -= 3
        justification.append(f"Detected {trailing_whitespace} lines with trailing whitespace, often removed by linters/AI.")

    # Analyze Bracket Style
    if len(set(bracket_styles['opening'])) > 1:
        score -= 4
        justification.append("Mixed opening brace styles detected (e.g., some on same line, some on new line).")
        patterns.append("MIXED_BRACKET_STYLE")
    elif len(bracket_styles['opening']) > 2: # Need a few examples to be sure
        score += 2
        justification.append("Consistent opening brace style observed.")


    return score, justification, patterns

def analyze_naming(code):
    """Analyzes variable and function naming conventions."""
    score = 0
    justification = []
    patterns = []

    # Regex to find potential variable/function names (simplified)
    # Looks for declarations (var, let, const, function) and assignments/properties
    # This is an approximation and won't catch all cases perfectly.
    names = re.findall(r'(?:var|let|const|function)\s+([a-zA-Z_]\w*)', code)
    names += re.findall(r'([a-zA-Z_]\w*)\s*=', code) # Assignments
    names += re.findall(r'\.\s*([a-zA-Z_]\w*)', code) # Property access
    names += re.findall(r'function\s*([a-zA-Z_]\w*)\s*\(', code) # Function declarations again
    
    # Filter out common JS keywords and very short names likely to be noise
    keywords = {'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default', 
                'break', 'continue', 'return', 'new', 'this', 'super', 'class', 
                'extends', 'import', 'export', 'try', 'catch', 'finally', 'throw', 
                'typeof', 'instanceof', 'delete', 'void', 'in', 'of', 'yield', 
                'async', 'await', 'null', 'undefined', 'true', 'false', 'get', 'set',
                'static', 'prototype', 'constructor'} 
    
    # Heuristic filtering: length > 1, not all caps (constants ok), not keywords
    potential_names = [n for n in set(names) if len(n) > 1 and not n.isupper() and n not in keywords]
    
    if not potential_names:
         return 0, justification, patterns

    total_name_length = sum(len(n) for n in potential_names)
    avg_name_length = total_name_length / len(potential_names)
    
    camel_case_count = 0
    pascal_case_count = 0
    snake_case_count = 0
    other_case_count = 0
    single_letter_vars = 0 # Outside typical loop vars i, j, k
    
    for name in potential_names:
        if re.match(r'^[a-z]+(?:[A-Z][a-z\d]*)*$', name):
            camel_case_count += 1
        elif re.match(r'^[A-Z][a-z\d]+(?:[A-Z][a-z\d]*)*$', name):
             pascal_case_count +=1 # Usually for classes/constructors
        elif re.match(r'^[a-z]+(?:_[a-z\d]+)*$', name):
            snake_case_count += 1
        else:
             other_case_count += 1
             
        # Penalize single letters unless clearly loop/callback vars (difficult heuristic)
        # Simple check: if name is single letter and not in a common context pattern
        if len(name) == 1 and name not in 'ijkemnxyztp': 
            # Crude check for context: not immediately following 'for(' or inside '=>' or 'function('
            # This is very weak, proper AST needed for accuracy
            if not re.search(rf'(?:for\s*\(.*|function\s*\(.*|\(\s*)\b{name}\b', code):
                 single_letter_vars += 1
                 patterns.append("CRYPTIC_SINGLE_LETTER_VAR")


    # Analyze average length
    if avg_name_length > AVG_NAME_LENGTH_AI_THRESHOLD:
        score += 7
        justification.append(f"Average variable/function name length is high ({avg_name_length:.1f}), suggesting descriptive AI style.")
        patterns.append("DESCRIPTIVE_NAMING")
    elif avg_name_length < AVG_NAME_LENGTH_HUMAN_THRESHOLD:
         score -= 5
         justification.append(f"Average variable/function name length is low ({avg_name_length:.1f}), often seen in human code (abbreviations, short names).")
         patterns.append("SHORT_NAMING")

    # Analyze casing consistency (dominant style should be camelCase for JS vars/funcs)
    total_names = len(potential_names)
    if camel_case_count / total_names > 0.8:
        score += 4
        justification.append("Naming predominantly uses consistent camelCase, common in AI/linted code.")
        patterns.append("CONSISTENT_CAMELCASE")
    elif snake_case_count > 0 or pascal_case_count > total_names * 0.1: # Allow some PascalCase for classes
        score -= 3
        justification.append("Mixed naming conventions (camelCase, PascalCase, snake_case) detected, potentially human.")
        patterns.append("MIXED_NAMING_CASE")
        
    if single_letter_vars > 0:
         score -= single_letter_vars * 3
         justification.append(f"Found {single_letter_vars} potentially cryptic single-letter variable names outside typical contexts.")

    return score, justification, patterns


def analyze_complexity_efficiency(code, code_lines):
    """Analyzes code structure, nesting, and potential inefficiencies."""
    score = 0
    justification = []
    patterns = []
    
    nesting_depth = 0
    max_nesting = 0
    redundant_loops = 0 # Heuristic: loops that could likely be combined
    modern_features = 0 # Use of map, filter, reduce, async/await, etc.
    
    # Basic nesting check (count indentation increases)
    current_indent = 0
    indent_stack = [0]
    for line in code_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
            
        leading_whitespace = line[:len(line) - len(line.lstrip())]
        indent_level = len(leading_whitespace) # Simple length based, assumes consistent indent char

        # Very basic approximation of block start/end
        if indent_level > indent_stack[-1]:
            indent_stack.append(indent_level)
            nesting_depth = len(indent_stack) - 1
            max_nesting = max(max_nesting, nesting_depth)
        elif indent_level < indent_stack[-1]:
            while indent_stack and indent_level < indent_stack[-1]:
                indent_stack.pop()
            if not indent_stack or indent_level != indent_stack[-1]:
                 # Indentation doesn't match stack - potential issue or mixed style
                 # For complexity scoring, just reset depth based on current line
                 nesting_depth = len(indent_stack) # Approximation
            else:
                 nesting_depth = len(indent_stack) -1


    # Check for modern JS features often used by AI for efficiency/conciseness
    modern_patterns = [r'\.\s*map\s*\(', r'\.\s*filter\s*\(', r'\.\s*reduce\s*\(', 
                       r'\.\s*forEach\s*\(', r'async\s+function', r'\=\>\s*\{?', 
                       r'Promise\.(all|race|resolve|reject)', r'Object\.(keys|values|entries)',
                       r'\{\s*\.\.\.\s*[a-zA-Z_]\w*\s*\}'] # Spread syntax
    for pattern in modern_patterns:
        if re.search(pattern, code):
            modern_features += 1
            
    # Simple check for potentially redundant loops (e.g., multiple loops over same array structure)
    loop_patterns = re.findall(r'(for\s*\(.*\)|while\s*\(.*\)|do\s*\{)', code)
    if len(loop_patterns) > 2:
         # Very weak heuristic: If multiple loops exist close together, maybe redundant
         # Need semantic analysis for accuracy
         if len(code_lines) / len(loop_patterns) < 15: # Loops are 'close'
             redundant_loops = 1 # Flag possibility
             patterns.append("POTENTIAL_REDUNDANT_LOOPS")


    # Scoring based on observations
    if max_nesting > COMPLEXITY_NESTING_THRESHOLD:
        score -= 5
        justification.append(f"High nesting depth ({max_nesting}) detected, can indicate less structured human logic.")
        patterns.append("DEEP_NESTING")
    elif max_nesting <= 2 and len(code_lines) > 15: # Shallow nesting in non-trivial code
         score += 3
         justification.append("Code structure appears relatively flat (max nesting <= 2), possibly AI/refactored.")
         patterns.append("SHALLOW_NESTING")

    if modern_features >= 3: # Uses several modern features
        score += 6
        justification.append(f"Detected use of {modern_features} modern JavaScript features (map, filter, async, etc.), often employed by AI for conciseness/efficiency.")
        patterns.append("MODERN_JS_FEATURES")
        
    if redundant_loops > 0:
         score -= 4
         justification.append("Potential redundant loops detected; human code might iterate multiple times where one pass could suffice.")
         
    # Efficiency check (very basic): Look for loops recalculating values unnecessarily
    # Example: Calculating array length inside loop condition (classic anti-pattern)
    if re.search(r'for\s*\(.*\;\s*i\s*<\s*[a-zA-Z_]\w*\.length\s*\;', code):
         score -= 3
         justification.append("Detected potential inefficiency: Array length calculated repeatedly inside loop condition.")
         patterns.append("INEFFICIENT_LOOP_CONDITION")


    return score, justification, patterns


def analyze_constructs_redundancy(code):
    """Analyzes unusual code patterns, redundancy, excessive abstraction."""
    score = 0
    justification = []
    patterns = []
    
    # Redundant parentheses: ((expression)) or if((condition)) etc.
    redundant_parens = len(re.findall(r'\(\s*\([^()]*?\)\s*\)', code))
    if redundant_parens > 1:
        score += redundant_parens * 2
        justification.append(f"Found {redundant_parens} instances of potentially redundant parentheses.")
        patterns.append("REDUNDANT_PARENTHESES")
        
    # Unnecessary blocks: if (cond) { single_statement; }
    # Hard to detect accurately without parsing, regex is fragile.
    # Approximation: look for single non-comment line within braces
    unnecessary_blocks = 0
    for match in re.finditer(r'\{\s*([^//}]+?)\s*;?\s*\}', code):
        content = match.group(1).strip()
        if '\n' not in content and content and not content.startswith('/*'):
            # Check if it's immediately after if/while/for without else/catch etc.
            preceding_text = code[:match.start()].rstrip()
            if re.search(r'(if|for|while)\s*\(.*\)\s*$', preceding_text):
                 unnecessary_blocks += 1
                 patterns.append("UNNECESSARY_BLOCK")
    if unnecessary_blocks > 1:
        score += unnecessary_blocks * 2
        justification.append(f"Detected {unnecessary_blocks} potentially unnecessary code blocks around single statements.")
        

    # Excessive abstraction: Very short functions called only once (heuristic)
    functions = re.findall(r'(function\s+[a-zA-Z_]\w*\s*\(.*?\)\s*\{([\s\S]*?)\})', code)
    functions += re.findall(r'([a-zA-Z_]\w*\s*=\s*(?:async)?\s*\(.*?\)\s*=>\s*\{([\s\S]*?)\})', code) # Arrow funcs
    
    short_single_use_funcs = 0
    for func_match in functions:
        func_name_match = re.search(r'(?:function\s+|const|let|var)\s*([a-zA-Z_]\w*)', func_match[0])
        if not func_name_match: continue
        
        func_name = func_name_match.group(1)
        func_body = func_match[1] # Content within braces
        
        # Count non-empty, non-comment lines in body
        body_lines = [line for line in func_body.splitlines() if line.strip() and not line.strip().startswith(("//", "/*", "*"))]
        num_body_lines = len(body_lines)
        
        if 0 < num_body_lines <= SHORT_FUNC_THRESHOLD:
             # Check how many times the function name appears *outside* its definition
             # This is approximate - could miss obj.method calls etc.
             usage_count = len(re.findall(r'\b' + re.escape(func_name) + r'\b', code))
             definition_count = code.count(func_match[0]) # Occurrences of the definition itself
             
             # If used only once (or maybe twice if definition counted) outside its definition
             if usage_count - definition_count <= 1:
                  short_single_use_funcs += 1
                  patterns.append("SHORT_SINGLE_USE_FUNCTION")

    if short_single_use_funcs > 1:
         score += short_single_use_funcs * 3
         justification.append(f"Found {short_single_use_funcs} very short functions potentially used only once, suggesting excessive abstraction.")

    # Redundant return: return undefined; or return; at end of function where it's implicit
    # Hard to check accurately without scope analysis. Simple check for `return;` at end of block.
    if re.search(r'return\s*;?\s*\}', code):
         score += 2
         justification.append("Detected 'return;' at the end of a block, which might be redundant.")
         patterns.append("REDUNDANT_RETURN")

    return score, justification, patterns


def analyze_structure_completion(code):
    """Analyzes overall structure, presence of placeholders, commented-out code."""
    score = 0
    justification = []
    patterns = []

    # Look for common human placeholders/markers in code (not just comments)
    if re.search(r'//\s*(TODO|FIXME|XXX|HACK|LATER)', code, re.IGNORECASE):
        score -= 8 # Strong human indicator
        justification.append("Presence of TODO/FIXME markers suggests human iterative development.")
        patterns.append("CODE_PLACEHOLDERS")
        
    # Look for large commented-out code blocks (human experimentation/legacy)
    # Find block comments /* ... */
    block_comments = re.findall(r'/\*(.*?)\*/', code, re.DOTALL)
    for comment in block_comments:
         comment_lines = comment.strip().splitlines()
         # Heuristic: If a block comment has multiple lines that look like code (e.g., contain ';', '{', '}')
         code_like_lines = 0
         for line in comment_lines:
             if any(c in line for c in ';{}()=') and not line.strip().startswith('*'): # Avoid doc comment lines
                 code_like_lines += 1
         if code_like_lines > 3: # If more than 3 lines look like code within a block comment
             score -= 6
             justification.append("Detected large commented-out code block, likely human experimentation or legacy code.")
             patterns.append("COMMENTED_OUT_CODE")
             break # Only count once

    # Assess if the snippet looks like a direct answer vs. part of a larger flow
    # Heuristic: Does it define functions/classes but not call them? Is it self-contained?
    # This is subjective and hard to automate reliably.
    
    # Simple check: Top-level function calls or immediate execution?
    # (Doesn't apply well to class definitions or library-like code)
    normalized = normalize_code(code) # Code without comments
    lines = get_code_lines(normalized)
    has_top_level_calls = False
    if lines:
        last_line = lines[-1].strip()
        # Check if last line looks like a function call `func()` or assignment `x = func()`
        # Or IIFE (Immediately Invoked Function Expression)
        if re.search(r'\)\s*;?$', last_line) or re.search(r'\)\(\s*;?$', code):
             has_top_level_calls = True

    # If code defines functions/classes but has no apparent execution/export, it might be an AI 'example'
    has_definitions = re.search(r'function\s+[a-zA-Z_]\w*|class\s+[A-Z]\w*', code)
    if has_definitions and not has_top_level_calls and len(lines) > 5:
         # Check for exports, which would be normal for modules
         has_exports = re.search(r'export\s+(default|const|let|var|function|class)', code)
         if not has_exports:
             score += 3
             justification.append("Code defines structures (functions/classes) but lacks clear top-level execution or exports, potentially resembling an AI-generated example snippet.")
             patterns.append("ISOLATED_DEFINITIONS")

    return score, justification, patterns

# --- Main Detection Function ---

def detect_ai_js(code_snippet):
    """
    Analyzes a JavaScript code snippet to determine the likelihood of AI generation.

    Args:
        code_snippet (str): The JavaScript code snippet to analyze.

    Returns:
        dict: A dictionary containing the analysis results in JSON format.
              {
                  "suspicious_percentage": float (0-100),
                  "detailed_justification": [str],
                  "pattern_analysis": [str]
              }
    """
    if not isinstance(code_snippet, str) or not code_snippet.strip():
        return {
            "suspicious_percentage": 0.0,
            "detailed_justification": ["Input code snippet is empty or invalid."],
            "pattern_analysis": ["EMPTY_INPUT"]
        }

    total_score = 0
    all_justifications = []
    all_patterns = []
    
    lines = get_code_lines(code_snippet)

    # Run all analysis functions
    analysis_funcs = {
        "comments": analyze_comments,
        "formatting": analyze_formatting,
        "naming": analyze_naming,
        "complexity": analyze_complexity_efficiency,
        "constructs": analyze_constructs_redundancy,
        "structure": analyze_structure_completion,
    }
    
    # Function arguments map
    func_args = {
         analyze_comments: (code_snippet, lines),
         analyze_formatting: (code_snippet, lines),
         analyze_naming: (code_snippet,),
         analyze_complexity_efficiency: (code_snippet, lines),
         analyze_constructs_redundancy: (code_snippet,),
         analyze_structure_completion: (code_snippet,)
    }

    for name, func in analysis_funcs.items():
         args = func_args[func]
         try:
             score, justification, patterns = func(*args)
             weighted_score = score * WEIGHTS.get(name, 1.0)
             total_score += weighted_score
             if justification:
                 all_justifications.extend([f"[{name.upper()}]: {j}" for j in justification])
             if patterns:
                 all_patterns.extend(patterns)
         except Exception as e:
              all_justifications.append(f"[ERROR in {name.upper()}]: Failed to analyze - {e}")
              all_patterns.append(f"ANALYSIS_ERROR_{name.upper()}")

    # Normalize score to 0-100 percentage
    # This scaling is arbitrary and needs tuning based on expected score ranges.
    # Let's use a sigmoid-like approach to squash scores into a probability-like range.
    # Adjust scale and midpoint based on observed score ranges from testing.
    scale = 0.05 # Controls how quickly the percentage changes with score
    midpoint = 10 # Score considered neutral (adjust based on testing)
    
    suspicious_percentage = 100 / (1 + math.exp(-scale * (total_score - midpoint)))
    
    # Clamp the percentage between 0 and 100
    suspicious_percentage = max(0.0, min(100.0, suspicious_percentage))

    # Add overall assessment to justification
    if suspicious_percentage > 75:
        all_justifications.insert(0, f"Overall Assessment: High likelihood of AI generation based on multiple factors.")
    elif suspicious_percentage > 50:
         all_justifications.insert(0, f"Overall Assessment: Moderate suspicion of AI generation. Exhibits several AI-like traits.")
    elif suspicious_percentage > 25:
         all_justifications.insert(0, f"Overall Assessment: Low suspicion of AI generation. Some AI-like traits present, but mixed signals.")
    else:
         all_justifications.insert(0, f"Overall Assessment: Likely human-written. Exhibits primarily human-like coding patterns.")
         
    # Add total score for debugging/transparency
    all_justifications.append(f"[DEBUG] Raw Score: {total_score:.2f}")


    # Remove duplicate patterns
    unique_patterns = sorted(list(set(all_patterns)))

    # Prepare JSON output
    result = {
        "suspicious_percentage": round(suspicious_percentage, 2),
        "detailed_justification": all_justifications,
        "pattern_analysis": unique_patterns
    }

    return result



if __name__ == "__main__":
    
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing object_id argument"}))
        sys.exit(1)

    document_id = sys.argv[1]  # Get object_id from command line argument

    doc_content = fetch_document_by_id(document_id)
    if doc_content:
        analysis_result = detect_ai_js(doc_content['code'])

        if analysis_result:
           
            # json_output = json.dumps(analysis_result, indent=4, default=str)
            print(analysis_result)
        else:
            print("Analysis could not be performed on the document.")



