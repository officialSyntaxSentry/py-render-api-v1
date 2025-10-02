import re
import json
import math
import statistics
from collections import Counter
import sys
from pymongo import MongoClient
from bson.objectid import ObjectId

PYCODESTYLE_AVAILABLE = True
try:
    import pycodestyle
except ImportError:
    PYCODESTYLE_AVAILABLE = False


# --- Configuration Thresholds and Weights ---



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








# Adjust these thresholds based on observations or specific needs
THRESHOLDS = {
    'comment_density_low': 0.03,      # Below this is suspicious (potentially AI)
    'comment_density_high': 0.35,     # Above this is suspicious (potentially AI boilerplate comments)
    'generic_comment_ratio_high': 0.5, # More than 50% of comments being generic is suspicious
    'todo_fixme_low': 1,              # Less than 1 TODO/FIXME might be slightly more AI-like (weak signal)
    'avg_line_len_low': 15,
    'avg_line_len_high': 100,         # Very long average lines might be less common for AI (sticking to limits)
    'line_len_stddev_low': 5.0,       # Very low variation in line length is suspicious
    'indentation_consistency_threshold': 0.95, # % of lines matching dominant indent pattern
    'blank_line_ratio_low': 0.05,
    'blank_line_ratio_high': 0.30,    # Very systematic or sparse blank lines
    'op_spacing_consistency_threshold': 0.90, # % of operators with consistent spacing
    'avg_var_name_len_low': 3,
    'avg_var_name_len_high': 15,
    'var_name_len_stddev_low': 1.5,   # Low variation in variable name length
    'avg_method_name_len_low': 4,
    'avg_method_name_len_high': 20,
    'method_name_len_stddev_low': 2.0,# Low variation in method name length
    'generic_name_ratio_high': 0.25,  # High percentage of generic names used
    'magic_number_ratio_high': 0.05   # Ratio of potential magic numbers to code lines
}

# Weights for combining scores (should sum roughly to 1.0)
WEIGHTS = {
    'comments': 0.25,
    'formatting': 0.35,
    'naming': 0.25,
    'structure': 0.15,
}

# --- Regular Expressions ---
# Use 'DOTALL' for multi-line comments, 'MULTILINE' for line-based checks
RE_SINGLE_LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)
RE_MULTI_LINE_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
RE_CODE_LINE = re.compile(r"^\s*([^\s/].*?);?\s*(?://.*)?$", re.MULTILINE) # Basic code line detection (heuristic)
RE_BLANK_LINE = re.compile(r"^\s*$", re.MULTILINE)
RE_GENERIC_COMMENT_PATTERNS = re.compile(
    r"//\s*(?:Initialize|Declare|Set|Get|Return|Loop over|Iterate|Check if|Process|Handle|Define|Constant|Variable|Parameter|Argument|Constructor|Method|Function)",
    re.IGNORECASE
)
RE_CODE_RESTATING_COMMENT = re.compile(r"//\s*\w+\s*(?:=|is assigned|set to)", re.IGNORECASE) # Simple heuristic
RE_TODO_FIXME = re.compile(r"//\s*(?:TODO|FIXME|XXX|HACK)", re.IGNORECASE)
RE_OPERATOR_SPACING = re.compile(r"\s*([+\-*/%&|^<>=!]=?|&&|\|\|)\s*") # Detect operators and surrounding space
RE_VARIABLE_DECLARATION = re.compile(
    r"\b(int|String|double|float|boolean|long|short|byte|char|var|final\s+\w+|\w+<.*?>|List<.*?>|Map<.*?>|Set<.*?>|[\w\.<>\[\]]+)\s+([a-zA-Z_]\w*)\s*[=;,)]"
)
RE_METHOD_DEFINITION = re.compile(
    r"\b(?:public|private|protected|static|final|abstract|synchronized|\s)*<?[a-zA-Z_]\w*>?\s+([a-zA-Z_]\w*)\s*\("
)
RE_GENERIC_NAMES = re.compile(r"\b(temp|tmp|data|value|item|elem|element|result|res|list|map|set|obj|object|input|output|param|arg|ctx|context|str|num|flag)\b", re.IGNORECASE)
RE_MAGIC_NUMBER = re.compile(r"[^\"'a-zA-Z_.\d\s)](-?\d+(?:\.\d+)?(?:[fLdD]?)?)\b(?!\s*//)") # Look for numbers not in strings/comments/decimals/vars


