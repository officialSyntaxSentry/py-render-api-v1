import re
import json
import math
import statistics
import sys
from pymongo import MongoClient
from bson.objectid import ObjectId

# --- Configuration Constants ---







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







# Weights for different factors (adjust based on observation/tuning)
WEIGHTS = {
    "comment_density": 0.15,
    "obvious_comments": 0.10,
    "todo_fixme_presence": 0.10,
    "comment_style_consistency": 0.05,
    "indentation_consistency": 0.10,
    "operator_spacing_consistency": 0.10,
    "line_length_variance": 0.05,
    "generic_variable_names": 0.15,
    "code_complexity_proxy": 0.10,
    "error_handling_presence": 0.10,
}

# Thresholds (these are heuristics and might need tuning)
COMMENT_DENSITY_LOW_THRESHOLD = 0.02  # Below this is suspicious (AI might forget comments)
COMMENT_DENSITY_HIGH_THRESHOLD = 0.30 # Above this is slightly suspicious (AI might over-comment)
LINE_LENGTH_MAX_COMMON = 120
LINE_LENGTH_MIN_VARIANCE = 10       # Low variance might indicate robotic consistency
GENERIC_NAME_RATIO_THRESHOLD = 0.25 # More than 25% generic names is suspicious
COMPLEXITY_KEYWORDS_DENSITY_HIGH = 0.1 # High density might indicate AI verbosity/simplicity
OPERATOR_SPACING_INCONSISTENCY_THRESHOLD = 0.2 # More than 20% inconsistent lines
INDENTATION_MIXED_THRESHOLD = 0.1 # More than 10% lines with mixed indentation evidence

# Patterns and Lists
COMMENT_PATTERN = re.compile(r'//.*|/\*.*?\*/', re.DOTALL)
SINGLE_LINE_COMMENT_PATTERN = re.compile(r'//.*')
BLOCK_COMMENT_PATTERN = re.compile(r'/\*.*?\*/', re.DOTALL)
TODO_FIXME_PATTERN = re.compile(r'\b(TODO|FIXME|XXX|HACK)\b', re.IGNORECASE)
# Basic check for obvious comments - expand as needed
OBVIOUS_COMMENT_PATTERNS = [
    re.compile(r'//\s*increment\s+\w+', re.IGNORECASE),
    re.compile(r'//\s*decrement\s+\w+', re.IGNORECASE),
    re.compile(r'//\s*loop\s+', re.IGNORECASE),
    re.compile(r'//\s*variable\s+', re.IGNORECASE),
    re.compile(r'//\s*return\s+\w+', re.IGNORECASE),
    re.compile(r'//\s*function\s+to\s+', re.IGNORECASE),
    re.compile(r'//\s*check\s+if\s+', re.IGNORECASE),
    re.compile(r'//\s*initialize\s+', re.IGNORECASE),
    re.compile(r'#include\s*<.*?>\s*//\s*for\s+', re.IGNORECASE), # Comments explaining standard includes
]
# Common C++ operators for spacing check
OPERATORS = ['=', '+', '-', '*', '/', '%', '==', '!=', '<', '>', '<=', '>=', '&&', '||', '+=', '-=', '*=', '/=', '%=', '<<', '>>', '&', '|', '^', '->', '::']
OPERATOR_SPACING_PATTERN = re.compile(r'\s*(' + '|'.join(re.escape(op) for op in OPERATORS) + r')\s*')
# Basic C++ keywords hinting at complexity
COMPLEXITY_KEYWORDS = {'if', 'else', 'while', 'for', 'switch', 'case', 'goto', 'try', 'catch'}
# Common generic variable names (add more as needed)
GENERIC_NAMES = {'i', 'j', 'k', 'n', 'm', 'x', 'y', 'z', 'tmp', 'temp', 'val', 'value', 'data', 'result', 'res', 'count', 'cnt', 'buffer', 'str', 'ptr'}
VARIABLE_DECL_PATTERN = re.compile(r'\b(int|float|double|char|string|auto|bool|long|short|unsigned|signed|const\s+\w+|\w+::\w+)\s+([a-zA-Z_]\w*)\s*[=({;,]')
ERROR_HANDLING_KEYWORDS = {'try', 'catch', 'throw', 'assert', 'static_assert', 'noexcept'}


