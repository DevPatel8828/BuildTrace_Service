# buildtrace-service/main.py - REVISED for Sync Reporting and BQ Logging

import os
import json
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, Field
from google.cloud import storage
# Re-import process_job
from diff import process_job 

# --- Configuration & Initialization ---
app = FastAPI()

# Environment variables
PROJECT_ID = os.environ.get("PROJECT_ID")
BUCKET_NAME = os.environ.get("BUCKET").replace("gs://", "")
BIGQUERY_DATASET = "buildtrace_metrics" # Re-added
BIGQUERY_TABLE = "job_results"          # Re-added

# GCP Client
try:
    STORAGE_CLIENT = storage.Client()
    # Note: Pub/Sub is no longer needed
except Exception as e:
    print(f"GCP Client initialization error: {e}")
    STORAGE_CLIENT = None

# --- Pydantic Models (Remains the same for ingestion) ---
class JobState(BaseModel):
    state: dict = Field(..., description="Map of file paths to their content hashes.")
    job_id: int = Field(..., description="Unique ID for the build/job.")
    timestamp: str = Field(..., description="ISO 8601 timestamp of the job start.")
    latency_ms: int = Field(..., description="Total build latency in milliseconds.")


# --- 1. Ingestion Endpoint (/process) ---

@app.post("/process", status_code=202)
async def process_jobs(jobs: List[JobState]):
    """
    Receives jobs and saves them to GCS for later synchronous analysis.
    """
    if not STORAGE_CLIENT:
        raise HTTPException(status_code=500, detail="Storage client not initialized.")
        
    for job in jobs:
        job_id = job.job_id
        job_data = job.model_dump()
        
        # 1. Save state to GCS (job_state/{job_id}.json)
        blob_name = f"job_state/{job_id}.json"
        
        # ... (GCS saving logic is unchanged) ...
        try:
            bucket = STORAGE_CLIENT.bucket(BUCKET_NAME)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(
                json.dumps(job_data), 
                content_type="application/json"
            )
            print(f"Job state for {job_id} saved to GCS.")
        except Exception as e:
            print(f"GCS upload failed for job {job_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save job state for {job_id}.")
            
    # Response confirms storage, but no queueing.
    return {"status": "Jobs accepted and state stored. Ready for reporting."}


# --- 2. New Reporting Endpoint (/report/{job_id}) ---

@app.get("/report/{job_id}", response_model=Dict[str, Any])
def get_change_report(
    job_id: int = Path(..., description="The Job ID (current state) to analyze.")
):
    """
    Triggers the synchronous change detection, logs metrics to BQ, 
    and returns a human-readable report.
    """
    if job_id <= 0:
        raise HTTPException(status_code=400, detail="Job ID must be positive.")
        
    try:
        # Synchronously call the analysis logic with BQ context
        report = process_job(job_id, BUCKET_NAME, BIGQUERY_DATASET, BIGQUERY_TABLE)
        return report
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"Error generating report for Job {job_id}: {e}")
        # Return 500 but indicate that BQ logging may have failed
        raise HTTPException(status_code=500, detail=f"Internal analysis failed. Check logs for BigQuery status.")


# --- Auxiliary Endpoint ---

@app.get("/health")
async def health_check():
    # Only need to check Storage Client as Pub/Sub is gone
    if not STORAGE_CLIENT:
        raise HTTPException(status_code=503, detail="Service Unhealthy: Storage Client failed to initialize.")
    return {"status": "SUCCESS", "service": "BuildTrace-SyncReport-BQLog"}
