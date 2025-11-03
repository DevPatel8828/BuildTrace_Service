## 🏗️ BuildTrace Service: Synchronous Reporting and BigQuery Logging

This document explains the architecture, data flow, operational strategy, and future outlook for the BuildTrace service, which tracks object changes between sequential build jobs and logs performance metrics.

-----

## 1\. System Architecture and Data Flow

The system is a **monolithic, synchronous microservice** deployed on a platform like Google Cloud Run, utilizing FastAPI for the API layer and Google Cloud services for persistence and metrics.

### Architecture Overview

  * **Client (Simulator):** Sends the `JobState` payload (a map of file paths/object IDs to their pseudo-hashes, plus metadata like `timestamp` and `latency_ms`) to the service.
  * **FastAPI Service (main.py):** Hosted on Cloud Run. Handles two primary requests: ingestion (`/process`) and synchronous reporting (`/report/{job_id}`).
  * **Google Cloud Storage (GCS):** Used as the **durable source of truth** for all job states. Each job's full payload is stored as a JSON file (e.g., `job_state/123.json`).
  * **Google BigQuery (BQ):** Used as the **data warehouse** for quantitative metrics derived from the change analysis (e.g., `total_added`, `total_removed`, `latency_ms`).

### Data Flow

| Step | Endpoint | Action | Components Involved |
| :--- | :--- | :--- | :--- |
| **1. Ingestion** | `POST /process` | Accepts a list of jobs, validates the Pydantic model, and saves the full JSON payload for *each* job to GCS. | Client $\rightarrow$ FastAPI $\rightarrow$ GCS |
| **2. Reporting/Analysis** | `GET /report/{job_id}` | 1. **Reads** the current job's state (`job_id`) and the previous job's state (`job_id - 1`) from **GCS**. 2. **Compares** the two states to find added, removed, and modified/moved objects. 3. **Logs** quantitative metrics (counts, latency) to BigQuery. 4. **Returns** a human-readable, descriptive report. | Client $\rightarrow$ FastAPI (diff.py) $\rightarrow$ GCS & BQ |

-----

## 2\. Scaling and Fault Tolerance Strategy

### 📈 Scaling

The service is designed for deployment on **Google Cloud Run** or a similar serverless container platform.

  * **Automatic Scaling:** Cloud Run handles automatic horizontal scaling (adding container instances) based on the concurrent request load, making the service highly scalable for the synchronous analysis and reporting endpoints.
  * **Decoupling:** By storing the job state in **GCS**, the ingestion endpoint (`/process`) is very fast, only requiring a simple write operation. The complex, CPU-intensive analysis is deferred to the separate, on-demand reporting endpoint (`/report/{job_id}`).

### 🛡️ Fault Tolerance

| Component | Failure | Mitigation Strategy |
| :--- | :--- | :--- |
| **FastAPI/Cloud Run** | Instance crash/failure. | Cloud Run automatically restarts/replaces failed containers. The analysis is stateless (data read from GCS). |
| **Google Cloud Storage** | GCS Write/Read Failure. | The `load_full_job_data` function includes a `try/except` block and will raise a critical exception, resulting in a **500 or 404** API response, preventing bad data from being analyzed or reported. |
| **BigQuery Insertion** | BQ Client/Table Error. | The service prioritizes the **report generation**. If BQ insertion fails, an error is printed to the logs, but the descriptive report is still generated and returned to the client. The report's status field confirms that "BigQuery insertion attempted." |

-----

## 3\. Metrics Computation Design

The goal is to log quantitative, searchable metrics directly into BigQuery for long-term analysis, reporting, and dashboarding.

### Stored Metrics (BigQuery Schema)

The `metrics` dictionary in `diff.py` defines the quantitative metrics logged for every run of the `/report` endpoint:

  * **`timestamp`:** When the job was initiated (from the ingested payload).
  * **`job_id`:** The unique identifier for the current build/job state.
  * **`latency_ms`:** The total build time of the job itself (provided in the payload).
  * **`total_added`:** Count of new objects/files since the previous job.
  * **`total_removed`:** Count of deleted objects/files since the previous job.
  * **`total_modified`:** Count of objects/files whose hash changed (moved or modified attributes).
  * **`total_unchanged`:** Count of objects/files that are identical to the previous job.

### Estimating P99 Latency (Conceptual)

The **P99 (99th Percentile) latency** for a specific period (e.g., the last month) is estimated **within BigQuery** using the collected data:

1.  **Query:** Filter the `job_results` table for the desired time range.
2.  **Aggregation:** Use a BigQuery statistical function like `APPROX_QUANTILES` on the `latency_ms` column to find the value at the 99th percentile.

> **Example BQ Query:**
>
> ```sql
> SELECT
>   APPROX_QUANTILES(latency_ms, 100)[OFFSET(99)] AS p99_latency_ms
> FROM
>   `project.buildtrace_metrics.job_results`
> WHERE
>   timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
> ```

-----

## 4\. Trade-offs and Possible Future Extensions

### ⚖️ Trade-offs

| Aspect | Current Design | Trade-off Implication |
| :--- | :--- | :--- |
| **Architecture** | Synchronous/Monolithic | **Simpler deployment** and **immediate feedback** for the `/report` endpoint, but analysis is **blocking** and ties up the web server for the duration of the GCS reads and diff computation. |
| **Data Source** | GCS for all state data. | **Cheaper** and simpler than a dedicated database (e.g., Firestore or PostgreSQL), but **read latency** can be higher, especially for frequent sequential reads. |
| **Job ID** | Incremental ID (`job_id - 1`). | **Simple mechanism** for finding the previous state, but **fragile** if job IDs are non-sequential (e.g., a job fails to submit, leaving a gap). |

### 🚀 Possible Future Extensions

1.  **Asynchronous Analysis (Decoupling):**
      * Change the `/process` endpoint to **publish a message to Pub/Sub** *after* saving to GCS.
      * Deploy the `diff.py` logic as a **Cloud Function** (triggered by Pub/Sub) to perform the analysis and BQ logging *in the background*.
      * The `/report` endpoint would then only fetch the pre-computed BQ results or GCS report file, significantly **reducing its latency** and making the system more scalable.
2.  **State Lookup (Robust Diff):**
      * Instead of `job_id - 1`, implement a mechanism to look up the **last successful job ID** for the same project/service using a small metadata store (like Redis or a simple BQ query). This makes the diff more reliable.
3.  **Advanced Hashing:**
      * The current pseudo-hash is simplistic (`type_x_y_w_h`). A more robust system would use a cryptographic hash (e.g., SHA-256) of the object's actual content or attributes, ensuring any non-positional change is also detected.