# --- Helper Functions ---

def preprocess_code(code):
    """Removes block comments and handles basic preprocessing."""
    # Replace block comments with spaces to preserve line numbers somewhat
    def replacer(match):
        return '\n' * match.group(0).count('\n')
    code = BLOCK_COMMENT_PATTERN.sub(replacer, code)
    lines = code.splitlines()
    # Remove empty lines and strip whitespace
    processed_lines = [line.strip() for line in lines if line.strip()]
    full_lines_no_comments = [SINGLE_LINE_COMMENT_PATTERN.sub('', line) for line in lines]
    return lines, processed_lines, full_lines_no_comments

def calculate_weighted_score(scores):
    """Calculates the final weighted suspiciousness score."""
    total_score = 0
    total_weight = 0
    for factor, data in scores.items():
        if factor in WEIGHTS:
            total_score += data['score'] * WEIGHTS[factor]
            total_weight += WEIGHTS[factor]

    if total_weight == 0:
        return 0
    # Normalize the score based on the weights used
    final_score = (total_score / total_weight) * 100
    return min(max(final_score, 0), 100) # Clamp between 0 and 100

# --- Analysis Functions ---

def analyze_comments(lines):
    """Analyzes comment density, types, and style."""
    reasons = []
    scores = {
        'comment_density': {'score': 0.0, 'details': ''},
        'obvious_comments': {'score': 0.0, 'details': ''},
        'todo_fixme_presence': {'score': 1.0, 'details': 'No TODO/FIXME found (common in human code)'}, # Assume suspicious if none found
        'comment_style_consistency': {'score': 0.0, 'details': ''}
    }
    
    total_lines = len(lines)
    if total_lines == 0:
        return scores, reasons

    comment_lines = 0
    obvious_comment_count = 0
    has_todo_fixme = False
    has_single_line = False
    has_block_line = False # Approximation: check if line *only* contains block comment markers

    original_code_str = "\n".join(lines)
    block_comments = BLOCK_COMMENT_PATTERN.findall(original_code_str)
    
    # Recalculate line types considering original block comments
    line_types = [] # 'code', 'sl_comment', 'bl_comment_line', 'mixed'
    for line in lines:
        is_sl = bool(SINGLE_LINE_COMMENT_PATTERN.search(line))
        # Simple check if line seems to be part of a block comment
        is_bl_part = '/*' in line or '*/' in line or (line.strip().startswith('*') and not line.strip().startswith('*/'))
        code_part = SINGLE_LINE_COMMENT_PATTERN.sub('', line).strip()

        if is_sl and not code_part:
            line_types.append('sl_comment')
            has_single_line = True
            comment_lines += 1
        elif is_bl_part and not code_part:
             line_types.append('bl_comment_line')
             has_block_line = True # Approximating block comment lines
             comment_lines += 1
        elif is_sl and code_part:
             line_types.append('mixed')
             comment_lines += 0.5 # Count mixed lines partially
        elif is_bl_part and code_part:
             line_types.append('mixed')
             # Harder to quantify accurately without parsing
        elif code_part:
             line_types.append('code')
        # else: empty line, ignore for density

    # Add block comment content analysis
    all_comment_content = SINGLE_LINE_COMMENT_PATTERN.findall(original_code_str) + block_comments
    for comment_content in all_comment_content:
        if TODO_FIXME_PATTERN.search(comment_content):
            has_todo_fixme = True
        for pattern in OBVIOUS_COMMENT_PATTERNS:
            if pattern.search(comment_content):
                obvious_comment_count += 1
                break # Count max once per comment block/line

    # --- Scoring ---
    non_empty_lines = len([l for l in lines if l.strip()])
    if non_empty_lines > 0:
        density = comment_lines / non_empty_lines
        scores['comment_density']['details'] = f"{density:.2f} ({comment_lines}/{non_empty_lines})"
        if density < COMMENT_DENSITY_LOW_THRESHOLD:
            scores['comment_density']['score'] = 0.8
            reasons.append(f"Very low comment density ({density:.2f}), potentially AI-generated.")
        elif density > COMMENT_DENSITY_HIGH_THRESHOLD:
            scores['comment_density']['score'] = 0.6
            reasons.append(f"High comment density ({density:.2f}), possibly overly verbose AI comments.")
        else:
             scores['comment_density']['score'] = 0.1 # Neutral/Slightly human

    if obvious_comment_count > 0:
         # Scale score by how many obvious comments relative to total comments
         total_comments_approx = comment_lines + obvious_comment_count # Rough estimate
         if total_comments_approx > 0:
             obvious_ratio = obvious_comment_count / total_comments_approx
             scores['obvious_comments']['score'] = min(obvious_ratio * 2.0, 1.0) # Amplify ratio effect
             scores['obvious_comments']['details'] = f"{obvious_comment_count} obvious comments found (ratio ~{obvious_ratio:.2f})"
             if scores['obvious_comments']['score'] > 0.5:
                 reasons.append(f"Contains {obvious_comment_count} comments stating the obvious, common in AI.")

    if not has_todo_fixme:
        scores['todo_fixme_presence']['score'] = 0.7 # Higher suspicion if missing
        reasons.append("Lack of TODO/FIXME markers, often present in human development cycles.")
    else:
         scores['todo_fixme_presence']['score'] = 0.0 # Finding them is a good sign of human origin
         scores['todo_fixme_presence']['details'] = 'TODO/FIXME markers found.'


    if has_single_line and has_block_line: # Simple check for mixed styles
        scores['comment_style_consistency']['score'] = 0.4
        scores['comment_style_consistency']['details'] = "Mixed // and /* */ comment styles detected."
        reasons.append("Inconsistent comment styles (using both // and /* */) might occur, but less common for uniform AI output.")
    elif has_single_line or has_block_line:
         scores['comment_style_consistency']['score'] = 0.1 # Consistent style
         scores['comment_style_consistency']['details'] = "Consistent comment style detected."
    else:
         scores['comment_style_consistency']['score'] = 0.0 # No comments to judge
         scores['comment_style_consistency']['details'] = "No comments found to analyze style consistency."


    return scores, reasons

