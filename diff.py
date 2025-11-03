# buildtrace-service/diff.py - FINAL WORKING VERSION (Fixes Crash and Schema)

import json
from google.cloud import storage, bigquery
from typing import Dict, Any, List

# Initialize GCP clients
STORAGE_CLIENT = storage.Client()
BIGQUERY_CLIENT = bigquery.Client()

# --- Helper Functions for GCS Retrieval ---

def load_full_job_data(job_id: int, bucket_name: str, client: storage.Client) -> dict:
    """Loads the entire job submission dictionary (including metadata) from GCS."""
    blob_name = f"job_state/{job_id}.json"
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        if blob.exists():
            return json.loads(blob.download_as_text()) # RETURN THE FULL DICT
        return {}
    except Exception as e:
        print(f"CRITICAL: Failed to load data for Job {job_id} from GCS: {e}")
        raise

def get_state_map(job_data: dict) -> dict:
    """Safely extracts the state map ({file: hash}) from the full job dictionary."""
    return job_data.get('state', {})

# --- Helper Functions for Qualitative Analysis ---

def parse_hash(hash_string: str) -> dict:
    """Parses pseudo-hash 'type_x_y_w_h' back into coordinates and type."""
    try:
        parts = hash_string.split('_')
        return {
            'type': parts[0],
            'x': int(parts[1]),
            'y': int(parts[2]),
        }
    except Exception:
        return {'type': 'unknown', 'x': 0, 'y': 0}

def get_movement_description(prev_hash: str, curr_hash: str, obj_id: str) -> str:
    """Calculates directional movement between two states."""
    prev = parse_hash(prev_hash)
    curr = parse_hash(curr_hash)
    
    dx = curr['x'] - prev['x']
    dy = curr['y'] - prev['y']
    
    if dx == 0 and dy == 0:
        return f"{obj_id} attributes modified (not position)."

    direction = []
    if dx > 0: direction.append(f"{abs(dx)} units east")
    elif dx < 0: direction.append(f"{abs(dx)} units west")
    
    if dy > 0: direction.append(f"{abs(dy)} units north")
    elif dy < 0: direction.append(f"{abs(dy)} units south")
        
    movement_desc = " and ".join(direction) if direction else "slightly adjusted position"
    return f"{obj_id} ({prev['type']}) moved {movement_desc}"

# --- Main Worker Function ---

def process_job(job_id: int, bucket_name: str, dataset_id: str, table_id: str) -> dict:
    """
    Performs core diff, returns descriptive report, AND logs metrics to BigQuery.
    """
    # Safely convert job_id
    try:
        current_job_id = int(job_id)
        previous_job_id = current_job_id - 1
    except (TypeError, ValueError):
        raise ValueError("Invalid job_id received.")

    # 1. Fetch Job Data (Fixes the crash by loading the full file first)
    current_job_data = load_full_job_data(current_job_id, bucket_name, STORAGE_CLIENT)
    
    # CRITICAL CHECK: Raises the 404 error if file is missing
    if not current_job_data:
        raise ValueError(f"Current state for Job {current_job_id} is empty.") 
    
    # Extract metadata and state map
    current_state = get_state_map(current_job_data)
    timestamp = current_job_data.get('timestamp')
    latency_ms = current_job_data.get('latency_ms')

    # 2. Fetch Previous State
    previous_job_data = load_full_job_data(previous_job_id, bucket_name, STORAGE_CLIENT)
    previous_state = get_state_map(previous_job_data)
    
    # 3. Analyze Changes (Qualitative Data)
    current_files = set(current_state.keys())
    previous_files = set(previous_state.keys())
    
    added = []
    removed = []
    modified_moved = []
    unchanged_count = 0
    
    total_added = len(current_files - previous_files)
    total_removed = len(previous_files - current_files)
    
    # Build the descriptive lists
    for file_path in (current_files - previous_files):
        curr = parse_hash(current_state[file_path])
        added.append(f"{file_path} ({curr['type']} added at x:{curr['x']}, y:{curr['y']})")

    for file_path in (previous_files - current_files):
        removed.append(f"{file_path} removed")

    for file_path in (current_files & previous_files):
        prev_hash = previous_state[file_path]
        curr_hash = current_state[file_path]
        
        if curr_hash != prev_hash:
            move_desc = get_movement_description(prev_hash, curr_hash, file_path)
            modified_moved.append(move_desc)
        else:
            unchanged_count += 1
            
    # 4. BigQuery Insertion (Quantitative Metrics)
    metrics = {
        "timestamp": timestamp,
        "job_id": str(current_job_id), 
        "latency_ms": latency_ms,
        "total_added": total_added,
        "total_removed": total_removed,
        "total_modified": len(modified_moved), # Total moved/modified items
        "total_unchanged": unchanged_count
    }
    
    try:
        table_ref = BIGQUERY_CLIENT.dataset(dataset_id).table(table_id)
        errors = BIGQUERY_CLIENT.insert_rows_json(table_ref, [metrics])
        if errors:
            print(f"CRITICAL: BQ Insertion Errors: {errors}")
            # Allow report generation but log the BQ failure
    except Exception as e:
        print(f"CRITICAL: BigQuery client error: {e}")
        
    # 5. Generate and Return Descriptive Report
    summary_parts = []
    if added: summary_parts.append(f"{len(added)} item(s) added.")
    if removed: summary_parts.append(f"{len(removed)} item(s) removed.")
    if modified_moved: summary_parts.append(f"{len(modified_moved)} item(s) moved/modified.")
    
    final_summary = " | ".join(summary_parts) if summary_parts else "No significant changes detected."
    
    return {
        "job_id": current_job_id,
        "added": added,
        "removed": removed,
        "moved_or_modified": modified_moved,
        "summary": final_summary,
        "metrics_status": "BigQuery insertion attempted."
    }
