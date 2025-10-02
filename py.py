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



# Attempt to import optional dependencies
try:
    from radon.visitors import ComplexityVisitor
    from radon.metrics import h_visit
    RADON_AVAILABLE = True
except ImportError:
    RADON_AVAILABLE = False
    print("Warning: 'radon' library not found. Complexity analysis will be limited.")

try:
    import pycodestyle
    PYCODESTYLE_AVAILABLE = True
except ImportError:
    PYCODESTYLE_AVAILABLE = False
    print("Warning: 'pycodestyle' library not found. Formatting analysis will be limited.")

# Basic English dictionary words (expand for better accuracy)
# In a real system, load this from a file or use a more comprehensive library
COMMON_ENGLISH_WORDS = {
    "data", "value", "index", "item", "result", "list", "dict", "set", "file",
    "process", "compute", "calculate", "average", "total", "count", "sum",
    "get", "set", "add", "remove", "update", "find", "search", "sort",
    "parse", "read", "write", "input", "output", "error", "message",
    "user", "config", "setting", "parameter", "argument", "function",
    "class", "method", "object", "instance", "variable", "constant", "temp",
    "tmp", "buffer", "queue", "stack", "node", "tree", "graph", "matrix",
    "vector", "point", "line", "circle", "square", "number", "string", "bool",
    "true", "false", "none", "request", "response", "url", "api", "key", "id"
}
# Add common programming context words often used by humans too
COMMON_ENGLISH_WORDS.update({"foo", "bar", "baz", "spam", "eggs"})