def analyze_formatting(lines):
    """Analyzes indentation, spacing, and line length."""
    reasons = []
    scores = {
        'indentation_consistency': {'score': 0.0, 'details': ''},
        'operator_spacing_consistency': {'score': 0.0, 'details': ''},
        'line_length_variance': {'score': 0.0, 'details': ''}
    }
    
    if not lines:
        return scores, reasons

    line_lengths = []
    indentation_types = {'space': 0, 'tab': 0, 'mixed': 0, 'none': 0}
    leading_spaces = []
    operator_spacing_consistent = 0
    operator_spacing_inconsistent = 0
    lines_with_operators = 0

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith(('#', '//')): # Ignore preprocessor/comments for formatting analysis
            continue

        line_lengths.append(len(stripped_line))

        # Indentation check
        leading_whitespace = line[:len(line) - len(line.lstrip())]
        if not leading_whitespace:
            indentation_types['none'] += 1
        elif '\t' in leading_whitespace and ' ' in leading_whitespace:
            indentation_types['mixed'] += 1
        elif '\t' in leading_whitespace:
            indentation_types['tab'] += 1
            leading_spaces.append(len(leading_whitespace)) # Count tabs as units
        elif ' ' in leading_whitespace:
            indentation_types['space'] += 1
            leading_spaces.append(len(leading_whitespace)) # Count spaces

        # Operator spacing check (simple version)
        ops_in_line = OPERATOR_SPACING_PATTERN.findall(stripped_line)
        if ops_in_line:
            lines_with_operators += 1
            # Check if spacing *around* operators is consistent *within the line*
            # Example: a=b vs c = d is inconsistency across lines. a = b+c is inconsistency within a line.
            # This simplified check looks for adjacent non-space char before OR after operator
            spaced_correctly = 0
            for op in ops_in_line:
                 # Find exact position - requires more careful regex or parsing.
                 # Simplified: Check if *any* operator lacks space on both sides if it's not at start/end
                 pattern = r'(?<!\s)' + re.escape(op) + r'|' + re.escape(op) + r'(?!\s)'
                 if not re.search(pattern, stripped_line):
                      spaced_correctly += 1 # Assume spaced if no immediate neighbor

            # This is a very rough heuristic: if *any* operator seems inconsistently spaced
            if spaced_correctly < len(ops_in_line):
                 operator_spacing_inconsistent += 1
            else:
                 operator_spacing_consistent += 1


    # --- Scoring ---
    # Indentation
    total_indented_lines = indentation_types['space'] + indentation_types['tab'] + indentation_types['mixed']
    if total_indented_lines > 0:
        mixed_ratio = indentation_types['mixed'] / total_indented_lines
        if indentation_types['space'] > 0 and indentation_types['tab'] > 0:
            scores['indentation_consistency']['score'] = 0.8
            scores['indentation_consistency']['details'] = "Mixed spaces and tabs for indentation."
            reasons.append("Mixed spaces and tabs used for indentation, less common for linters/auto-formatters often used by humans or enforced by AI.")
        elif mixed_ratio > INDENTATION_MIXED_THRESHOLD :
             scores['indentation_consistency']['score'] = 0.6
             scores['indentation_consistency']['details'] = f"High ratio ({mixed_ratio:.2f}) of lines with potentially mixed space/tab leading whitespace."
             reasons.append("Inconsistent indentation (potential mix of spaces/tabs on same lines) detected.")
        else:
            # Check consistency of space indentation levels (e.g., multiples of 2 or 4)
            if indentation_types['space'] > 1:
                space_diffs = {abs(leading_spaces[i] - leading_spaces[i-1]) for i in range(1, len(leading_spaces)) if leading_spaces[i] > 0 and leading_spaces[i-1] > 0}
                common_diffs = {2, 4, 8}
                if not space_diffs.issubset(common_diffs) and len(space_diffs) > 2 : # Allow some variance, but too many odd diffs is weird
                     scores['indentation_consistency']['score'] = 0.4
                     scores['indentation_consistency']['details'] = f"Unusual indentation level increments detected: {space_diffs}"
                     reasons.append("Indentation levels seem inconsistent (not typical multiples of 2/4 spaces).")
                else:
                     scores['indentation_consistency']['score'] = 0.1 # Reasonably consistent
                     scores['indentation_consistency']['details'] = "Indentation appears consistent."

    # Operator Spacing
    if lines_with_operators > 0:
        inconsistency_ratio = operator_spacing_inconsistent / lines_with_operators
        scores['operator_spacing_consistency']['details'] = f"{operator_spacing_inconsistent}/{lines_with_operators} lines show potential operator spacing inconsistency (ratio: {inconsistency_ratio:.2f})."
        if inconsistency_ratio > OPERATOR_SPACING_INCONSISTENCY_THRESHOLD:
            scores['operator_spacing_consistency']['score'] = 0.7
            reasons.append(f"Inconsistent spacing around operators found in ~{inconsistency_ratio:.1%} of relevant lines.")
        else:
             scores['operator_spacing_consistency']['score'] = 0.1 # Seems consistent

    # Line Length Variance
    if len(line_lengths) > 1:
        variance = statistics.variance(line_lengths)
        mean_len = statistics.mean(line_lengths)
        scores['line_length_variance']['details'] = f"Mean={mean_len:.1f}, Var={variance:.1f}"
        # Check for very low variance OR excessively long lines on average
        if variance < LINE_LENGTH_MIN_VARIANCE and mean_len > 20: # Avoid penalizing very short snippets
            scores['line_length_variance']['score'] = 0.6
            reasons.append(f"Very low line length variance ({variance:.1f}), suggesting robotic consistency.")
        elif mean_len > LINE_LENGTH_MAX_COMMON:
             scores['line_length_variance']['score'] = 0.4 # Slightly suspicious
             reasons.append(f"Average line length ({mean_len:.1f}) exceeds common limits ({LINE_LENGTH_MAX_COMMON}).")
        else:
             scores['line_length_variance']['score'] = 0.1 # Normal variance

    return scores, reasons

