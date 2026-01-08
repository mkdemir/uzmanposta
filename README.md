# Uzman Posta Mail Event Logger

<p align="center">
<img src="assets/uzmanposta-logo.png" alt="Uzman Posta Logo" width="400"/>
</p>

## Overview

The **Uzman Posta Mail Event Logger** is a production-grade Python script designed to collect and log mail events (incoming/outgoing), quarantine, and authentication logs from the Uzman Posta API. It features high-performance parallel processing with concurrency limits, robust data integrity, and is optimized for automated environments like Cron.

## Key Features

- ✅ **Ordered Processing**: Logs are saved in strict chronological order for absolute data integrity.
- ✅ **Dynamic File Naming**: Log filenames are standardized to `{domain}_{type}_%Y-%m-%d_%H.log` with support for dynamic placeholders.
- ✅ **Auto-Cleanup**: Automated retention policies for both message and error logs to keep disk usage in check.
- ✅ **High-Performance Parallelism**: Fetches logs for multiple domains in parallel with configurable worker limits (`--max-workers`).
- ✅ **Concurrent Detail Fetching**: Retrieves detailed mail logs (sender, recipient, status) using multi-threaded workers within each domain.
- ✅ **Cross-Platform Robustness**: Includes Windows-specific fixes for file locking and atomic writes (`[WinError 5]` handling).
- ✅ **Cron Optimized**: Internal paths are automatically resolved to the script's absolute directory to prevent failures in scheduled tasks.
- ✅ **Atomic Position Tracking**: Resumes exactly where it left off, even after a crash or manual stop.
- ✅ **Session Management**: Uses persistent HTTP connections (Keep-Alive) with `requests.Session`.
- ✅ **Monitoring**: Real-time heartbeat files and comprehensive metrics per domain.

## Prerequisites

- Python 3.8+
- `requests` library (`pip install requests`)
- Access to the Uzman Posta API with a Bearer token

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# List all available sections in config
python3 uzmanposta.py --list

# Run all domains in parallel (default 5 workers)
python3 uzmanposta.py --all --parallel

# Run all domains with specific concurrency limit
python3 uzmanposta.py --all --parallel --max-workers 3

# Run a specific domain section
python3 uzmanposta.py --section "MailLogger:domain-outgoing"
```

## CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--config PATH` | Path to the INI configuration file. | `uzmanposta.ini` |
| `--section NAME` | Run only a specific section from the config. | - |
| `--all` | Process all sections starting with `[MailLogger:*]`. | `False` |
| `--parallel` | Enable multi-threaded execution for sections (requires `--all`). | `False` |
| `--max-workers N` | Maximum number of parallel workers for high-level tasks. | `5` |
| `--list` | List all discovered configuration sections and exit. | - |

## Configuration (`uzmanposta.ini`)

The script uses an INI file for configuration. You can use a `[DEFAULT]` section for shared settings.

```ini
[DEFAULT]
# Global defaults (commented out to use internal defaults)
# log_directory = ./output
# max_parallel_details = 2
log_file_name_format = {domain}_{type}_%Y-%m-%d_%H.log

[MailLogger:example-outgoing]
api_key    = YOUR_API_KEY
domain     = example.com
type       = outgoinglog
category   = mail
start_time = 1734876000
```

### Advanced Config Options

| Option | Description | Default |
| --- | --- | --- |
| `api_key` | **Required** API Key for the domain | - |
| `domain` | **Required** Domain name | - |
| `type` | Log type (`incominglog`, `outgoinglog`, `quarantine`, etc.) | `outgoinglog` |
| `category` | API category (`mail`, `quarantine`, `authentication`) | `mail` |
| `start_time` | Unix timestamp to start fetching logs from (defaults to NOW if missing) | `Current Time` |
| `log_file_name_format` | Format for log files with placeholders | `{domain}_{type}_%Y-%m-%d_%H.log` |
| `error_log_file_name` | Format for error log files | `errors_%Y-%m-%d_%H.log` |
| `error_log_retention_count` | Number of recent error logs to keep | `2` |
| `max_parallel_details` | Concurrent detail fetch workers per domain | `2` |
| `use_session` | Enable connection pooling | `True` |

## Output Structure

The script automatically maintains a clean directory structure relative to its location:

```text
/project-root/
├── positions/             # Checkpoints (resume pointers) for each section
├── locks/                 # Lock files to prevent concurrent same-section runs
└── output/
    └── example.com/
        └── mail/
            └── outgoinglog/
                ├── example.com_outgoinglog_2025-12-25_14.log  # Main data log
                ├── messages_2025-12-25_14.log                 # Verbose operational logs
                ├── errors_2025-12-25_14.log                   # Error logs
                └── example.com-outgoing_heartbeat.json        # Health status
```

## Deployment (Cron)

The script is designed for Cron. It automatically finds its configuration and output folders even when run from a different working directory.

```bash
# Every 5 minutes (Parallel execution with 5 workers)
*/5 * * * * /usr/bin/python3 /opt/uzmanposta/uzmanposta.py --config /opt/uzmanposta/uzmanposta.ini --all --parallel --max-workers 5
```

## Metrics & Monitoring

The script provides real-time monitoring through two main mechanisms:

1.  **Heartbeat Files**: Each section maintains a `{section}_heartbeat.json` file in the output directory, containing:
    - `status`: `running`, `completed`, or `error`.
    - `last_heartbeat`: Last update timestamp.
    - `pid`: Process ID.
    - `metrics`: Current processing statistics.
2.  **Summary Statistics**: At the end of each run, a summary is logged including:
    - Total logs processed.
    - API success/error rates.
    - Average/Min/Max API response times.
    - Throughput (logs/second).

## Data Integrity & Resume

### Position Tracking

The script uses atomic position tracking to ensure no logs are missed or duplicated.

- **Location**: `./positions/{section}.pos`
- **Mechanism**: After each successful batch write, the timestamp of the last processed record is saved. On restart, the script resumes exactly from this timestamp.

### File Locking

To prevent data corruption, a cross-platform file locking mechanism is used:

- **Location**: `./locks/{section}.lock`
- **Behavior**: If a section is already being processed (e.g., a previous Cron job is still running), the new instance will skip that section and log a message.

## Troubleshooting

### `[WinError 5] Access is denied`
This is a common issue on Windows when multiple threads try to write/rename files simultaneously while an antivirus scanner or the OS locks them. The script includes a retry mechanism (`_safe_replace`) to handle this transient error automatically.

### API Throttling ("Too Many Requests")
If you see HTTP 429 errors or timeouts, reduce the concurrency:
- Decrease `--max-workers` (e.g., from 5 to 2).
- Decrease `max_parallel_details` in `uzmanposta.ini` (e.g., set to 1 or 2).

## Legal Disclaimer

> [!IMPORTANT]
> **Data Privacy & Compliance**
> This tool is designed to collect and process potentially sensitive email metadata. Users are responsible for ensuring that the use of this script complies with local and international data protection laws, including:
> - **GDPR** (General Data Protection Regulation)
> - **Internal Security Policies**
> - **Client Confidentiality Agreements**
>
> The developers of this script are not responsible for any data misuse or unauthorized access resulting from improper configuration or deployment.

## License

MIT License - See [LICENSE](LICENSE) file.
