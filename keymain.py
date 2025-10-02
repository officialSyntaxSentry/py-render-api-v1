from pymongo import MongoClient
from bson.objectid import ObjectId
import json
from datetime import datetime
import math
import logging
from collections import deque


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

# Thresholds (These are crucial and likely need tuning based on real-world data)
# Time difference between consecutive keys considered "very fast" (milliseconds)
FAST_TYPING_THRESHOLD_MS = 50
# Time difference between consecutive keys considered a "long gap" (milliseconds)
LONG_GAP_THRESHOLD_MS = 15000  # 15 seconds
# Time difference between 'Control' and 'v' to be considered a rapid paste (milliseconds)
RAPID_PASTE_CTRL_V_THRESHOLD_MS = 300
# Time difference between consecutive paste actions ('v' key following 'Control')
# to be considered "multiple rapid pastes" (milliseconds)
CONSECUTIVE_PASTE_THRESHOLD_MS = 1000 # 1 second
# Minimum number of key logs required to perform meaningful analysis
MIN_KEYLOGS_FOR_ANALYSIS = 10
# Minimum number of keys considered a "burst" potentially indicating pasted content
PASTE_BURST_MIN_KEYS = 5
# Maximum IKI within a burst (milliseconds)
PASTE_BURST_MAX_IKI_MS = 70


# Scoring Weights (Total should ideally map to 100 for percentage)
WEIGHT_RAPID_PASTE = 40           # High impact for detected Ctrl+V
WEIGHT_MULTIPLE_RAPID_PASTE = 25  # Additional impact for consecutive pastes
WEIGHT_EXTREME_FAST_TYPING = 25   # High percentage of very fast IKIs
WEIGHT_LONG_GAPS = 10             # Moderate impact for excessive pauses

# Maximum score contribution for each category (to prevent one factor dominating excessively)
MAX_SCORE_RAPID_PASTE = 50
MAX_SCORE_MULTIPLE_RAPID_PASTE = 30
MAX_SCORE_EXTREME_FAST_TYPING = 40
MAX_SCORE_LONG_GAPS = 20

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

def calculate_inter_key_intervals(key_logs):
    """
    Calculates the time differences between consecutive key presses.

    Args:
        key_logs (list): A list of key log dictionaries, sorted by timestamp.

    Returns:
        list: A list of inter-key intervals in milliseconds.
              Returns an empty list if fewer than 2 key logs are provided.
    """
    if not key_logs or len(key_logs) < 2:
        return []

    ikis = []
    for i in range(1, len(key_logs)):
        # Ensure timestamps are valid numbers
        try:
            prev_ts = float(key_logs[i-1]['timestamp'])
            curr_ts = float(key_logs[i]['timestamp'])
            # Ensure time flows forward
            if curr_ts >= prev_ts:
                 ikis.append(curr_ts - prev_ts)
            else:
                logging.warning(f"Non-monotonic timestamp detected: {prev_ts} -> {curr_ts}. Skipping interval calculation.")
                # Handle potentially out-of-order logs - decide whether to skip, use abs(), or raise error
                # Skipping is often safest if data quality is uncertain
                ikis.append(None) # Add a placeholder or skip
        except (TypeError, ValueError, KeyError) as e:
            logging.error(f"Error processing timestamp: {e}. Keylog: {key_logs[i]}")
            ikis.append(None) # Add a placeholder

    # Filter out None values added due to errors or non-monotonic timestamps
    return [iki for iki in ikis if iki is not None]


# --- Main Analysis Class ---