def analyze_structure(processed_lines, full_lines_no_comments):
    """Analyzes generic names, complexity proxy, etc."""
    reasons = []
    scores = {
        'generic_variable_names': {'score': 0.0, 'details': ''},
        'code_complexity_proxy': {'score': 0.0, 'details': ''},
        # Could add function length analysis here if needed
    }
    
    if not processed_lines:
        return scores, reasons

    variable_names = []
    complexity_keyword_count = 0
    total_words = 0

    full_code_no_comments = "\n".join(full_lines_no_comments)

    # Extract potential variable names (simple regex approach)
    for match in VARIABLE_DECL_PATTERN.finditer(full_code_no_comments):
        variable_names.append(match.group(2))

    # Count complexity keywords and total words
    words = re.findall(r'\b\w+\b', full_code_no_comments)
    total_words = len(words)
    if total_words > 0:
        for word in words:
            if word in COMPLEXITY_KEYWORDS:
                complexity_keyword_count += 1

    # --- Scoring ---
    # Generic Variable Names
    if variable_names:
        generic_count = sum(1 for name in variable_names if name in GENERIC_NAMES)
        generic_ratio = generic_count / len(variable_names)
        scores['generic_variable_names']['details'] = f"{generic_count}/{len(variable_names)} generic names (ratio: {generic_ratio:.2f})"
        if generic_ratio > GENERIC_NAME_RATIO_THRESHOLD:
            scores['generic_variable_names']['score'] = min(generic_ratio * 1.5, 1.0) # Scale up suspicion
            reasons.append(f"High ratio ({generic_ratio:.1%}) of generic variable names (e.g., i, temp, data) detected.")
        else:
            scores['generic_variable_names']['score'] = 0.1 # Normal usage
    
    # Code Complexity Proxy (Keyword Density)
    if total_words > 0:
         keyword_density = complexity_keyword_count / total_words
         scores['code_complexity_proxy']['details'] = f"{complexity_keyword_count} complexity keywords / {total_words} total words (density: {keyword_density:.3f})"
         # High density might mean overly simple/repetitive structures OR verbose AI, low might mean simple task or advanced techniques
         # This is a weak indicator alone. Penalize extremes slightly.
         if keyword_density > COMPLEXITY_KEYWORDS_DENSITY_HIGH:
              scores['code_complexity_proxy']['score'] = 0.4
              reasons.append(f"High density ({keyword_density:.3f}) of basic complexity keywords (if, for, while), potentially indicating verbose or simplistic AI logic.")
         elif keyword_density < 0.01 and total_words > 50: # Very low density in non-trivial code
              scores['code_complexity_proxy']['score'] = 0.3
              reasons.append(f"Very low density ({keyword_density:.3f}) of basic complexity keywords, might indicate unusual structure or overly simple AI generation.")
         else:
              scores['code_complexity_proxy']['score'] = 0.1 # Normal range

    return scores, reasons