class CodeAnalyzer:
    """Analyzes Python code snippets to determine likelihood of AI generation."""

    def __init__(self, code_snippet):
        """Initializes the CodeAnalyzer."""
        # Initialize results structure FIRST
        self.results = {
            "suspicious_percentage": 0.0,
            "detailed_justification": [],
            "pattern_analysis": [],
            "scores": defaultdict(float), # Internal scores for weighting
            "metrics": {} # Raw metrics collected
        }

        self.code = code_snippet.strip()
        self.lines = self.code.splitlines()
        self.non_empty_lines = [line for line in self.lines if line.strip()]
        self.loc = len(self.non_empty_lines)
        self.tokens = self._tokenize()
        self.tree = self._parse_ast()
        self.results = {
            "suspicious_percentage": 0.0,
            "detailed_justification": [],
            "pattern_analysis": [],
            "scores": defaultdict(float), # Internal scores for weighting
            "metrics": {} # Raw metrics collected
        }

    def _tokenize(self):
        """Tokenize the code snippet."""
        if not self.code:
            return []
        try:
            buffer = io.BytesIO(self.code.encode('utf-8'))
            return list(tokenize.tokenize(buffer.readline))
        except tokenize.TokenError as e:
            self.results["pattern_analysis"].append(f"Tokenization Error: {e}. Code might be incomplete or syntactically incorrect (human-like).")
            return []
        except IndentationError as e:
             self.results["pattern_analysis"].append(f"Indentation Error: {e}. Often indicates human iterative development.")
             # Try to proceed if possible, might fail later
             try:
                 buffer = io.BytesIO(self.code.encode('utf-8'))
                 # Tolerate errors during tokenization for partial analysis
                 return list(tokenize.tokenize(buffer.readline))
             except:
                 return []
        except Exception as e:
            self.results["pattern_analysis"].append(f"Unexpected Error during tokenization: {e}")
            return []


    def _parse_ast(self):
        """Parse the code into an Abstract Syntax Tree."""
        if not self.code:
            return None
        try:
            return ast.parse(self.code)
        except SyntaxError as e:
            self.results["detailed_justification"].append(f"Syntax Error detected: {e}. This strongly suggests human authorship or incomplete copy-pasting.")
            self.results["pattern_analysis"].append("Code contains syntax errors.")
            # Penalize AI score heavily for syntax errors
            self.results["scores"]["syntax_error"] = -50
            return None
        except Exception as e:
            self.results["pattern_analysis"].append(f"AST Parsing Error: {e}. Code might be structurally invalid.")
            return None

    # --- Analysis Factors ---

    def analyze_comments(self):
        """Analyzes comment style, frequency, and content."""
        if not self.tokens: return

        comments = [t for t in self.tokens if t.type == tokenize.COMMENT]
        num_comments = len(comments)
        comment_lines = set(t.start[0] for t in comments)
        num_comment_lines = len(comment_lines)

        self.results["metrics"]["comment_count"] = num_comments
        self.results["metrics"]["comment_lines"] = num_comment_lines
        self.results["metrics"]["comment_ratio"] = num_comment_lines / self.loc if self.loc > 0 else 0

        if self.loc == 0: return # Avoid division by zero

        total_comment_length = sum(len(c.string) for c in comments)
        avg_comment_length = total_comment_length / num_comments if num_comments > 0 else 0
        self.results["metrics"]["avg_comment_length"] = avg_comment_length

        structured_comments = 0
        informal_comments = 0
        todo_fixme_count = 0

        for comment_token in comments:
            comment_text = comment_token.string.lstrip('#').strip()
            # Check for PEP-8 style comments (# followed by space)
            if comment_token.string.startswith('# '):
                structured_comments += 1
            # Check for informal markers
            if re.search(r'\b(TODO|FIXME|XXX)\b', comment_text, re.IGNORECASE):
                todo_fixme_count += 1
                informal_comments += 1
            # Simplistic check for overly explanatory comments (can be improved)
            if len(comment_text.split()) > 10 and comment_text.endswith('.'):
                 # More likely explanatory if long and proper sentence structure
                 pass # This is harder to quantify reliably as AI-like vs helpful human

        # Scoring Logic
        score = 0
        justification = []

        comment_ratio = self.results["metrics"]["comment_ratio"]
        if comment_ratio > 0.3 and num_comments > 2: # High frequency
            score += 15
            justification.append("High comment frequency (>30% lines), potentially AI explanation.")
        elif comment_ratio == 0 and self.loc > 10: # No comments in significant code
            score -= 10
            justification.append("No comments found in a non-trivial snippet, potentially human.")
        elif 0 < comment_ratio < 0.05 and self.loc > 20: # Very few comments
             score -= 5
             justification.append("Very low comment frequency (<5%), possibly human.")

        if num_comments > 0:
            structured_ratio = structured_comments / num_comments
            if structured_ratio > 0.9:
                score += 10
                justification.append("Comments consistently follow PEP-8 style (# comment), common for AI.")
            elif structured_ratio < 0.5:
                 score -= 5
                 justification.append("Comments have inconsistent style (mix of '#comment' and '# comment'), more human-like.")

        if avg_comment_length > 40 and comment_ratio > 0.1:
            score += 10
            justification.append("Comments are relatively long on average, suggesting detailed explanation (AI-like).")
        elif 0 < avg_comment_length < 15:
            score -= 5
            justification.append("Comments are short on average, possibly quick human notes.")

        if todo_fixme_count > 0:
            score -= 20 # Strong human indicator
            justification.append(f"Found {todo_fixme_count} TODO/FIXME markers, strong human indicator.")
            self.results["pattern_analysis"].append("Presence of TODO/FIXME comments.")

        self.results["scores"]["comments"] = score
        self.results["detailed_justification"].extend(justification)

    def analyze_formatting(self):
        if not PYCODESTYLE_AVAILABLE or not self.code:
            if not PYCODESTYLE_AVAILABLE:
                 self.results["pattern_analysis"].append("Formatting analysis skipped: pycodestyle library not found.")
            return

        # --- REMOVE THE INCORRECT check_files CALL ---
        # style_guide = pycodestyle.StyleGuide(quiet=True)
        # Use StringIO to simulate a file - THIS IS WRONG FOR check_files
        # report = style_guide.check_files([io.StringIO(self.code)])
        # --- END REMOVAL ---


        # --- KEEP THE CORRECT Checker LOGIC ---
        # Use the Checker class which works directly with lines
        error_count = 0
        try:
            # Checker takes the lines directly. Provide a dummy filename.
            # Pass self.lines which are strings from self.code.splitlines()
            checker = pycodestyle.Checker(filename='snippet.py', lines=self.lines, quiet=True)
            # check_all() returns the total count of errors and warnings found.
            error_count = checker.check_all()
            self.results["metrics"]["pep8_violations"] = error_count
        except Exception as e:
            self.results["pattern_analysis"].append(f"Pycodestyle analysis failed: {e}")
            # Decide how to handle checker failure: assume 0 violations or add penalty?
            self.results["metrics"]["pep8_violations"] = 0 # Defaulting to 0 if checker fails


        # --- REST OF THE FUNCTION REMAINS THE SAME ---

        # Check indentation consistency (Tabs vs Spaces)
        indent_chars = set()
        has_indent = False # Track if any indentation exists
        for token in self.tokens:
            if token.type == tokenize.INDENT:
                # Check the first char of indent string, ignore if empty/whitespace only indent token
                if token.string and token.string.strip():
                     indent_chars.add(token.string[0])
                     has_indent = True
                elif token.string: # Check if token.string is just whitespace (e.g. newline indent)
                     pass # Ignore indent tokens that are just newlines/empty

        # Mixed indentation only makes sense if there *is* indentation
        mixed_indentation = len(indent_chars) > 1 if has_indent else False
        self.results["metrics"]["mixed_indentation"] = mixed_indentation

        # Scoring Logic
        score = 0
        justification = []

        # Adjust scoring slightly based on LOC, as 0 errors in 2 lines means less than in 50 lines
        loc_factor = max(1, self.loc / 20.0) # Scale impact slightly with code size

        if error_count == 0 and self.loc > 3: # Require a few lines for 'perfect' to mean much
            score += 10 * loc_factor # Max 15-20 for larger snippets
            justification.append("Code appears perfectly PEP-8 compliant, often seen in AI output.")
        # Increase threshold for 'high violation density' penalty
        elif error_count > 5 or (self.loc > 0 and error_count / self.loc > 0.15): # High violation density or > 5 absolute
            score -= 15
            justification.append(f"Found {error_count} PEP-8 violations, suggesting less strict human formatting.")
            self.results["pattern_analysis"].append("Multiple PEP-8 style violations.")
        elif error_count > 0:
            score -= 5 # Minor penalty for few errors
            justification.append(f"Found {error_count} minor PEP-8 violations.")


        if mixed_indentation:
            score -= 20 # Strong human indicator (or copy-paste issue)
            justification.append("Mixed indentation (tabs and spaces) detected, highly indicative of human editing or problematic copy-pasting.")
            self.results["pattern_analysis"].append("Mixed indentation found.")

        # Check blank line usage (simple heuristic)
        # Count sequences of 2 or more newlines
        blank_line_sequences = len(re.findall(r'\n\s*\n', self.code))
        # AI often uses PEP-8 standard 1 blank line between functions, 2 between classes
        # Humans might be less consistent. Hard to quantify reliably without AST context.
        # Example: Excessive blank lines?
        if self.loc > 0 and blank_line_sequences / self.loc > 0.15: # More than 15% blank line sequences seems high
             score -= 5
             justification.append("Relatively high number of blank lines detected, potentially human formatting variation.")

        self.results["scores"]["formatting"] = min(max(score, -30), 30) # Cap the score impact
        self.results["detailed_justification"].extend(justification)

    def analyze_naming(self):
        """Analyzes variable and function naming conventions."""
        if not self.tree: return

        names = []
        name_lengths = []
        short_names = 0
        dict_word_names = 0
        non_snake_case = 0
        total_vars_funcs = 0

        for node in ast.walk(self.tree):
            name_to_check = None
            is_var = False
            is_func_or_class = False

            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param)):
                name_to_check = node.id
                is_var = True
            elif isinstance(node, ast.FunctionDef):
                name_to_check = node.name
                is_func_or_class = True
            elif isinstance(node, ast.ClassDef):
                 name_to_check = node.name
                 is_func_or_class = True
            elif isinstance(node, ast.arg): # Function arguments
                name_to_check = node.arg
                is_var = True

            if name_to_check:
                # Ignore typical private/magic methods/vars for convention checks
                if name_to_check.startswith('_'):
                    continue

                total_vars_funcs +=1
                names.append(name_to_check)
                name_lengths.append(len(name_to_check))

                if len(name_to_check) <= 2 and name_to_check not in {'id', 'io', 'ip'}: # Common short names ok
                    short_names += 1

                # Check if parts are dictionary words (simple split by _)
                parts = name_to_check.split('_')
                is_dict_word = all(part.lower() in COMMON_ENGLISH_WORDS or part.isdigit() for part in parts if part)
                if is_dict_word and len(parts) > 0 : # Make sure it's not just '_'
                    dict_word_names += 1

                # Check for snake_case (allow digits) vs camelCase/PascalCase
                if not re.fullmatch(r'[a-z0-9_]+', name_to_check) and re.search(r'[A-Z]', name_to_check):
                    # It's not pure snake_case and contains an uppercase letter
                     if is_var or is_func_or_class: # Classes are PascalCase, functions/vars snake_case per PEP8
                         if is_var or (is_func_or_class and isinstance(node, ast.FunctionDef)):
                             non_snake_case += 1


        num_names = len(names)
        self.results["metrics"]["names_analyzed"] = num_names
        if num_names == 0: return

        avg_name_length = sum(name_lengths) / num_names
        short_name_ratio = short_names / num_names
        dict_word_ratio = dict_word_names / num_names
        non_snake_case_ratio = non_snake_case / total_vars_funcs if total_vars_funcs > 0 else 0

        self.results["metrics"]["avg_name_length"] = avg_name_length
        self.results["metrics"]["short_name_ratio"] = short_name_ratio
        self.results["metrics"]["dict_word_ratio"] = dict_word_ratio
        self.results["metrics"]["non_snake_case_ratio"] = non_snake_case_ratio

        # Scoring logic
        score = 0
        justification = []

        if avg_name_length > 10:
            score += 15
            justification.append("Average variable/function name length is high (>10), suggesting verbose, descriptive names (AI-like).")
        elif avg_name_length < 5 and num_names > 3:
            score -= 10
            justification.append("Average name length is short (<5), often seen in human code (e.g., i, j, x, tmp).")

        if dict_word_ratio > 0.8 and num_names > 3:
            score += 10
            justification.append("High ratio (>80%) of names composed of dictionary words, typical for AI's clean naming.")
        elif dict_word_ratio < 0.4 and num_names > 3:
            score -= 5
            justification.append("Lower ratio (<40%) of dictionary word names, suggesting more arbitrary or context-specific human naming.")

        if short_name_ratio > 0.3 and num_names > 5: # More than 30% short names
            score -= 15
            justification.append("High proportion (>30%) of short variable names (<=2 chars), common in human scripting/contests.")
            self.results["pattern_analysis"].append("Frequent use of short variable names (e.g., i, j, x).")

        if non_snake_case_ratio > 0.1: # More than 10% violating snake_case for vars/funcs
            score -= 10
            justification.append("Inconsistent casing (e.g., camelCase for variables/functions) detected, less common for strict AI adherence to PEP-8.")
            self.results["pattern_analysis"].append("Inconsistent naming conventions (non-snake_case found).")
        elif num_names > 3 and non_snake_case_ratio == 0:
             score += 5 # Slight bonus for perfect consistency
             justification.append("Naming conventions consistently follow PEP-8 (snake_case), common for AI.")


        self.results["scores"]["naming"] = score
        self.results["detailed_justification"].extend(justification)

    def analyze_complexity_optimality(self):
        """Analyzes code complexity and potential inefficiencies."""
        if not self.tree or not self.code: return

        # Cyclomatic Complexity (requires radon)
        cyclo_complexity = 0
        avg_complexity = 0
        max_complexity = 0
        if RADON_AVAILABLE:
            try:
                visitor = ComplexityVisitor.from_code(self.code)
                funcs = visitor.functions + visitor.classes # Treat classes similarly for complexity blocks
                if funcs:
                    complexities = [f.complexity for f in funcs]
                    total_complexity = sum(complexities)
                    avg_complexity = total_complexity / len(funcs) if funcs else 0
                    max_complexity = max(complexities) if funcs else 0
                    self.results["metrics"]["avg_complexity"] = avg_complexity
                    self.results["metrics"]["max_complexity"] = max_complexity
                else:
                     # Calculate complexity for the whole block if no functions/classes
                     block_complexity = visitor.complexity # Radon gives total complexity here
                     self.results["metrics"]["block_complexity"] = block_complexity
                     avg_complexity = block_complexity # Treat block as one unit
                     max_complexity = block_complexity

            except Exception as e:
                self.results["pattern_analysis"].append(f"Radon complexity analysis failed: {e}")
        else:
            self.results["pattern_analysis"].append("Complexity analysis limited: radon library not found.")
            # Basic heuristic: nested loops
            nested_loop_depth = 0
            for node in ast.walk(self.tree):
                 if isinstance(node, (ast.For, ast.While)):
                      current_depth = 1
                      parent = getattr(node, 'parent', None) # Need parent pointers for accurate depth
                      while parent: # This requires enhancing AST with parent pointers or a different traversal
                          if isinstance(parent, (ast.For, ast.While)):
                               current_depth += 1
                          parent = getattr(parent, 'parent', None)
                      nested_loop_depth = max(nested_loop_depth, current_depth)
            # This basic AST walk doesn't track depth easily. A dedicated visitor is better.
            # Simple approximation: Count total loops
            loop_count = sum(1 for node in ast.walk(self.tree) if isinstance(node, (ast.For, ast.While)))
            self.results["metrics"]["loop_count"] = loop_count
            if loop_count > 2 and self.loc < 30: # Many loops in short code?
                 avg_complexity = 5 # Assign arbitrary moderate complexity if many loops

        # Basic check for redundant operations (very simplistic)
        # Example: consecutive identical assignments? Hard to do robustly.
        redundancy_hints = 0
        # Example: multiple simple loops that could be combined. Requires deeper analysis.

        # Magic numbers (numeric literals not part of assignments/defaults)
        magic_numbers = 0
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                # Check if it's directly used in expressions, not assignments or function defaults
                 # Requires parent tracking or more context. Simplification: count all numeric constants.
                 # This is noisy, but maybe captures some cases.
                 is_assigned = False
                 # Crude check: is it the value part of an assignment or default arg?
                 # Need parent pointer for reliability. Skip for now.

        # Scoring logic
        score = 0
        justification = []

        # Use LOC as a rough proxy for problem complexity
        complexity_threshold = 5 + self.loc / 10 # Very rough baseline

        if avg_complexity > 0 and avg_complexity < complexity_threshold * 0.75 and self.loc > 10:
             # Low complexity for non-trivial code size *might* indicate straightforward AI generation
             score += 5
             justification.append(f"Code complexity (avg: {avg_complexity:.1f}) seems relatively low for its size, possibly simple AI structure.")
        elif avg_complexity > complexity_threshold * 1.5:
             # High complexity might be human (complex logic) or AI (overly complex generation) - less clear signal
             score -= 5 # Slight bias towards human for very complex parts
             justification.append(f"Code complexity (avg: {avg_complexity:.1f}) is relatively high.")
             self.results["pattern_analysis"].append("High cyclomatic complexity detected in parts.")
        elif avg_complexity == 0 and self.loc > 5:
            # No measurable complexity blocks (e.g., straight script)
             pass # Neutral

        if max_complexity > 15:
             score -= 10 # Very complex functions/blocks might be human struggle
             justification.append(f"Detected at least one highly complex block (max complexity: {max_complexity}), potentially human-written complex logic.")


        # If redundancy checks were implemented:
        # if redundancy_hints > 0:
        #    score -= 10
        #    justification.append("Detected potential redundancies or inefficiencies, possibly human.")

        self.results["scores"]["complexity"] = score
        self.results["detailed_justification"].extend(justification)

    def analyze_advanced_constructs(self):
        """Analyzes the use of list comprehensions, lambdas, map/filter, decorators."""
        if not self.tree: return

        constructs = {
            "list_comp": 0, "set_comp": 0, "dict_comp": 0, "gen_exp": 0,
            "lambda": 0, "map": 0, "filter": 0, "reduce": 0, # reduce needs import functools
            "decorator": 0
        }
        function_calls = defaultdict(int)

        for node in ast.walk(self.tree):
            if isinstance(node, ast.ListComp): constructs["list_comp"] += 1
            elif isinstance(node, ast.SetComp): constructs["set_comp"] += 1
            elif isinstance(node, ast.DictComp): constructs["dict_comp"] += 1
            elif isinstance(node, ast.GeneratorExp): constructs["gen_exp"] += 1
            elif isinstance(node, ast.Lambda): constructs["lambda"] += 1
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    function_calls[func_name] += 1
                    if func_name == "map": constructs["map"] += 1
                    elif func_name == "filter": constructs["filter"] += 1
                    elif func_name == "reduce": constructs["reduce"] += 1
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                 if node.decorator_list:
                     constructs["decorator"] += len(node.decorator_list)

        self.results["metrics"]["advanced_constructs"] = constructs
        total_advanced = sum(constructs.values())

        # Scoring logic
        score = 0
        justification = []

        # Heuristic: Usage relative to code size. More advanced constructs in shorter code = more suspicious.
        adv_ratio = total_advanced / self.loc if self.loc > 0 else 0
        self.results["metrics"]["advanced_construct_ratio"] = adv_ratio

        if adv_ratio > 0.1 and self.loc < 50: # High density in short code
            score += 15
            justification.append("Frequent use of advanced constructs (comprehensions, lambda, map/filter) relative to code size, potentially AI.")
            self.results["pattern_analysis"].append("High density of advanced Python constructs.")
        elif total_advanced > 5: # Significant absolute number
             score += 10
             justification.append(f"Used {total_advanced} advanced constructs, common for AI leveraging language features.")
        elif total_advanced == 0 and self.loc > 20:
             score -= 10
             justification.append("No significant use of advanced constructs found in non-trivial code, leans human (simpler style).")

        # Specific checks for potentially unnecessary use (hard to be certain)
        # Example: A list comprehension that is trivially replaceable by a simple loop
        # Example: Lambda used for a very simple operation passed to map/filter
        # Requires analyzing the *content* of these constructs, significantly harder.
        # Simple heuristic: if list comp body is just appending a simple expression.

        if constructs["lambda"] > 2:
             score += 5 # Multiple lambdas might suggest functional style AI likes
             justification.append("Multiple lambda functions used.")
        if constructs["decorator"] > 0:
             # Decorators often imply more structured code, could be AI or experienced human
             score += 5
             justification.append("Use of decorators detected.")


        self.results["scores"]["advanced_constructs"] = score
        self.results["detailed_justification"].extend(justification)

    def analyze_patterns_structure(self):
        """Analyzes repetitive patterns, unusual structures, and completion."""
        if not self.code: return

        # Check for debugging prints (especially commented out)
        print_count = 0
        commented_print_count = 0
        for line in self.lines:
            stripped_line = line.strip()
            if stripped_line.startswith("print("):
                print_count += 1
            elif stripped_line.startswith("#") and "print(" in stripped_line:
                 # Basic check, could be more robust with regex
                 if re.search(r'#\s*print\(', stripped_line):
                    commented_print_count += 1

        self.results["metrics"]["print_statements"] = print_count
        self.results["metrics"]["commented_print_statements"] = commented_print_count

        # Check for placeholders like 'pass' or '# TODO: Implement'
        pass_count = sum(1 for node in ast.walk(self.tree) if isinstance(node, ast.Pass)) if self.tree else 0
        # TODOs already checked in comments, but explicit pass is structural

        self.results["metrics"]["pass_statements"] = pass_count

        # Check for docstrings (AI often generates them)
        docstring_count = 0
        functions_classes = 0
        if self.tree:
            for node in ast.walk(self.tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        functions_classes += 1
                    docstring = ast.get_docstring(node, clean=False)
                    if docstring:
                        docstring_count += 1

        self.results["metrics"]["docstring_count"] = docstring_count
        self.results["metrics"]["functions_classes_count"] = functions_classes
        docstring_coverage = docstring_count / functions_classes if functions_classes > 0 else 0
        # Module docstring check (often added by AI)
        has_module_docstring = bool(self.tree and ast.get_docstring(self.tree)) if self.tree else False
        self.results["metrics"]["has_module_docstring"] = has_module_docstring


        # Check for large commented-out blocks (human experimentation)
        large_commented_blocks = 0
        in_block = False
        current_block_len = 0
        for line in self.lines:
            if line.strip().startswith("#"):
                if not in_block:
                    in_block = True
                    current_block_len = 1
                else:
                    current_block_len += 1
            else:
                if in_block and current_block_len > 3: # Block of 4+ commented lines
                    large_commented_blocks += 1
                in_block = False
                current_block_len = 0
        if in_block and current_block_len > 3: # Check trailing block
            large_commented_blocks += 1

        self.results["metrics"]["large_commented_blocks"] = large_commented_blocks

        # Scoring logic
        score = 0
        justification = []

        if commented_print_count > 0:
            score -= 25 # Strong human indicator
            justification.append(f"Found {commented_print_count} commented-out print statements, strong indicator of human debugging.")
            self.results["pattern_analysis"].append("Presence of commented-out debug prints.")
        elif print_count > 2 and self.loc < 50 : # Lots of active prints in short code? Maybe dev testing
             score -= 5
             justification.append("Multiple active print statements found, possibly human debugging/testing.")

        if pass_count > 1:
            score -= 10
            justification.append(f"Found {pass_count} 'pass' statements, suggesting placeholders during human development.")
            self.results["pattern_analysis"].append("Use of 'pass' statement as placeholder.")

        if large_commented_blocks > 0:
             score -= 20
             justification.append(f"Detected {large_commented_blocks} large commented-out code blocks, likely human experimentation.")
             self.results["pattern_analysis"].append("Large commented-out code blocks found.")

        if functions_classes > 0:
             if docstring_coverage > 0.8 or (has_module_docstring and functions_classes == 0): # High coverage or module docstring on script
                 score += 15
                 justification.append("High docstring coverage or presence of module docstring, common in AI-generated code.")
             elif docstring_coverage < 0.2 and functions_classes > 2 : # Low coverage on multiple items
                 score -= 10
                 justification.append("Low docstring coverage for functions/classes, more typical of human contest code.")

        # Structure check: Does it look like a direct answer? (Hard to quantify)
        # If code defines only one or two functions and maybe a simple call at the end,
        # it might resemble a prompt response.
        if self.tree and len(self.tree.body) > 0:
            top_level_nodes = [type(n) for n in self.tree.body]
            is_simple_script = all(t in (ast.FunctionDef, ast.Import, ast.ImportFrom, ast.Expr, ast.Assign, ast.If, ast.ClassDef) for t in top_level_nodes)
            num_func_defs = top_level_nodes.count(ast.FunctionDef)
            num_class_defs = top_level_nodes.count(ast.ClassDef)

            if is_simple_script and (num_func_defs + num_class_defs) <= 2 and self.loc < 60:
                 score += 5 # Slight increase, weak indicator
                 justification.append("Structure appears simple (few top-level functions/classes), potentially direct AI response to prompt.")

        self.results["scores"]["patterns_structure"] = score
        self.results["detailed_justification"].extend(justification)


    # --- Aggregation ---

    def calculate_suspicion(self):
        """Calculates the final suspicious percentage based on weighted scores."""

        # Define weights for each factor (TUNE THESE BASED ON OBSERVATIONS)
        weights = {
            "comments": 1.0,
            "formatting": 1.2, # PEP8 adherence is a decent signal
            "naming": 1.5,     # Naming conventions are often revealing
            "complexity": 0.8, # Complexity can be ambiguous
            "advanced_constructs": 1.1,
            "patterns_structure": 1.8, # Debug prints, comments, placeholders are strong signals
            "syntax_error": 1.0 # Handled as a large negative score directly
        }

        # Base score (start from neutral 50%)
        final_score = 50.0

        for factor, score in self.results["scores"].items():
            weight = weights.get(factor, 1.0)
            final_score += score * weight

        # Clamp score between 0 and 100
        final_score = max(0, min(100, final_score))

        self.results["suspicious_percentage"] = round(final_score, 2)

        # Add overall assessment to justification
        if final_score > 75:
            assessment = "Overall Assessment: High likelihood of AI generation based on multiple strong indicators."
        elif final_score > 55:
            assessment = "Overall Assessment: Moderate likelihood of AI generation. Some AI-like traits detected."
        elif final_score > 45:
             assessment = "Overall Assessment: Ambiguous. Mix of human-like and AI-like traits or insufficient evidence."
        elif final_score > 25:
             assessment = "Overall Assessment: Moderate likelihood of human authorship. Some human-like traits detected."
        else:
            assessment = "Overall Assessment: High likelihood of human authorship based on multiple strong indicators."

        self.results["detailed_justification"].insert(0, assessment) # Add to beginning


    def analyze(self):
        """Runs all analysis steps and returns the results."""
        if not self.code:
             self.results["detailed_justification"].append("Input code snippet is empty.")
             self.results["suspicious_percentage"] = 0 # Or handle as error?
             return self.get_results_json()

        # Run analysis components
        self.analyze_comments()
        self.analyze_formatting()
        self.analyze_naming()
        self.analyze_complexity_optimality()
        self.analyze_advanced_constructs()
        self.analyze_patterns_structure() # Includes syntax error check effect via score

        # Calculate final score
        self.calculate_suspicion()

        # Consolidate pattern analysis list (remove duplicates)
        self.results["pattern_analysis"] = sorted(list(set(self.results["pattern_analysis"])))

        return self.get_results_json()

    def get_results_json(self):
        """Returns the analysis results formatted as a JSON string."""
        output = {
            "suspicious_percentage": self.results["suspicious_percentage"],
            "detailed_justification": "\n".join(self.results["detailed_justification"]),
            "pattern_analysis": self.results["pattern_analysis"],
            # Optional: include raw metrics for debugging/transparency
            # "metrics": self.results["metrics"]
        }
        return json.dumps(output, indent=4)



if __name__ == "__main__":
    
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing object_id argument"}))
        sys.exit(1)

    document_id = sys.argv[1]  # Get object_id from command line argument

    doc_content = fetch_document_by_id(document_id)
    if doc_content:
        analysis_result = CodeAnalyzer(doc_content['code']).analyze()

        if analysis_result:
           
            # json_output = json.dumps(analysis_result, indent=4, default=str)
            print(analysis_result)
        else:
            print("Analysis could not be performed on the document.")



