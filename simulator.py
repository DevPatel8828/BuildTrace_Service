import json
import random
from faker import Faker
import time
import os

# --- CONFIGURATION ---
# GCS_BUCKET_NAME and PROJECT_ID are no longer needed
NUM_SEQUENTIAL_JOBS = 5 # Number of sequential jobs to generate
NUM_BASE_OBJECTS = 50

# --- INITIALIZE CLIENTS ---
# Only need the faker client
fake = Faker()

# --- UTILITY FUNCTIONS ---

def generate_base_object(obj_id, obj_type):
    """Generates a standard geometric object structure."""
    return {
        "id": obj_id,
        "type": obj_type,
        "x": random.randint(0, 100),
        "y": random.randint(0, 100),
        "width": random.randint(1, 10),
        "height": random.randint(1, 10)
    }

def calculate_state_map(object_list: list) -> dict:
    """
    Converts a list of objects into the required {object_id: pseudo_hash} state map.
    """
    state_map = {}
    for obj in object_list:
        # Create a pseudo-hash by concatenating position/size
        pseudo_hash = f"{obj['type']}_{obj['x']}_{obj['y']}_{obj['width']}_{obj['height']}"
        state_map[obj['id']] = pseudo_hash
    return state_map

def apply_changes(previous_state_list: list, job_id: int) -> list:
    """
    Applies random adds, removals, and modifications to the previous state 
    to create the current job's state.
    """
    if not previous_state_list:
        # Initial run (Job 1): generate a full base list
        object_types = ['wall', 'door', 'window', 'column', 'stair']
        new_list = []
        for i in range(NUM_BASE_OBJECTS):
            obj_type = random.choice(object_types)
            obj_id = f"{obj_type[0].upper()}{i:03d}"
            new_list.append(generate_base_object(obj_id, obj_type))
        return new_list

    current_map = {obj['id']: obj for obj in previous_state_list}

    # --- Simulate Changes ---

    # 1. Simulate Removals (5-10% of objects)
    if len(current_map) > 5:
        k_remove = random.randint(int(len(current_map)*0.05), int(len(current_map)*0.10))
        ids_to_remove = random.sample(list(current_map.keys()), k=k_remove)
        for obj_id in ids_to_remove:
            del current_map[obj_id]

    # 2. Simulate Modifications (10-20% of remaining objects)
    k_modify = random.randint(int(len(current_map)*0.10), int(len(current_map)*0.20))
    modified_ids = random.sample(list(current_map.keys()), k=k_modify)
    for obj_id in modified_ids:
        # Simulate a positional move (changes the pseudo-hash)
        current_map[obj_id]['x'] += random.randint(-2, 2) 
        current_map[obj_id]['y'] += random.randint(-2, 2)

    # 3. Simulate Adds (2-5 new objects)
    num_adds = random.randint(2, 5)
    object_types = ['wall', 'door', 'window', 'column', 'stair']
    for _ in range(num_adds):
        obj_type = random.choice(object_types)
        # Ensure new ID is unique
        new_id = f"J{job_id}N{obj_type[0].upper()}{fake.unique.random_int(min=100, max=999)}"
        new_obj = generate_base_object(new_id, obj_type)
        current_map[new_obj['id']] = new_obj
        
    return list(current_map.values())


# Removed the GCS upload function entirely, as it's not used.

# --- MAIN EXECUTION ---

if __name__ == "__main__":
    
    print(f"Starting sequential job simulation for {NUM_SEQUENTIAL_JOBS} jobs (Output ONLY)...")
    
    job_submissions = []
    current_object_list = [] # List of objects for the current job
    
    for i in range(1, NUM_SEQUENTIAL_JOBS + 1):
        job_id = i
        
        # 2. Apply changes to get the object list for the current job
        current_object_list = apply_changes(current_object_list, job_id)
        
        # 3. Calculate the required {object_id: pseudo_hash} state map
        current_state_map = calculate_state_map(current_object_list)
        
        # 4. Create the JSON payload for the /process endpoint
        job_submissions.append({
            "job_id": job_id,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            "latency_ms": random.randint(1000, 30000), 
            "state": current_state_map
        })
        
        # NOTE: We skip the GCS upload check and logging here
        print(f" ✅ Job {job_id} generated. Total objects: {len(current_object_list)}. Payload ready.")

    print("\n--- JOB SUBMISSION JSON (Paste this entire array into your cURL command) ---")
    print(json.dumps(job_submissions, indent=2))
    print("\n---------------------------------------------------------------------------------")