def analyze_error_handling(full_lines_no_comments):
    """Analyzes the presence and type of error handling."""
    reasons = []
    scores = {
        'error_handling_presence': {'score': 1.0, 'details': 'No significant error handling keywords found.'} # Suspicious by default
    }
    
    keyword_count = 0
    total_lines = len(full_lines_no_comments)
    if total_lines == 0:
        return scores, reasons

    full_code = "\n".join(full_lines_no_comments)
    words = re.findall(r'\b\w+\b', full_code)

    for word in words:
        if word in ERROR_HANDLING_KEYWORDS:
            keyword_count += 1

    # --- Scoring ---
    if keyword_count > 0:
        # Simple presence check - finding *any* is a good sign for human code
        scores['error_handling_presence']['score'] = 0.1 # Low suspicion if found
        scores['error_handling_presence']['details'] = f"{keyword_count} error handling keywords found ({', '.join(ERROR_HANDLING_KEYWORDS & set(words))})."
        # More sophisticated analysis could check *how* they are used (e.g., empty catch blocks)
    else:
        # Score remains high (suspicious) if none found, especially in longer code
        if total_lines > 10: # More significant if missing in larger snippets
             scores['error_handling_presence']['score'] = 0.8
             reasons.append("Lack of explicit error handling (try/catch, assert, etc.), potentially AI 'happy path' code.")
        else:
             scores['error_handling_presence']['score'] = 0.5 # Less significant in very short snippets
             reasons.append("Minimal or no explicit error handling detected (less critical for short snippets).")


    return scores, reasons