# --- Helper Functions ---

def clean_code(code):
    """Remove multi-line comments first to simplify line-based analysis."""
    code = RE_MULTI_LINE_COMMENT.sub("", code)
    return code

def get_lines(code):
    """Split code into lines, handling different line endings."""
    return code.splitlines()

def count_matches(pattern, text):
    """Count non-overlapping matches of a regex pattern."""
    return len(pattern.findall(text))

# --- Analysis Functions ---

def analyze_comments(code, lines):
    """Analyzes comment density, style, and content."""
    metrics = {}
    reasons = []
    score = 0.0 # Score 0-1, higher is more suspicious (AI-like)

    single_line_comments = RE_SINGLE_LINE_COMMENT.findall("\n".join(lines)) # Use cleaned lines
    num_single_line = len(single_line_comments)
    # Multi-line comments are removed by clean_code, count them before cleaning if needed
    # For simplicity here, we focus on single-line after cleaning.

    total_lines = len(lines)
    code_lines = [line for line in lines if not RE_BLANK_LINE.match(line) and not RE_SINGLE_LINE_COMMENT.match(line.strip())]
    num_code_lines = len(code_lines)
    num_comment_lines = num_single_line # Simplified: only single line comments after cleaning

    if total_lines == 0: return {'metrics': metrics, 'reasons': reasons, 'score': 0.0}

    metrics['total_lines'] = total_lines
    metrics['code_lines'] = num_code_lines
    metrics['comment_lines'] = num_comment_lines

    if num_code_lines > 0:
        comment_density = num_comment_lines / num_code_lines
    else:
        comment_density = 0 if num_comment_lines == 0 else 1.0 # All comments or none
    metrics['comment_density'] = round(comment_density, 3)

    # Score based on density
    if comment_density < THRESHOLDS['comment_density_low']:
        score += 0.6
        reasons.append(f"Very low comment density ({metrics['comment_density']:.1%}), potentially AI-generated or uncommented human code.")
    elif comment_density > THRESHOLDS['comment_density_high']:
        score += 0.4 # High density *could* be AI boilerplate
        reasons.append(f"High comment density ({metrics['comment_density']:.1%}), potentially AI boilerplate or detailed human code.")
    else:
        score += 0.1 # Moderate density is less indicative

    # Analyze comment content (if any comments exist)
    if num_comment_lines > 0:
        generic_comments = 0
        restating_comments = 0
        todo_fixme_comments = 0
        comment_lengths = []

        for comment in single_line_comments:
            comment_text = comment.strip()[2:].strip() # Remove '//' and whitespace
            if not comment_text: continue
            comment_lengths.append(len(comment_text))
            if RE_GENERIC_COMMENT_PATTERNS.search(comment_text):
                generic_comments += 1
            if RE_CODE_RESTATING_COMMENT.search(comment_text):
                 # Add check if preceding line has the assignment? More complex.
                 # Simple check for now.
                restating_comments += 1
            if RE_TODO_FIXME.search(comment_text):
                todo_fixme_comments += 1

        metrics['generic_comment_count'] = generic_comments
        metrics['restating_comment_count'] = restating_comments
        metrics['todo_fixme_comment_count'] = todo_fixme_comments
        metrics['avg_comment_length'] = round(statistics.mean(comment_lengths), 1) if comment_lengths else 0

        generic_ratio = generic_comments / num_comment_lines
        metrics['generic_comment_ratio'] = round(generic_ratio, 3)
        if generic_ratio > THRESHOLDS['generic_comment_ratio_high']:
            score += 0.5
            reasons.append(f"High ratio of generic comments ({metrics['generic_comment_ratio']:.1%}), suggesting AI generation.")

        # TODO/FIXME are usually human markers
        if todo_fixme_comments < THRESHOLDS['todo_fixme_low']:
            score += 0.1 # Weak indicator
            reasons.append("Lack of TODO/FIXME comments, slightly more common in AI code.")
        else:
            score -= 0.3 # Presence of TODO/FIXME makes it lean more human
            reasons.append(f"Presence of {todo_fixme_comments} TODO/FIXME comments suggests human authorship.")

    # Normalize score to be between 0 and 1
    final_score = max(0.0, min(1.0, score / 1.5)) # Adjust divisor based on max possible raw score

    return {'metrics': metrics, 'reasons': reasons, 'score': final_score}