class SuspiciousBehaviorDetector:
    """
    Analyzes keylogging data from a document to detect suspicious patterns
    indicative of cheating, such as rapid copy-pasting, unnaturally fast typing,
    and unusually long pauses.
    """

    def __init__(self, config=None):
        """
        Initializes the detector with configurable thresholds and weights.

        Args:
            config (dict, optional): A dictionary overriding default configuration.
                                     Keys should match the global configuration names.
                                     Defaults to None, using global settings.
        """
        self.config = {
            'FAST_TYPING_THRESHOLD_MS': FAST_TYPING_THRESHOLD_MS,
            'LONG_GAP_THRESHOLD_MS': LONG_GAP_THRESHOLD_MS,
            'RAPID_PASTE_CTRL_V_THRESHOLD_MS': RAPID_PASTE_CTRL_V_THRESHOLD_MS,
            'CONSECUTIVE_PASTE_THRESHOLD_MS': CONSECUTIVE_PASTE_THRESHOLD_MS,
            'MIN_KEYLOGS_FOR_ANALYSIS': MIN_KEYLOGS_FOR_ANALYSIS,
            'PASTE_BURST_MIN_KEYS': PASTE_BURST_MIN_KEYS,
            'PASTE_BURST_MAX_IKI_MS': PASTE_BURST_MAX_IKI_MS,
            'WEIGHT_RAPID_PASTE': WEIGHT_RAPID_PASTE,
            'WEIGHT_MULTIPLE_RAPID_PASTE': WEIGHT_MULTIPLE_RAPID_PASTE,
            'WEIGHT_EXTREME_FAST_TYPING': WEIGHT_EXTREME_FAST_TYPING,
            'WEIGHT_LONG_GAPS': WEIGHT_LONG_GAPS,
            'MAX_SCORE_RAPID_PASTE': MAX_SCORE_RAPID_PASTE,
            'MAX_SCORE_MULTIPLE_RAPID_PASTE': MAX_SCORE_MULTIPLE_RAPID_PASTE,
            'MAX_SCORE_EXTREME_FAST_TYPING': MAX_SCORE_EXTREME_FAST_TYPING,
            'MAX_SCORE_LONG_GAPS': MAX_SCORE_LONG_GAPS,
        }
        if config:
            self.config.update(config)
        logging.info(f"Detector initialized with config: {self.config}")

    def _detect_rapid_paste(self, key_logs):
        """
        Detects instances of rapid Ctrl+V sequences and consecutive pastes.

        Note: This assumes 'Control' and 'v' keys are logged explicitly.
              Accuracy depends heavily on how the keylogger records modifier keys.
              It also looks for bursts of fast typing as potential paste indicators.

        Args:
            key_logs (list): Sorted list of key log dictionaries.

        Returns:
            tuple: (
                list of timestamps where rapid Ctrl+V was detected,
                list of timestamps where potential paste bursts were detected
            )
        """
        rapid_paste_timestamps = []
        paste_burst_timestamps = []
        last_paste_time = -float('inf')
        control_pressed_time = None
        recent_keys = deque(maxlen=self.config['PASTE_BURST_MIN_KEYS']) # Track recent keys for burst detection

        for i in range(len(key_logs)):
            log = key_logs[i]
            key = log.get('key', '').lower() # Case-insensitive check
            timestamp = log.get('timestamp')

            if timestamp is None:
                logging.warning(f"Skipping log due to missing timestamp: {log}")
                continue

            try:
                timestamp = float(timestamp)
            except (ValueError, TypeError):
                logging.warning(f"Skipping log due to invalid timestamp format: {log}")
                continue

            # --- Ctrl+V Detection ---
            # Check if 'Control' was pressed recently
            if key == 'control': # Assuming 'control' is the logged key name
                control_pressed_time = timestamp
            elif key == 'v' and control_pressed_time is not None:
                time_diff = timestamp - control_pressed_time
                if 0 < time_diff <= self.config['RAPID_PASTE_CTRL_V_THRESHOLD_MS']:
                    logging.debug(f"Potential Ctrl+V detected at {timestamp} (diff: {time_diff}ms)")
                    rapid_paste_timestamps.append(timestamp)
                    # Reset control time after 'v' press to avoid re-triggering immediately
                    control_pressed_time = None
            elif key != 'control': # Any other key press resets the Control state
                 control_pressed_time = None


            # --- Paste Burst Detection ---
            # Look for a sequence of keys typed very quickly
            recent_keys.append(log)
            if len(recent_keys) == self.config['PASTE_BURST_MIN_KEYS']:
                is_burst = True
                burst_start_time = float(recent_keys[0]['timestamp'])
                for k in range(1, len(recent_keys)):
                    prev_ts_burst = float(recent_keys[k-1]['timestamp'])
                    curr_ts_burst = float(recent_keys[k]['timestamp'])
                    iki_burst = curr_ts_burst - prev_ts_burst
                    if iki_burst > self.config['PASTE_BURST_MAX_IKI_MS'] or iki_burst < 0:
                        is_burst = False
                        break
                if is_burst:
                    # Check if this burst follows a significant pause or is distinct
                    # Find IKI *before* the burst starts
                    iki_before_burst = float('inf')
                    if i >= self.config['PASTE_BURST_MIN_KEYS']:
                        try:
                            ts_before_burst = float(key_logs[i - self.config['PASTE_BURST_MIN_KEYS']]['timestamp'])
                            iki_before_burst = burst_start_time - ts_before_burst
                        except (IndexError, ValueError, TypeError, KeyError):
                            pass # Can happen at the very beginning or with bad data

                    # Consider it a potential paste burst if it's fast internally
                    # and possibly follows a pause (optional refinement: check iki_before_burst > threshold)
                    logging.debug(f"Potential paste burst detected ending at {timestamp} (started {burst_start_time})")
                    paste_burst_timestamps.append(timestamp) # Log end time of the burst

        return rapid_paste_timestamps, paste_burst_timestamps


    def _analyze_typing_speed(self, ikis):
        """
        Analyzes inter-key intervals for extremely fast typing and long gaps.

        Args:
            ikis (list): List of inter-key intervals in milliseconds.

        Returns:
            tuple: (
                percentage of IKIs below FAST_TYPING_THRESHOLD_MS,
                percentage of IKIs above LONG_GAP_THRESHOLD_MS
            )
        """
        if not ikis:
            return 0.0, 0.0

        fast_count = sum(1 for iki in ikis if 0 <= iki < self.config['FAST_TYPING_THRESHOLD_MS'])
        long_gap_count = sum(1 for iki in ikis if iki > self.config['LONG_GAP_THRESHOLD_MS'])

        total_ikis = len(ikis)
        fast_percentage = (fast_count / total_ikis) * 100
        long_gap_percentage = (long_gap_count / total_ikis) * 100

        return fast_percentage, long_gap_percentage

    def analyze(self, document):
        """
        Performs the full analysis on a given document.

        Args:
            document (dict): The input document containing keylogging data.

        Returns:
            dict: A dictionary containing the analysis results:
                  'suspicious_percentage': Overall score (0-100).
                  'details': A dictionary with scores and counts for each detected behavior.
                  'error': An error message if analysis could not be performed, None otherwise.
        """
        analysis_results = {
            'suspicious_percentage': 0.0,
            'details': {
                'total_key_presses': 0,
                'analyzed_intervals': 0,
                'rapid_paste_ctrl_v_count': 0,
                'rapid_paste_ctrl_v_timestamps': [],
                'multiple_rapid_paste_sequences': 0,
                'paste_burst_count': 0,
                'paste_burst_timestamps': [],
                'fast_typing_percentage': 0.0,
                'long_gap_percentage': 0.0,
                'score_contribution': {
                    'rapid_paste': 0.0,
                    'multiple_rapid_paste': 0.0,
                    'fast_typing': 0.0,
                    'long_gaps': 0.0,
                }
            },
            'error': None
        }

        # --- Basic Validation ---
        if not isinstance(document, dict):
            analysis_results['error'] = "Invalid input: document is not a dictionary."
            logging.error(analysis_results['error'])
            return analysis_results

        key_logs = document.get('keyLogs')
        if not key_logs or not isinstance(key_logs, list):
            analysis_results['error'] = "Missing or invalid 'keyLogs' field in the document."
            # Don't log error here, might be expected for some events
            # logging.warning(analysis_results['error'])
            return analysis_results # Return 0% suspicion if no logs

        analysis_results['details']['total_key_presses'] = len(key_logs)

        if len(key_logs) < self.config['MIN_KEYLOGS_FOR_ANALYSIS']:
            analysis_results['error'] = f"Not enough key logs ({len(key_logs)}) for detailed analysis (minimum {self.config['MIN_KEYLOGS_FOR_ANALYSIS']})."
            # No suspicion score assigned for very short inputs
            return analysis_results

        # --- Preprocessing: Sort by timestamp ---
        try:
            # Ensure timestamps are valid numbers before sorting
            for log in key_logs:
                 log['timestamp'] = float(log['timestamp'])
            key_logs.sort(key=lambda x: x['timestamp'])
        except (ValueError, TypeError, KeyError) as e:
            analysis_results['error'] = f"Failed to sort key logs due to invalid timestamp data: {e}"
            logging.error(analysis_results['error'])
            return analysis_results

        # --- Calculate Inter-Key Intervals ---
        ikis = calculate_inter_key_intervals(key_logs)
        if not ikis:
             # Warning if calculation failed despite enough keylogs
            logging.warning(f"Could not calculate IKIs for document ID {document.get('_id', 'N/A')}")
            # Proceed with other checks if possible, but typing speed analysis won't work
        else:
            analysis_results['details']['analyzed_intervals'] = len(ikis)


        # --- Feature Detection ---
        total_suspicion_score = 0.0

        # 1. Detect Rapid Pastes (Ctrl+V and Bursts)
        try:
            rapid_paste_timestamps, paste_burst_timestamps = self._detect_rapid_paste(key_logs)
            analysis_results['details']['rapid_paste_ctrl_v_count'] = len(rapid_paste_timestamps)
            analysis_results['details']['rapid_paste_ctrl_v_timestamps'] = rapid_paste_timestamps
            analysis_results['details']['paste_burst_count'] = len(paste_burst_timestamps)
            analysis_results['details']['paste_burst_timestamps'] = paste_burst_timestamps

            # Score for individual Ctrl+V pastes
            paste_score = min(self.config['MAX_SCORE_RAPID_PASTE'],
                              len(rapid_paste_timestamps) * self.config['WEIGHT_RAPID_PASTE'])
            analysis_results['details']['score_contribution']['rapid_paste'] = paste_score
            total_suspicion_score += paste_score

            # Score for multiple *consecutive* Ctrl+V pastes
            multiple_paste_sequences = 0
            if len(rapid_paste_timestamps) > 1:
                for i in range(1, len(rapid_paste_timestamps)):
                    if (rapid_paste_timestamps[i] - rapid_paste_timestamps[i-1]) <= self.config['CONSECUTIVE_PASTE_THRESHOLD_MS']:
                        multiple_paste_sequences += 1
            analysis_results['details']['multiple_rapid_paste_sequences'] = multiple_paste_sequences
            multi_paste_score = min(self.config['MAX_SCORE_MULTIPLE_RAPID_PASTE'],
                                    multiple_paste_sequences * self.config['WEIGHT_MULTIPLE_RAPID_PASTE'])
            analysis_results['details']['score_contribution']['multiple_rapid_paste'] = multi_paste_score
            total_suspicion_score += multi_paste_score

            # Add score contribution from paste *bursts*? (Optional - could overlap with Ctrl+V)
            # Decide if bursts should add score independently or just be informational
            # Example: Add a smaller score for bursts if they don't coincide with Ctrl+V
            # burst_score = min(MAX_SCORE_BURST, len(paste_burst_timestamps) * WEIGHT_BURST)
            # total_suspicion_score += burst_score


        except Exception as e:
            logging.error(f"Error during paste detection: {e}", exc_info=True)
            analysis_results['error'] = "Error during paste detection."
            # Optionally add partial score or return error


        # 2. Analyze Typing Speed (Fast Typing & Long Gaps)
        if ikis: # Only if IKI calculation was successful
            try:
                fast_perc, long_gap_perc = self._analyze_typing_speed(ikis)
                analysis_results['details']['fast_typing_percentage'] = round(fast_perc, 2)
                analysis_results['details']['long_gap_percentage'] = round(long_gap_perc, 2)

                # Score for extremely fast typing
                # Scale the score based on the percentage, capped
                fast_typing_score = min(self.config['MAX_SCORE_EXTREME_FAST_TYPING'],
                                        (fast_perc / 100) * self.config['WEIGHT_EXTREME_FAST_TYPING'] * 2) # Scale factor can be adjusted
                analysis_results['details']['score_contribution']['fast_typing'] = fast_typing_score
                total_suspicion_score += fast_typing_score

                # Score for long gaps
                long_gap_score = min(self.config['MAX_SCORE_LONG_GAPS'],
                                     (long_gap_perc / 100) * self.config['WEIGHT_LONG_GAPS'] * 1.5) # Scale factor can be adjusted
                analysis_results['details']['score_contribution']['long_gaps'] = long_gap_score
                total_suspicion_score += long_gap_score

            except Exception as e:
                logging.error(f"Error during typing speed analysis: {e}", exc_info=True)
                analysis_results['error'] = "Error during typing speed analysis."
                # Optionally add partial score or return error


        # --- Final Score Calculation ---
        # Clamp the total score between 0 and 100
        final_percentage = max(0.0, min(100.0, round(total_suspicion_score, 2)))
        analysis_results['suspicious_percentage'] = final_percentage

        logging.info(f"Analysis complete for doc ID {document.get('_id', 'N/A')}. Suspicion: {final_percentage}%")
        logging.debug(f"Detailed scores: {analysis_results['details']['score_contribution']}")

        return analysis_results













if __name__ == "__main__":
    document_id = "67e198048ca3a3695a600c25"  # Replace with actual _id
    doc_cotent = fetch_document_by_id(document_id)

    detector = SuspiciousBehaviorDetector()

    # --- Analyze Documents ---
    print("--- Analyzing Normal Document ---")
    results_normal = detector.analyze(doc_cotent)
    print(json.dumps(results_normal, indent=2))