# --- Main Detection Function ---

def detect_ai_cpp_code(cpp_code):
    """
    Analyzes C++ code to detect potential AI generation based on heuristics.

    Args:
        cpp_code (str): The C++ code snippet or full file content.

    Returns:
        str: A JSON string containing the analysis results:
             - suspiciousness_percentage (float): 0-100 likelihood estimate.
             - reasons (list): List of strings explaining suspicious findings.
             - factor_scores (dict): Detailed scores for each analysis factor.
    """
    if not isinstance(cpp_code, str) or not cpp_code.strip():
        return json.dumps({
            "suspiciousness_percentage": 0.0,
            "reasons": ["Input code is empty or invalid."],
            "factor_scores": {}
        }, indent=2)

    try:
        lines, processed_lines, full_lines_no_comments = preprocess_code(cpp_code)

        all_reasons = []
        all_scores = {}

        # Run analyses
        comment_scores, comment_reasons = analyze_comments(lines)
        all_scores.update(comment_scores)
        all_reasons.extend(comment_reasons)

        format_scores, format_reasons = analyze_formatting(lines) # Use original lines for indentation
        all_scores.update(format_scores)
        all_reasons.extend(format_reasons)
        
        structure_scores, structure_reasons = analyze_structure(processed_lines, full_lines_no_comments)
        all_scores.update(structure_scores)
        all_reasons.extend(structure_reasons)

        error_scores, error_reasons = analyze_error_handling(full_lines_no_comments)
        all_scores.update(error_scores)
        all_reasons.extend(error_reasons)


        # Calculate final score
        final_percentage = calculate_weighted_score(all_scores)

        # Filter unique reasons
        unique_reasons = sorted(list(set(all_reasons)))

        result = {
            "suspiciousness_percentage": round(final_percentage, 2),
            "reasons": unique_reasons,
            "factor_scores": all_scores  # Include detailed scores for transparency/debugging
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        # Basic error handling for the detector itself
        return json.dumps({
            "suspiciousness_percentage": -1.0, # Indicate error
            "reasons": [f"An error occurred during analysis: {type(e).__name__} - {e}"],
            "factor_scores": {}
        }, indent=2)


# --- Example Usage ---




if __name__ == "__main__":
    
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing object_id argument"}))
        sys.exit(1)

    document_id = sys.argv[1]  # Get object_id from command line argument

    doc_content = fetch_document_by_id(document_id)
    if doc_content:
        analysis_result = detect_ai_cpp_code(doc_content['code'])

        if analysis_result:
           
            # json_output = json.dumps(analysis_result, indent=4, default=str)
            print(analysis_result)
        else:
            print("Analysis could not be performed on the document.")