def analyze_formatting(lines):
    """Analyzes indentation, spacing, line length, and blank lines."""
    metrics = {}
    reasons = []
    score = 0.0 # Score 0-1, higher is more suspicious (AI-like)

    total_lines = len(lines)
    if total_lines == 0: return {'metrics': metrics, 'reasons': reasons, 'score': 0.0}

    non_empty_lines = [line for line in lines if line.strip()]
    code_lines_for_indent = [line for line in non_empty_lines if not RE_SINGLE_LINE_COMMENT.match(line.strip())]
    num_code_lines_for_indent = len(code_lines_for_indent)

    # 1. Indentation Consistency
    indentations = []
    leading_whitespace_chars = set()
    if num_code_lines_for_indent > 1: # Need multiple lines to check consistency
        for line in code_lines_for_indent:
            match = re.match(r"^(\s*)", line)
            indent = match.group(1) if match else ""
            indentations.append(indent)
            if indent:
                leading_whitespace_chars.update(set(indent))

        # Check for mixed tabs/spaces (strong human indicator if mixed)
        if '\t' in leading_whitespace_chars and ' ' in leading_whitespace_chars:
            metrics['indentation_mixed_tabs_spaces'] = True
            score -= 0.5 # Strong indicator of human (or poorly configured tool)
            reasons.append("Mixed tabs and spaces used for indentation, less common for AI.")
        else:
            metrics['indentation_mixed_tabs_spaces'] = False
            # Check consistency of the dominant indent style (spaces or tabs)
            if indentations:
                indent_counts = Counter(indentations)
                dominant_indent, dominant_count = indent_counts.most_common(1)[0]
                # Heuristic: Check if levels are consistent multiples (e.g., 4 spaces, 8 spaces)
                # This is simplified. A proper AST check is better.
                is_consistent = True
                base_indent_unit = None
                if ' ' in leading_whitespace_chars: base_indent_unit = ' ' * 4 # Assume 4 spaces common
                elif '\t' in leading_whitespace_chars: base_indent_unit = '\t'

                consistent_lines = 0
                if base_indent_unit:
                    for indent in indentations:
                        if not indent or len(indent) % len(base_indent_unit) == 0 and all(c == base_indent_unit[0] for c in indent):
                            consistent_lines += 1
                        # Allow empty indent or root level indent ""
                    consistency_ratio = consistent_lines / num_code_lines_for_indent if num_code_lines_for_indent > 0 else 1.0
                else: # No indentation found or only root level
                     consistency_ratio = 1.0

                metrics['indentation_consistency_ratio'] = round(consistency_ratio, 3)
                if consistency_ratio >= THRESHOLDS['indentation_consistency_threshold']:
                    score += 0.6
                    reasons.append(f"Highly consistent indentation ({metrics['indentation_consistency_ratio']:.1%}), typical of AI / auto-formatters.")
                elif consistency_ratio < 0.7: # Significantly inconsistent
                    score -= 0.3
                    reasons.append(f"Potentially inconsistent indentation ({metrics['indentation_consistency_ratio']:.1%}), might suggest human editing.")
                else:
                    score += 0.1 # Moderately consistent


    # 2. Line Length Analysis
    line_lengths = [len(line) for line in non_empty_lines]
    if line_lengths:
        metrics['avg_line_length'] = round(statistics.mean(line_lengths), 1)
        metrics['max_line_length'] = max(line_lengths)
        metrics['line_length_stddev'] = round(statistics.stdev(line_lengths), 1) if len(line_lengths) > 1 else 0.0

        if metrics['avg_line_length'] < THRESHOLDS['avg_line_len_low'] or metrics['avg_line_length'] > THRESHOLDS['avg_line_len_high']:
            score += 0.1 # Weak indicator for unusual average length
            reasons.append(f"Average line length ({metrics['avg_line_length']}) is outside typical range, slightly suspicious.")

        if len(line_lengths) > 1 and metrics['line_length_stddev'] < THRESHOLDS['line_len_stddev_low']:
            score += 0.4
            reasons.append(f"Very low standard deviation in line length ({metrics['line_length_stddev']}), suggesting uniform structure possibly from AI.")
    else:
        metrics['avg_line_length'] = 0
        metrics['max_line_length'] = 0
        metrics['line_length_stddev'] = 0

    # 3. Blank Line Ratio
    num_blank_lines = count_matches(RE_BLANK_LINE, "\n".join(lines))
    blank_line_ratio = num_blank_lines / total_lines if total_lines > 0 else 0.0
    metrics['blank_line_ratio'] = round(blank_line_ratio, 3)

    if blank_line_ratio < THRESHOLDS['blank_line_ratio_low']:
        score += 0.2
        reasons.append(f"Very low ratio of blank lines ({metrics['blank_line_ratio']:.1%}), potentially AI-generated compact code.")
    elif blank_line_ratio > THRESHOLDS['blank_line_ratio_high']:
        score += 0.2
        reasons.append(f"High ratio of blank lines ({metrics['blank_line_ratio']:.1%}), possibly overly systematic AI formatting or verbose human.")

    # 4. Operator Spacing Consistency (Simplified check)
    operators_found = RE_OPERATOR_SPACING.findall("\n".join(code_lines_for_indent))
    if operators_found:
        spaced_correctly = 0 # e.g., ' = '
        spaced_incorrectly = 0 # e.g., '= ', ' =' , '='
        # This heuristic checks if space exists on BOTH sides vs not. More granular checks are possible.
        for op_match in RE_OPERATOR_SPACING.finditer("\n".join(code_lines_for_indent)):
            full_match = op_match.group(0)
            op = op_match.group(1)
            # Check if spaces exist before AND after the operator itself
            if full_match.startswith(' ') and full_match.endswith(' '):
                 spaced_correctly += 1
            elif not full_match.startswith(' ') and not full_match.endswith(' '):
                 spaced_correctly += 1 # Also consider no space consistent, e.g. x=y+z
            else: # Mixed spacing like ' =' or '= '
                 spaced_incorrectly += 1

        total_ops_checked = spaced_correctly + spaced_incorrectly
        if total_ops_checked > 0:
             consistency_ratio = spaced_correctly / total_ops_checked
             metrics['operator_spacing_consistency'] = round(consistency_ratio, 3)
             if consistency_ratio >= THRESHOLDS['op_spacing_consistency_threshold']:
                 score += 0.3
                 reasons.append(f"Highly consistent spacing around operators ({metrics['operator_spacing_consistency']:.1%}).")
             elif consistency_ratio < 0.7:
                 score -= 0.2
                 reasons.append(f"Inconsistent spacing around operators ({metrics['operator_spacing_consistency']:.1%}), potentially human.")

    # 5. Trailing Whitespace (Weak indicator nowadays)
    trailing_whitespace_lines = sum(1 for line in lines if line != line.rstrip() and line.strip())
    metrics['trailing_whitespace_lines'] = trailing_whitespace_lines
    if trailing_whitespace_lines > 2: # More than a couple might be human habit
        score -= 0.1
        reasons.append(f"Found {trailing_whitespace_lines} lines with trailing whitespace, slightly less common with AI/formatters.")

    # Normalize score
    final_score = max(0.0, min(1.0, score / 1.8)) # Adjust divisor

    return {'metrics': metrics, 'reasons': reasons, 'score': final_score}


