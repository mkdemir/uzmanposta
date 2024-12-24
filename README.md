# Uzman Posta Mail Event Logger

<p align="center">
<img src="assets/uzmanposta_logo.png" alt="Uzman Posta Logo" width="400"/>
</p>

## Overview

The Uzman Posta Mail Event Logger is a Python-based script designed to collect and log mail events (both incoming and outgoing) from the Uzman Posta API. This tool allows users to efficiently monitor and analyze mail operations by storing log data in structured files.

## Objective

This project retrieves mail event logs using the Uzman Posta API and stores them as log files for easy access and analysis.

## Prerequisites

Before using this project, ensure the following requirements are met:

- Access to the Uzman Posta API and its documentation.
- A Bearer access token for API authentication.
- Python environment with required dependencies installed.

## Installation

1. Install the required Python package:

   ```bash
   pip install requests
   ```

2. Clone or download the project files to a suitable directory.

3. Configure the following parameters in the script or provide them as runtime arguments:

   - `api_key`: Bearer access token.
   - Other parameters such as API endpoint URL and file paths.

## Features

The `MailLogger` class handles the following operations:

- Retrieving and storing mail logs (incoming and outgoing).
- Managing log retrieval time intervals to avoid API overload.
- Logging errors and saving progress for recovery.
- Supporting detailed log fetching for specific events.

## Usage

Run the script using the following command:

```bash
python mail_logger.py \
  --api_key <your_api_key> \
  --log_directory <log_directory> \
  --log_file_name_format <log_file_name_format> \
  --position_file <position_file_path> \
  --start_time <start_time_unix> \
  --domain <domain_or_email> \
  --url <api_url> \
  --log_type <log_type> \
  --split_interval <split_interval_seconds> \
  --max_time_gap <max_time_gap_seconds>
```

### Parameters

- `--api_key`: API key for accessing the Uzman Posta API.
- `--log_directory`: Directory where log files will be saved.
- `--log_file_name_format`: Format for log file names (e.g., `uzman_posta_mail_%Y%m%d%H%M.json`).
- `--position_file`: File to store the last retrieved timestamp for continuing log retrieval.
- `--start_time`: Start time for retrieving logs (Unix timestamp).
- `--domain`: Domain or email address for which logs are retrieved.
- `--url`: API endpoint URL for mail logs.
- `--log_type`: Type of logs to retrieve (`incominglog` or `outgoinglog`).
- `--split_interval`: Time interval (in seconds) for splitting requests.
- `--max_time_gap`: Maximum time range (in seconds) for a single request.

### Example

```bash
python mail_logger.py \
  --api_key d1cs3-2312d!234323 \
  --log_directory /home/user/output \
  --log_file_name_format uzman_posta_mail_%Y%m%d%H%M.json \
  --position_file /home/user/output/position.txt \
  --start_time 1712131157 \
  --domain example.com \
  --url https://yenipanel-api.uzmanposta.com/api/v2/logs/mail \
  --log_type incominglog \
  --split_interval 3600 \
  --max_time_gap 86400
```

## Class Overview: `MailLogger`

### Key Attributes

- **`api_key`**: Bearer token for API authentication.
- **`log_directory`**: Directory for saving log files.
- **`log_file_name_format`**: Format string for generating log file names.
- **`position_file`**: Path to file storing the last processed timestamp.
- **`start_time`**: Starting timestamp for log retrieval.
- **`domain`**: Domain or email for retrieving logs.
- **`url`**: Uzman Posta API endpoint for log retrieval.
- **`log_type`**: Log type (`incominglog` or `outgoinglog`).
- **`split_interval`**: Time interval (seconds) for chunking requests.
- **`max_time_gap`**: Maximum time range (seconds) for a single request.

### Key Methods

- **`setup_logging(self)`**: Configures the logging environment and ensures directories exist.
- **`generate_log_file_name(self)`**: Creates log file names based on the specified format.
- **`save_last_position(self, endtime)`**: Saves the last retrieved timestamp to a file.
- **`load_last_position(self)`**: Loads the last processed timestamp from a file.
- **`retrieve_mail_logs(self, starttime, endtime, retries, sleep_time)`**: Fetches logs within a time range, with retry logic for robustness.
- **`retrieve_detailed_log(self, queue_id, time, retries, sleep_time)`**: Fetches detailed logs for specific events.
- **`log_error(self, error_message)`**: Logs errors for debugging and troubleshooting.
- **`split_and_retrieve_logs(self)`**: Splits time ranges to avoid large gaps and API overload.
- **`process_logs(self, logs)`**: Processes and saves logs in structured files.
- **`run(self)`**: Main entry point for the logging process.

## Authentication

Include the Bearer token in the `Authorization` header of API requests:

```json
Authorization: Bearer <api_key>
```

## Notes

- Regularly clean log files to manage disk usage.
- Validate script parameters to ensure proper execution.
- Test in a development environment before deploying to production.
- Check firewall settings to allow API requests.

## Support

For issues or questions, refer to the Uzman Posta API documentation or contact support.
