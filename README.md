# Uzman Posta Mail Event Logger

<p align="center">
<img src="assets/uzmanposta_logo.png" alt="Uzman Posta Logo" width="400"/>
</p>

## Overview

The **Uzman Posta Mail Event Logger** is a Python-based script designed to collect and log mail events (both incoming and outgoing) from the Uzman Posta API. This tool helps users efficiently monitor and analyze mail operations by storing log data in structured files.

## Objective

This project retrieves mail event logs using the Uzman Posta API and stores them as log files for easy access and analysis.

## Prerequisites

Before using this project, ensure the following requirements are met:

- Access to the Uzman Posta API and its documentation.
- A **Bearer access token** for API authentication.
- A Python environment with the required dependencies installed.

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

## Configuration

The **uzmanposta_email.ini** file contains the configuration settings required for the script to run. Below is an example configuration file:

```ini
; Mail Logger Configuration File
; Last updated: 2025

[Mail]
; API authentication key
api_key = xxxxxxxxxxxxxxxxxxxxxxx

; Output directory and file settings
log_directory = ./output
log_file_name_format = uzmanposta-mail_%%Y-%%m-%%d-%%H-%%M.json
position_file = ./uzmanposta-mail_position.txt

; Time settings
start_time = 1738911600
split_interval = 300
max_time_gap = 3600

; API endpoint configuration
domain = domain.com.tr
url = https://yenipanel-api.uzmanposta.com/api/v2/logs/mail
type = outgoinglog

; Additional settings
lock_file_path = ./uzmanposta-mail.lock
verbose = true
message_log_file_name = messages.log
```

## Usage

Run the script using the following command:

```bash
python3 uzmanposta_mail.py
```

For scheduled execution with **cron**, add the following line to your crontab:

```bash
* * * * * /usr/bin/python3 /home/temp/uzmanposta/uzmanposta_mail.py
```

Note: If the script does not start, you can get the error output with this command

```bash
* * * * * /usr/bin/python3 /home/temp/uzmanposta/uzmanposta_mail.py >> /home/temp/uzmanposta/uzmanposta-cron.log 2>&1
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

Include the **Bearer token** in the `Authorization` header of API requests:

```json
Authorization: Bearer <api_key>
```

## Notes

- Regularly clean log files to manage disk usage.
- Validate script parameters to ensure proper execution.
- Test in a development environment before deploying to production.
- Check firewall settings to allow API requests.