def analyze_naming(code):
    """Analyzes variable and method names for length, variance, and generic terms."""
    metrics = {}
    reasons = []
    score = 0.0 # Score 0-1, higher is more suspicious (AI-like)

    variable_names = [match.group(2) for match in RE_VARIABLE_DECLARATION.finditer(code)]
    method_names = [match.group(1) for match in RE_METHOD_DEFINITION.finditer(code)]

    all_names = variable_names + method_names
    if not all_names:
        return {'metrics': metrics, 'reasons': reasons, 'score': 0.0}

    # Variable Name Analysis
    if variable_names:
        var_name_lengths = [len(name) for name in variable_names]
        metrics['variable_count'] = len(variable_names)
        metrics['avg_variable_name_length'] = round(statistics.mean(var_name_lengths), 1)
        metrics['variable_name_length_stddev'] = round(statistics.stdev(var_name_lengths), 1) if len(var_name_lengths) > 1 else 0.0

        if metrics['avg_variable_name_length'] < THRESHOLDS['avg_var_name_len_low'] or metrics['avg_variable_name_length'] > THRESHOLDS['avg_var_name_len_high']:
            score += 0.1
            reasons.append(f"Average variable name length ({metrics['avg_variable_name_length']}) is slightly unusual.")
        if len(var_name_lengths) > 1 and metrics['variable_name_length_stddev'] < THRESHOLDS['var_name_len_stddev_low']:
            score += 0.3
            reasons.append(f"Low variation in variable name length (StdDev: {metrics['variable_name_length_stddev']}), potentially AI pattern.")

    # Method Name Analysis
    if method_names:
        method_name_lengths = [len(name) for name in method_names]
        metrics['method_count'] = len(method_names)
        metrics['avg_method_name_length'] = round(statistics.mean(method_name_lengths), 1)
        metrics['method_name_length_stddev'] = round(statistics.stdev(method_name_lengths), 1) if len(method_name_lengths) > 1 else 0.0

        if metrics['avg_method_name_length'] < THRESHOLDS['avg_method_name_len_low'] or metrics['avg_method_name_length'] > THRESHOLDS['avg_method_name_len_high']:
            score += 0.1
            reasons.append(f"Average method name length ({metrics['avg_method_name_length']}) is slightly unusual.")
        if len(method_name_lengths) > 1 and metrics['method_name_length_stddev'] < THRESHOLDS['method_name_len_stddev_low']:
            score += 0.3
            reasons.append(f"Low variation in method name length (StdDev: {metrics['method_name_length_stddev']}), potentially AI pattern.")

    # Generic Name Analysis
    generic_name_count = 0
    for name in all_names:
        if RE_GENERIC_NAMES.match(name):
            generic_name_count += 1
    metrics['generic_name_count'] = generic_name_count

    generic_ratio = generic_name_count / len(all_names) if all_names else 0.0
    metrics['generic_name_ratio'] = round(generic_ratio, 3)
    if generic_ratio > THRESHOLDS['generic_name_ratio_high']:
        score += 0.5
        reasons.append(f"High ratio of generic names like 'data', 'temp', 'value' ({metrics['generic_name_ratio']:.1%}), suggestive of AI.")

    # Normalize score
    final_score = max(0.0, min(1.0, score / 1.3)) # Adjust divisor

    return {'metrics': metrics, 'reasons': reasons, 'score': final_score}


