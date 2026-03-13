SmellHunter API
==========================

Event-driven API for detecting code smells using metrics analysis and a Domain Specific Language (DSL).

## Table of Contents

1. [Research Motivation](#research-motivation)
   - [Problem](#problem)
   - [Research Gap](#research-gap)
   - [Proposed Approach](#proposed-approach)

2. [Architecture](#architecture)

3. [Detection Workflow](#detection-workflow)

4. [API Endpoints](#api-endpoints)
   - [POST analyze](#post-analyze)
   - [GET status](#get-statusctx_id)
   - [GET smells](#get-smellssmell_id)

5. [Event Flow](#event-flow)

6. [Response Codes](#response-codes)

7. [Observers Overview](#observers-overview)

8. [Setup Guide](#setup-guide)
   - [Prerequisites](#prerequisites)
      - [Python Environment](#python-environment)
      - [Install Dependencies](#install-dependencies)
      - [Google Sheets Setup](#google-sheets-setup)
    
9. [Running the Application](#running-the-application)

10. [Eclipse Plugin Setup](#eclipse-plugin-setup)
       - [Requirements](#requirements)
       - [Import Plugin Project](#import-plugin-project)
       - [Build and Run](#build-and-run)

11. [Data Visualization](#data-visualization)
       - [Overview](#overview)
       - [Physical Context View](#physical-context-view)
       - [Smell Details View](#smell-details-view)
    
## Research Motivation

### *Problem*

Code smells are internal structures in source code that violate coding conventions and design principles, harming the internal quality of evolving systems and indicating issues of architectural and design degradation.

They typically arise when developers make hurried or poorly planned modifications to implement features or fix problems.

### *Research Gap*

Traditional detection approaches focus mainly on static analysis and predefined technical metrics. However, such approaches often ignore important aspects of the development context, such as team characteristics, project constraints, and the stage of software evolution.

### *Proposed Approach*

Unlike traditional detection approaches, **SmellHunter integrates technical metrics alongside development context**.

The tool supports **asynchronous analyses**, reducing interference with the developer’s workflow while enabling scalable and incremental processing.

This approach aims to **reduce false positives** and helps in **refactoring decisions aligned with real-world development contexts**.


Architecture
------------
![Architecture](/figures/article_diagram_smellhunter.drawio.png)
The system uses an event bus pattern with the following event types:

-   `METRICS_VALIDATION_REQUESTED`

-   `VALIDATION_COMPLETED` / `VALIDATION_FAILED`

-   `ANALYSIS_COMPLETED`

-   `PERSISTENCE_COMPLETED`

## Detection Workflow

```mermaid
flowchart LR

A[Eclipse Plugin / Client] --> B[POST /analyze]

B --> C[API Gateway]

C --> D[Event: METRICS_VALIDATION_REQUESTED]

D --> E[Validation Service]

E --> F{Validation Result}

F -->|Success| G[Event: VALIDATION_COMPLETED]
F -->|Failure| X[Event: VALIDATION_FAILED]

G --> H[Interpreter Engine]

H --> I[Event: ANALYSIS_COMPLETED]

I --> J[Persistence Worker]

J --> K[(Smell Storage)]

K --> L[GET /status]
K --> M[GET /smells]
```

API Endpoints
-------------

### `POST /analyze`

Initiates asynchronous smell analysis.

Request Format: `multipart/form-data` or `application/json`

#### Required Parameters (multipart/form-data):

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| user_id | string | Yes | User identifier |
| smell_dsl | file | Yes | `.smelldsl` file with smell definitions |
| metrics | file | Yes | CSV/JSON file with metric values |
| thresholds | file | Yes | CSV/JSON file with threshold values |


### Optional Parametes
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| loc_id | string | Yes | Location identifier |
| project_id | string | Yes | Project identifier |
| org_id | string | Yes | Company identifier |

#### File Formats:

## `metrics.csv`

```
Metrica,Valor
GodClass.ATFD,12
GodClass.TCC,4
LongMethod.LOC,300
```

## `thresholds.csv`
```
Metrica,Valor
GodClass.ATFD-LIMIT,10
GodClass.TCC-LIMIT,5
LongMethod.LOC-LIMIT,100
```

## `smelldsl`:

```
smelltype DesignSmell;
smell GodClass extends DesignSmell {
    feature ATFD with threshold 4, 10;
    feature TCC with threshold 3, 5;
    treatment "Refactor into smaller classes";
}
rule GodClassRule when (GodClass.ATFD > GodClass.ATFD-LIMIT) then "Flag";
```

#### JSON Request (alternative):


```
{
  "user_id": 3,
  "smell_dsl": "smelltype DesignSmell; smell GodClass extends...",
  "metrics": {
    "GodClass.ATFD": 12,
    "GodClass.TCC": 4
  },
  "thresholds": {
    "GodClass.ATFD-LIMIT": 10,
    "GodClass.TCC-LIMIT": 5
  },
  "request_data": {
    "org_id": 2,
    "loc_id": 3,
    "project_id": 1,
    "file_path": "/src/Main.java",
    "language": "java",
    "branch": "main",
    "commit_sha": "abc123"
  }
}
```
#### Response (202 Accepted):

```
{
  "status": "accepted",
  "ctx_id": "550e8400-e29b-41d4-a716-446655440000",
  "smell_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
}
```

### `GET /status/<ctx_id>`

Check analysis status.

#### Response (processing):

```
{
  "status": "processing"
}
```

#### Response (completed):

```
{
  "status": "ok",
  "history": [
    {
      "cod_ctx": "550e8400-e29b-41d4-a716-446655440000",
      "status": "INTERPRETED",
      "details": "{\"result\": {\"is_smell\": true, \"smells_detected\": [\"GodClass\"]}}"
    }
  ]
}
```

### `GET /smells/<smell_id>`

Retrieve persisted smell data.

#### Response (200 OK):

```
{
  "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "ctx_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp_utc": "2024-01-01T12:00:00.000Z",
  "user_id": "123",
  "org_id": "456",
  "loc_id": "789",
  "project_id": "101",
  "type": "GodClass",
  "smell_type": "DesignSmell",
  "is_smell": true,
  "rule": {"GodClassRule": true},
  "file_path": "/src/Main.java",
  "language": "java",
  "branch": "main",
  "commit_sha": "abc123",
  "treatment": "Refactor into smaller classes",
  "metrics": {
    "GodClass.ATFD": 12,
    "GodClass.TCC": 4
  }
}
```

Event Flow
----------

1.  Eclipse Plugin Client → `POST /analyze`

2.  API generates `ctx_id` and `smell_id`

3.  Event `METRICS_VALIDATION_REQUESTED` published

4.  ValidationObserver validates metrics and thresholds

5.  Event `VALIDATION_COMPLETED` published

6.  InterpreterWorker executes `run_interpretation()`

7.  Event `ANALYSIS_COMPLETED` published

8.  PersistenceWorker saves to local CSV

9.  Event `PERSISTENCE_COMPLETED` published

10. SheetsPersistenceObserver saves to Google Sheets

11. StatusWorker stores result for status queries

12. Client polls `GET /status/<ctx_id>` and `GET /smells/<smell_id>`

Response Codes
--------------

| Code | Description |
| --- | --- |
| 202 | Analysis accepted (async processing) |
| 400 | Bad request (invalid data) |
| 404 | Resource not found |
| 500 | Internal server error |


Observers Overview
------------------

| Observer | Event | Responsibility |
| --- | --- | --- |
| ValidationObserver | METRICS_VALIDATION_REQUESTED | Validates metrics |
| InterpreterWorker | VALIDATION_COMPLETED | Executes interpretation |
| PersistenceWorker | ANALYSIS_COMPLETED | Saves to CSV |
| SheetsPersistenceObserver | PERSISTENCE_COMPLETED | Saves to Google Sheets |
| StatusWorker | ANALYSIS_COMPLETED | Stores for status queries |
| LogObserver | ANALYSIS_COMPLETED | Saves log file |
| CsvSheetsObserver | ANALYSIS_COMPLETED | Exports to CSV |
| EventBusLoggerObserver | All | Logs context events |


Setup Guide
===========

Complete Step-by-Step Installation
----------------------------------

## Prerequisites

### Python Environment

#### Python 3.9+ required
 ```
python --version  # Verify version
 ```
## Create virtual environment (recommended)
 ```
python -m venv venv
 ```


## Activate virtual environment
 ```
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
 ```
----------
### Install Dependencies
----------
### Google Sheets Setup

#### 3.1 Create Google Cloud Project

1.  Go to [Google Cloud Console](https://console.cloud.google.com/)

2.  Create new project or select existing

3.  Enable Google Sheets API

#### 3.2 Create Service Account

1.  Navigate to IAM & Admin → Service Accounts

2.  Click Create Service Account

3.  Name: `(...)`

4.  Assign role: Editor

5.  Create key: JSON format

6.  Download and save as `service-account.json` in project root

### 3.3 Google Sheets Setup

1. Download the pre-configured spreadsheet:

   - Access the shared Google Drive template:

     🔗 **[SmellHunter Database Template](https://docs.google.com/spreadsheets/d/1mYoiaN0SBuAhNZgl-2trXicUmo2pxkHMTsYyr1uPRMo/edit?usp=sharing)**

   - Click "Make a copy" to save it to your own Google Drive

   - Rename it as needed (e.g., "SmellHunter - [Your Project Name]")
2.  Worksheet Structure (already configured):

    -   Bad_Smell - Contains all detected smells with complete metadata

    -   Context - Logs all context events and execution history

3.  Share with Service Account:

    -   Open your copied spreadsheet

    -   Click the "Share" button in the top-right corner

    -   Add your service account email (found in `service-account.json`)

    -   Assign role: Editor

    -   Uncheck "Notify people" and click Share

4.  Get Spreadsheet ID:

    -   The spreadsheet URL contains the ID:\
        `https://docs.google.com/spreadsheets/d/``SPREADSHEET_ID_HERE``/edit`

    -   Copy this ID and add it to your `.env` file:
```
        SPREADSHEET_ID=YOUR_SPREADSHEET_ID
        GOOGLE_APPLICATION_CREDENTIALS=app/configs/service_account.json
```
5.  Verify Headers (already set up):

    Bad_Smell worksheet headers:

 ```
    id, timestamp_utc, time_zone, user_id, org_id, loc_id, project_id, type, smell_type, is_smell, rule, file_path, language, branch, commit_sha, ctx_id, treatment
  ```

Context worksheet headers:

```
    ctx_id, user_id, org_id, loc_id, timestamp_utc, event_type
```

The spreadsheets are now ready to receive data from your SmellDSL Detection Service!

### 4\. Configuration File

Create `.env` file in project root:


#### Flask settings
```
FLASK_ENV=development
FLASK_APP=interpreter_api.py
PORT=5000
```
#### Google Sheets
```
SPREADSHEET_ID=your-spreadsheet-id-here
SERVICE_ACCOUNT_FILE=service-account.json
```

#### Logging
```
LOG_DIR=logs
```

### 5\. Project Structure

```
smell-detect/
├── app/
│   ├── configs/
│   │   └── settings.py
│   ├── events/
│   │   ├── event_bus.py
│   │   ├── event_types.py
│   │   ├── observers.py
│   │   └── validation_service.py
│   ├── parser/
│   │   ├── grammar.py
│   │   └── metric_extractor.py
│   ├── repositories/
│   │   └── sheets_repository.py
│   ├── interpreter_api.py
│   ├── interpreter_core.py
│   └── __init__.py
├── logs/
├── service-account.json
├── .env
└── requirements.txt
```

### 6\. pip install requirements.txt
```
#Core dependencies
flask==2.3.3
lark==1.2.2

#Google Sheets integration
google-api-python-client==2.108.0
google-auth==2.28.1
google-auth-httplib2==0.2.0
google-auth-oauthlib==1.2.0
google-oauth2==1.0.0


#Utilities
python-dotenv==1.0.0
requests==2.31.0
dataclasses==0.6  # For Python < 3.7 (optional)
typing-extensions==4.9.0

#Development tools (optional)
pytest==7.4.4
black==23.12.1
flake8==7.0.0
```

## Running the Application

### 1\. Start the API Server


```
cd smelldetect
python -m app.interpreter_api
```

## Eclipse Plugin Setup 
 🔗[**SmellHunter Eclipse Plugin**](https://github.com/MathDEV-0/SmellHunter-Eclipse-Plugin.git)

###  Requirements

-   Eclipse IDE 2023-12 or later

-   JDK 21 or later

-   SWT libraries (included with Eclipse)

### Import Plugin Project

1.  File → Import → Existing Projects into Workspace

2.  Select the plugin project directory

3.  Check "Search for nested projects"

4.  Click Finish

### Build and Run

1.  Right-click on the project → Run As → Eclipse Application

2.  A new Eclipse instance will launch

3.  Navigate to Window → Show View → Other...

4.  In the dialog, expand the plugin category and select "MyView"

5.  Click Open to display the view


## Data Visualization

### Overview

SmellHunter persists detected smells and contextual execution data in Google Sheets.  
These datasets can be connected to AppSheet to provide an interactive visualization layer for exploring detection results.

The dashboard allows users to inspect detected smells, navigate contextual information, and analyze detection outcomes through a structured interface.

---

### Physical Context View

This view presents contextual information related to the execution environment where the analysis occurred.  
It includes metadata such as organization identifiers, project information, location identifiers, and execution timestamps.

The goal of this view is to support contextual analysis of smell occurrences across different projects and development environments.

![Physical Context View](figures/tela_sao_leo_location.png)
![Physical Context View1](figures/tela_sao_leo_smell.png)
![Physical Context View2](figures/tela_sao_leo_smell2.png)

---

### Smell Details View

The Smell Details view displays the complete information related to a detected smell instance.  
This includes the smell type, evaluated rule results, associated metrics, and metadata describing the analyzed artifact.

This view helps developers understand why a smell was detected and provides insights to guide refactoring decisions.

![Smell Details View](figures/tela5_artigo.png)
![Smell Details View](figures/tela6_artigo.png)
![Smell Details View](figures/tela7_artigo.png)