def analyze_structure(code, lines):
    """Analyzes basic structural patterns like repetition and magic numbers."""
    metrics = {}
    reasons = []
    score = 0.0 # Score 0-1, higher is more suspicious (AI-like)

    code_lines = [line for line in lines if not RE_BLANK_LINE.match(line) and not RE_SINGLE_LINE_COMMENT.match(line.strip())]
    num_code_lines = len(code_lines)

    if num_code_lines == 0:
        return {'metrics': metrics, 'reasons': reasons, 'score': 0.0}

    # 1. Simple Repetition Check (Consecutive identical non-empty lines)
    # This is a very basic heuristic. Real repetition analysis needs AST/CFG.
    consecutive_duplicates = 0
    for i in range(len(code_lines) - 1):
        # Normalize whitespace for comparison
        line1_norm = " ".join(code_lines[i].strip().split())
        line2_norm = " ".join(code_lines[i+1].strip().split())
        if line1_norm == line2_norm and len(line1_norm) > 5: # Avoid matching empty braces etc.
            consecutive_duplicates += 1

    metrics['consecutive_duplicate_lines'] = consecutive_duplicates
    if num_code_lines > 5 and consecutive_duplicates / num_code_lines > 0.05: # If > 5% lines are duplicates of previous
        score += 0.3
        reasons.append(f"Detected {consecutive_duplicates} instances of consecutive identical code lines, potential AI boilerplate.")

    # 2. Magic Number Check (Simplified)
    magic_numbers = RE_MAGIC_NUMBER.findall(code)
    # Filter out common non-magic numbers like 0, 1, -1, maybe indices in loops? Hard heuristic.
    potential_magic_numbers = [n for n in magic_numbers if float(n) not in [0, 1, -1]]
    num_magic_numbers = len(potential_magic_numbers)
    metrics['potential_magic_numbers'] = num_magic_numbers

    magic_ratio = num_magic_numbers / num_code_lines if num_code_lines > 0 else 0.0
    metrics['magic_number_ratio'] = round(magic_ratio, 3)

    if magic_ratio > THRESHOLDS['magic_number_ratio_high']:
        score += 0.3
        reasons.append(f"High ratio ({metrics['magic_number_ratio']:.1%}) of potential 'magic numbers' (uncommented literals), could be AI or less careful human.")

    # Normalize score
    final_score = max(0.0, min(1.0, score / 0.6)) # Adjust divisor

    return {'metrics': metrics, 'reasons': reasons, 'score': final_score}


# --- Main Detection Function ---

def detect_ai_generated_java(java_code):
    """
    Analyzes Java code using multiple heuristics to estimate the likelihood of AI generation.

    Args:
        java_code (str): A string containing the Java code (full or snippet).

    Returns:
        str: A JSON string containing the analysis results:
             - suspicious_percentage (float): Estimated likelihood (0-100) the code is AI-generated.
             - reasons (list): A list of strings explaining the factors contributing to the score.
             - detailed_metrics (dict): Raw metrics collected during analysis.
             - factors (dict): Scores (0-1) for each analysis category.
    """
    if not isinstance(java_code, str) or not java_code.strip():
        return json.dumps({
            'suspicious_percentage': 0.0,
            'reasons': ["Input code is empty or invalid."],
            'detailed_metrics': {},
            'factors': {}
        }, indent=2)

    try:
        # Preprocessing
        cleaned_code = clean_code(java_code) # Removes multi-line comments
        lines = get_lines(cleaned_code) # Use code without multi-line comments for line-based analysis
        original_lines = get_lines(java_code) # Keep original for some checks if needed

        # Analysis
        comment_analysis = analyze_comments(cleaned_code, lines)
        formatting_analysis = analyze_formatting(lines) # Pass lines from cleaned code
        naming_analysis = analyze_naming(cleaned_code) # Analyze names in cleaned code
        structure_analysis = analyze_structure(cleaned_code, lines) # Analyze structure in cleaned code

        # Combine scores using weights
        total_score = (
            comment_analysis['score'] * WEIGHTS['comments'] +
            formatting_analysis['score'] * WEIGHTS['formatting'] +
            naming_analysis['score'] * WEIGHTS['naming'] +
            structure_analysis['score'] * WEIGHTS['structure']
        )

        # Ensure the score is capped between 0 and 1 before converting to percentage
        final_suspicion_score = max(0.0, min(1.0, total_score))
        suspicious_percentage = round(final_suspicion_score * 100, 2)

        # Collect reasons from all analyses
        all_reasons = (
            comment_analysis['reasons'] +
            formatting_analysis['reasons'] +
            naming_analysis['reasons'] +
            structure_analysis['reasons']
        )
        # Filter out reasons corresponding to scores near neutral (e.g., score additions of 0.1)
        # This requires linking reasons back to score increments, which is complex.
        # Simpler: just list all generated reasons. More advanced: filter based on score impact.

        # Consolidate metrics
        all_metrics = {
            'comments': comment_analysis['metrics'],
            'formatting': formatting_analysis['metrics'],
            'naming': naming_analysis['metrics'],
            'structure': structure_analysis['metrics'],
        }

        # Factor scores
        factor_scores = {
            'comments': round(comment_analysis['score'], 3),
            'formatting': round(formatting_analysis['score'], 3),
            'naming': round(naming_analysis['score'], 3),
            'structure': round(structure_analysis['score'], 3),
        }

        # Prepare JSON output
        result = {
            'suspicious_percentage': suspicious_percentage,
            'reasons': all_reasons if all_reasons else ["No specific indicators found; analysis inconclusive based on heuristics."],
            'factors': factor_scores,
            'detailed_metrics': all_metrics
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        # Basic error handling for unexpected issues during analysis
        return json.dumps({
            'suspicious_percentage': -1.0, # Indicate error
            'reasons': [f"An error occurred during analysis: {type(e).__name__} - {e}"],
            'detailed_metrics': {},
            'factors': {}
        }, indent=2)






if __name__ == "__main__":
    
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing object_id argument"}))
        sys.exit(1)

    document_id = sys.argv[1]  # Get object_id from command line argument

    doc_content = fetch_document_by_id(document_id)
    if doc_content:
        analysis_result = detect_ai_generated_java(doc_content['code'])

        if analysis_result:
           
            # json_output = json.dumps(analysis_result, indent=4, default=str)
            print(analysis_result)
        else:
            print("Analysis could not be performed on the document.")



