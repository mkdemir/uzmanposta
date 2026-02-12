"""
MailLogger: A service for logging and processing mail events from Uzman Posta API.

This module provides functionality to:
- Retrieve incoming and outgoing mail logs from Uzman Posta API
- Process and store logs in configurable file formats
- Track logging positions to ensure continuous data collection
- Handle API pagination and rate limiting
- Support verbose logging for debugging

Reference: https://mxlayer.stoplight.io/
"""

# pylint: disable=too-many-lines

import os
import sys
import json
import socket
import configparser
import logging
import hashlib
import signal
import time
import threading

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

if os.name == 'nt':
    import msvcrt # pylint: disable=import-error
else:
    import fcntl # pylint: disable=import-error


@dataclass
class MailLoggerConfig: # pylint: disable=too-many-instance-attributes
    """Configuration dataclass for MailLogger settings."""
    api_key: str
    log_directory: str
    position_file: str
    url: str
    start_time: int = 0
    log_file_name_format: str = '{domain}_{type}_%Y-%m-%d_%H.log'
    domain: str = ''
    log_type: str = 'outgoinglog'
    api_category: str = 'mail'  # mail, quarantine, authentication
    split_interval: int = 300
    max_time_gap: int = 3600
    verbose: bool = True
    message_log_file_name: str = 'messages_%Y-%m-%d_%H.log'
    message_log_retention_count: int = 2
    error_log_file_name: str = 'errors_%Y-%m-%d_%H.log'
    error_log_retention_count: int = 2
    list_timeout: int = 300
    detail_timeout: int = 120
    list_retries: int = 10
    list_sleep_time: int = 2
    detail_retries: int = 10
    detail_sleep_time: int = 2
    max_records_per_page: int = 1000
    heartbeat_file: str = 'heartbeat.json'
    lock_file_path: str = 'uzmanposta.lock'
    section_name: str = ''
    max_parallel_details: int = 2
    use_session: bool = True



@dataclass
class Metrics:
    """Tracks runtime metrics for monitoring and reporting."""
    logs_processed: int = 0
    errors_count: int = 0
    api_calls: int = 0
    total_api_time: float = 0.0
    min_api_time: float = float('inf')
    max_api_time: float = 0.0
    start_time: float = field(default_factory=time.perf_counter)

    def record_api_call(self, duration: float) -> None:
        """Record an API call with its duration."""
        self.api_calls += 1
        self.total_api_time += duration
        self.min_api_time = min(self.min_api_time, duration)
        self.max_api_time = max(self.max_api_time, duration)

    @property
    def avg_api_time(self) -> float:
        """Calculate average API response time."""
        return self.total_api_time / self.api_calls if self.api_calls > 0 else 0.0

    @property
    def error_rate(self) -> float:
        """Calculate error rate as percentage."""
        total = self.logs_processed + self.errors_count
        return (self.errors_count / total * 100) if total > 0 else 0.0

    @property
    def elapsed_time(self) -> float:
        """Calculate total elapsed time in seconds."""
        return time.perf_counter() - self.start_time

    @property
    def logs_per_second(self) -> float:
        """Calculate throughput as logs per second."""
        return self.logs_processed / self.elapsed_time if self.elapsed_time > 0 else 0.0

    @property
    def avg_logs_per_api_call(self) -> float:
        """Calculate average logs retrieved per API call."""
        return self.logs_processed / self.api_calls if self.api_calls > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization."""
        return {
            'logs_processed': self.logs_processed,
            'errors_count': self.errors_count,
            'api_calls': self.api_calls,
            'avg_api_time_ms': round(self.avg_api_time * 1000, 2),
            'min_api_time_ms': (
                round(self.min_api_time * 1000, 2)
                if self.min_api_time != float('inf') else 0.0
            ),
            'max_api_time_ms': round(self.max_api_time * 1000, 2),
            'error_rate_percent': round(self.error_rate, 2),
            'elapsed_time_seconds': round(self.elapsed_time, 2),
            'logs_per_second': round(self.logs_per_second, 3),
            'avg_logs_per_api_call': round(self.avg_logs_per_api_call, 2)
        }


class MailLogger: # pylint: disable=too-many-instance-attributes
    """
    Manages mail event logging from Uzman Posta API.

    Handles API communication, log processing, and file management for both incoming
    and outgoing mail events. Supports incremental logging with position tracking.

    Attributes:
        config: MailLoggerConfig instance containing all settings
        metrics: Metrics instance for tracking runtime statistics
    """

    # Global shutdown event shared across all instances
    _shutdown_event = threading.Event()

    def __init__(self, cfg: MailLoggerConfig) -> None:
        """
        Initialize mail logger with configuration.

        Args:
            config: MailLoggerConfig instance with all required settings
        """
        self.config = cfg
        self.metrics = Metrics()

        # Ensure directories exist
        os.makedirs(self.config.log_directory, exist_ok=True)
        if self.config.position_file:
            os.makedirs(os.path.dirname(os.path.abspath(self.config.position_file)), exist_ok=True)
        if self.config.lock_file_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.config.lock_file_path)), exist_ok=True)

        self._setup_signal_handlers()
        self.setup_logging()

        # Initialize lock attributes for pylint (W0201)
        self.lock_file_path = None
        self.lock_file = None

        # Initialize session and headers
        self.auth_headers = {'Authorization': f'Bearer {self.config.api_key}'}
        self.session = requests.Session() if self.config.use_session else None
        if self.session:
            self.session.headers.update(self.auth_headers)

    def close(self) -> None:
        """Ensure session is closed explicitly."""
        if hasattr(self, 'session') and isinstance(self.session, requests.Session):
            try:
                self.session.close()
                self.log_message("Session closed")
            except Exception: # pylint: disable=broad-exception-caught
                pass

    def _setup_signal_handlers(self) -> None:
        """Configure signal handlers for graceful shutdown (main thread only)."""
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._handle_shutdown)
            signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, _frame: Any) -> None:
        """
        Handle shutdown signals gracefully.

        Args:
            signum: Signal number received
            frame: Current stack frame
        """
        signal_name = 'SIGTERM' if signum == signal.SIGTERM else 'SIGINT'
        self.log_message(f"Received {signal_name}, notifying all instances to shut down...")
        MailLogger._shutdown_event.set()

    @property
    def _shutdown_requested(self) -> bool:
        """Check if shutdown has been requested via the shared event."""
        return MailLogger._shutdown_event.is_set()

    def _parse_api_error(self, response: requests.Response) -> str:
        """
        Parses detailed error information from an API response.

        Args:
            response: The requests.Response object from the failed call

        Returns:
            A formatted string containing status code and detailed error message if available
        """
        status_code = response.status_code
        status_map = {
            403: "Forbidden",
            404: "Not Found",
            406: "Not Acceptable"
        }
        status_text = status_map.get(status_code, response.reason)

        error_details = [f"HTTP {status_code} ({status_text})"]

        try:
            error_json = response.json()
            if isinstance(error_json, dict):
                # Fields to extract from the error body
                fields = ['status', 'code', 'message', 'api-version', 'extended-code-text', 'link']
                details = []
                for fld in fields:
                    if fld in error_json:
                        details.append(f"{fld}: {error_json[fld]}")

                if details:
                    error_details.append(" | ".join(details))
        except (ValueError, TypeError):
            # If body is not JSON, just include the text snippet if short
            if response.text:
                snippet = response.text[:200] + ("..." if len(response.text) > 200 else "")
                error_details.append(f"Response body: {snippet}")

        return " - ".join(error_details)

    def log_message(self, message: str) -> None:
        """
        Log a timestamped message.

        Writes to file if verbose mode is enabled, otherwise prints to console.

        Args:
            message: Text to log
        """
        prefix = f"[{self.config.section_name}] " if self.config.section_name else ""
        if self.config.verbose:
            self.message_logger.info("%s%s", prefix, message)
        else:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{timestamp}] {prefix}{message}")

    def _safe_replace(self, src: str, dst: str, max_retries: int = 5, delay: float = 0.5) -> None:
        """
        Safely replace a file with retries to handle transient 'Access is denied' errors on Windows.

        Args:
            src: Source file path
            dst: Destination file path
            max_retries: Maximum number of retry attempts
            delay: Seconds to wait between retries
        """
        for i in range(max_retries):
            try:
                if os.name == 'nt' and os.path.exists(dst):
                    os.replace(src, dst)
                else:
                    os.rename(src, dst)
                return
            except (PermissionError, OSError) as _e:
                if i == max_retries - 1:
                    raise
                time.sleep(delay)

    def setup_logging(self) -> None:
        """
        Configures logging setup for the application.

        Creates the log directory if it doesn't exist and configures message logging
        when verbose mode is enabled. Raises PermissionError if log directory is not writable.

        Raises:
            PermissionError: If log directory is not writable
        """
        if not os.path.exists(self.config.log_directory):
            os.makedirs(self.config.log_directory)
        elif not os.access(self.config.log_directory, os.W_OK):
            raise PermissionError(f"Log directory '{self.config.log_directory}' is not writable.")

        # Set up a separate logger for general messages only if verbose is True
        # Use a unique name per section to avoid conflicts in parallel mode
        logger_suffix = self.config.section_name or str(id(self))
        if self.config.verbose:
            self.message_logger = logging.getLogger(f'message_logger_{logger_suffix}')
            self.message_logger.setLevel(logging.INFO)
            self.message_logger.propagate = False
            # Prevent handler accumulation
            for handler in self.message_logger.handlers[:]:
                self.message_logger.removeHandler(handler)

            # Create a file handler for the general messages using the configured file name
            # Allow full path and strftime-style date formatting in config
            resolved_filename = datetime.now().strftime(self.config.message_log_file_name)

            # If the resolved path is absolute, use it directly.
            # Otherwise, join it with our structured log directory.
            if os.path.isabs(resolved_filename):
                message_log_file_path = resolved_filename
            else:
                message_log_file_path = os.path.join(self.config.log_directory, resolved_filename)

            message_dir = os.path.dirname(message_log_file_path)
            if message_dir and not os.path.exists(message_dir):
                os.makedirs(message_dir, exist_ok=True)

            message_file_handler = logging.FileHandler(message_log_file_path, encoding='utf-8')
            message_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))

            # Add the handler to the message logger
            self.message_logger.addHandler(message_file_handler)

            # Cleanup old message logs and log actions into the message logger
            self.cleanup_old_message_logs(retention_count=self.config.message_log_retention_count)

        # Initialize an email logger instance attribute
        self.email_logger = logging.getLogger(f'email_logger_{logger_suffix}')
        self.email_logger.setLevel(logging.INFO)
        self.email_logger.propagate = False

        # Cleanup old error logs
        self.cleanup_old_error_logs(retention_count=self.config.error_log_retention_count)

    def cleanup_old_message_logs(self, retention_count: int = 2) -> None:
        """
        Deletes old message log files keeping only the most recent `retention_count` files.

        Args:
            retention_count: Number of recent log files to keep
        """
        # If the configured message log name does not contain any date directives,
        # we cannot safely infer per-period filenames for cleanup.
        pattern = self.config.message_log_file_name
        has_date_tokens = any(tok in pattern for tok in ("%Y", "%y", "%m", "%d", "%H", "%M", "%S"))
        if not has_date_tokens:
            if hasattr(self, "message_logger"):
                self.message_logger.info(
                    "message_log_retention_count is set but message_log_file_name has no "
                    "date/time tokens; skipping old message log cleanup."
                )
            return

        # Build directory and filename pattern from the configured template
        resolved_path = datetime.now().strftime(pattern)
        message_dir = os.path.dirname(resolved_path) or self.config.log_directory
        if not os.path.isdir(message_dir):
            return

        # Use only the filename part for strptime (directory is handled separately)
        filename_pattern = os.path.basename(pattern)

        parsed_files: List[Tuple[datetime, str]] = []
        for fname in os.listdir(message_dir):
            # Try to parse the filename according to the configured pattern
            try:
                file_dt = datetime.strptime(fname, filename_pattern)
            except ValueError:
                # Skip files that don't match the pattern
                continue
            parsed_files.append((file_dt, fname))

        # Eğer dosya sayısı retention_count'tan az veya eşitse, silinecek bir şey yok
        if len(parsed_files) <= retention_count:
            return

        # Tarih-saat sırasına göre eski->yeni sırala
        parsed_files.sort(key=lambda x: x[0])
        # Sadece son retention_count dosya kalsın, geri kalanlar silinsin
        files_to_delete = parsed_files[:-retention_count]

        for _, fname in files_to_delete:
            try:
                os.remove(os.path.join(message_dir, fname))
                if hasattr(self, "message_logger"):
                    self.message_logger.info("Removed old message log: %s", fname)
            except Exception as _e: # pylint: disable=broad-exception-caught
                self.log_error(f"Failed to delete old message log {fname}: {_e}")

    def cleanup_old_error_logs(self, retention_count: int = 2) -> None:
        """
        Deletes old error log files keeping only the most recent `retention_count` files.

        Args:
            retention_count: Number of recent log files to keep
        """
        pattern = self.config.error_log_file_name
        has_date_tokens = any(tok in pattern for tok in ("%Y", "%y", "%m", "%d", "%H", "%M", "%S"))
        if not has_date_tokens:
            return

        # Build directory and filename pattern
        _unused_path = datetime.now().strftime(pattern)
        # Handle relative/absolute paths
        if os.path.isabs(pattern):
            error_dir = os.path.dirname(pattern)
            filename_pattern = os.path.basename(pattern)
        else:
            error_dir = self.config.log_directory
            filename_pattern = pattern

        if not os.path.isdir(error_dir):
            return

        parsed_files: List[Tuple[datetime, str]] = []
        for fname in os.listdir(error_dir):
            try:
                file_dt = datetime.strptime(fname, filename_pattern)
            except ValueError:
                continue
            parsed_files.append((file_dt, fname))

        if len(parsed_files) <= retention_count:
            return

        parsed_files.sort(key=lambda x: x[0])
        files_to_delete = parsed_files[:-retention_count]

        for _, fname in files_to_delete:
            try:
                os.remove(os.path.join(error_dir, fname))
                if hasattr(self, "message_logger"):
                    self.message_logger.info("Removed old error log: %s", fname)
            except (OSError, IOError):
                pass

    def generate_log_file_name(self) -> str:
        """
        Generates log file name based on configured format and current timestamp.

        Returns:
            Generated log file path

        Raises:
            ValueError: If log file name format is invalid
        """
        try:
            filename_format = self.config.log_file_name_format
            # Replace placeholders
            display_domain = self.config.domain if self.config.domain else 'global'
            filename_format = filename_format.replace('{domain}', display_domain)
            # For authentication, use 'auth' instead of the default log_type
            type_value = (
                'auth' if self.config.api_category == 'authentication'
                else self.config.log_type
            )
            filename_format = filename_format.replace('{type}', type_value)

            return os.path.join(self.config.log_directory, datetime.now().strftime(filename_format))
        except ValueError as e:
            self.log_error(f"Invalid log file name format: {e}")
            self.log_message("Using default log file name due to invalid format.")
            return os.path.join(self.config.log_directory, "default_log.json")

    def save_last_position(self, endtime: int) -> None:
        """
        Saves the last processed timestamp to position file atomically.

        Uses write-to-temp-then-rename pattern to ensure crash safety.
        If process crashes during write, the old position file remains intact.

        Args:
            endtime: Unix timestamp of last processed position

        Raises:
            PermissionError: If position directory is not writable
            IOError: If unable to write to position file
        """
        # Support both relative filenames and explicit directories
        position_dir = os.path.dirname(self.config.position_file)
        if position_dir:
            os.makedirs(position_dir, exist_ok=True)
        else:
            position_dir = '.'  # current directory

        if not os.access(position_dir, os.W_OK):
            raise PermissionError(f"Position file directory '{position_dir}' is not writable.")

        # Atomic write: write to temp file, then rename
        temp_file = f"{self.config.position_file}.tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as file:
                file.write(str(endtime))
                # Ensure all buffers are flushed to OS
                file.flush()
                os.fsync(file.fileno())

            # Use safe replace with retries for Windows robustness
            self._safe_replace(temp_file, self.config.position_file)

        except (IOError, PermissionError, OSError) as e:
            self.log_error(f"Failed to save last position (timestamp={endtime}): {e}")
            # Clean up temp file if it exists
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception: # pylint: disable=broad-exception-caught
                    pass

    def load_last_position(self) -> Optional[int]:
        """
        Loads the last processed timestamp from position file.

        Returns:
            Last processed timestamp, or None if position file doesn't exist

        Raises:
            PermissionError: If position file is not readable
            IOError: If unable to read position file
        """
        if os.path.exists(self.config.position_file):
            if not os.access(self.config.position_file, os.R_OK):
                raise PermissionError(
                    f"Position file '{self.config.position_file}' is not readable.")
            try:
                with open(self.config.position_file, 'r', encoding='utf-8') as file:
                    return int(file.read().strip())
            except IOError as e:
                self.log_error(f"Failed to load last position: {e}")
        return None

    def update_heartbeat(self, status: str = "running") -> None:
        """
        Updates heartbeat file with current status and metrics.

        Args:
            status: Current status string (running, completed, error)
        """
        heartbeat_path = os.path.join(self.config.log_directory, self.config.heartbeat_file)
        data = {
            "last_update": datetime.now().isoformat(),
            "status": status,
            "metrics": self.metrics.to_dict()
        }
        try:
            with open(heartbeat_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            self.log_error(f"Failed to update heartbeat: {e}")

    def retrieve_logs(self, starttime: int, endtime: int, retries: Optional[int] = None,
                      sleep_time: Optional[int] = None, chunk_size: int = 500) -> int:
        """
        Retrieves mail logs from API within specified time range.

        Handles API-imposed page limits by iteratively splitting the time range
        if a request returns the maximum batch size (e.g., 1000). Implements
        exponential backoff for transient failures.

        Args:
            starttime: Start time for log retrieval (Unix timestamp)
            endtime: End time for log retrieval (Unix timestamp)
            retries: Maximum number of retry attempts
            sleep_time: Seconds to wait between retries
            chunk_size: Number of logs to process before writing to disk

        Returns:
            Total number of logs processed

        Raises:
            requests.exceptions.RequestException: If API request fails
            ValueError: If response JSON is invalid
        """
        effective_start = self.load_last_position() or starttime
        intervals: List[Tuple[int, int]] = [(effective_start, endtime)]
        buffer: List[Dict[str, Any]] = []
        total_processed = 0
        last_processed_time = effective_start

        retries = retries or self.config.list_retries
        sleep_time = sleep_time or self.config.list_sleep_time

        while intervals:
            # Check for shutdown request
            if self._shutdown_requested:
                self.log_message("Shutdown requested, saving position and exiting...")
                if buffer:
                    self.process_logs(buffer)
                self.save_last_position(last_processed_time)
                break

            s, e = intervals.pop()
            count_all = 0 # Track if we successfully got data for this interval

            # Category-specific parameters
            params = {
                'starttime': s,
                'endtime': e,
            }
            # Only include 'type' for categories that use it (mail, quarantine)
            if self.config.api_category != 'authentication':
                params['type'] = self.config.log_type
            if self.config.domain:
                params['domain'] = self.config.domain

            self.log_message(
                f"Retrieving logs for category '{self.config.api_category}' with params: {params}")

            attempt = 0
            is_successful = False
            while attempt < retries:
                if self._shutdown_requested:
                    break

                try:
                    self.log_message(
                        f"Attempt {attempt + 1} to retrieve mail logs for range [{s}, {e}]")

                    # Track API timing
                    api_start = time.perf_counter()
                    # Use session if enabled, otherwise direct request with headers
                    if self.session:
                        response = self.session.get(
                            self.config.url, params=params, timeout=self.config.list_timeout)
                    else:
                        response = requests.get(
                            self.config.url, headers=self.auth_headers, params=params,
                            timeout=self.config.list_timeout)
                    api_elapsed = time.perf_counter() - api_start
                    self.metrics.record_api_call(api_elapsed)

                    response.raise_for_status()
                    try:
                        data = response.json()
                    except ValueError:
                        self.log_error(
                            f"JSON decode error: {response.text}", request_info=response.url)
                        raise
                    count_all = len(data)
                    self.log_message(f"Retrieved {count_all} logs for range [{s}, {e}]")

                    # If page is full, split the interval iteratively
                    if count_all >= self.config.max_records_per_page and e - s > 1:
                        mid = (s + e) // 2
                        self.log_message(
                            f"Max page size reached; splitting into [{s}, {mid}] and [{mid}, {e}]")
                        intervals.append((mid, e))
                        intervals.append((s, mid))
                        break  # move to next interval from stack

                    total_jobs_in_page = 0
                    # List of (type, data) where type is 'log' or 'job' (with index)
                    processing_sequence = []
                    job_details = [] # List of (queue_id, time)

                    # Prepare sequence in chronological order
                    if self.config.api_category == 'mail':
                        for item in reversed(data):
                            queue_id = item.get('queue_id')
                            recipients = item.get('recipients', [])

                            if queue_id and recipients:
                                recipient = recipients[0]
                                queue_id_time = recipient.get('time')
                                if queue_id_time:
                                    processing_sequence.append(('job', len(job_details)))
                                    job_details.append((queue_id, queue_id_time))
                                    total_jobs_in_page += 1
                                    continue

                            processing_sequence.append(('log', item))
                    else:
                        # Quarantine / Authentication
                        for item in reversed(data):
                            processing_sequence.append(('log', item))

                    # Process jobs in parallel chunks
                    if job_details:
                        self.log_message(
                            f"Processing {total_jobs_in_page} detailed logs in parallel chunks...")
                        sub_batch_size = max(self.config.max_parallel_details * 5, 50)

                        for i in range(0, total_jobs_in_page, sub_batch_size):
                            if self._shutdown_requested:
                                break

                            chunk_indices = range(i, min(i + sub_batch_size, total_jobs_in_page))
                            chunk_details = [job_details[idx] for idx in chunk_indices]

                            with ThreadPoolExecutor(
                                    max_workers=self.config.max_parallel_details
                            ) as thread_executor:
                                futures = [thread_executor.submit(
                                               self.retrieve_detailed_log, d[0],
                                               d[1]) for d in chunk_details]

                                batch_results = []
                                for batch_future in futures:
                                    try:
                                        batch_results.append(batch_future.result())
                                    except Exception as e:
                                        self.log_error(f"Failed to retrieve detailed log: {e}")
                                        self.metrics.errors_count += 1
                                        raise

                                # Update job_details with actual log data
                                for idx_in_chunk, result_log in enumerate(batch_results):
                                    actual_idx = chunk_indices[idx_in_chunk]
                                    job_details[actual_idx] = result_log

                            # Update progress
                            current_completed = min(i + sub_batch_size, total_jobs_in_page)
                            percent = (current_completed / total_jobs_in_page) * 100
                            self.log_message(
                                f"Progress: {current_completed}/{total_jobs_in_page} "
                                f"({percent:.1f}%)")
                            # Short interruptible breather
                            MailLogger._shutdown_event.wait(0.01)

                    # Now process FULL sequence in order
                    if not self._shutdown_requested:
                        for item_type, content in processing_sequence:
                            if item_type == 'job':
                                item = job_details[content]
                            else:
                                item = content

                            if not item:
                                continue

                            # Extract timestamp for position update
                            item_time = None
                            if self.config.api_category == 'mail':
                                # Mail log structure
                                recipients = item.get('recipients', [])
                                if recipients:
                                    item_time = recipients[0].get('time')
                                elif 'time' in item:
                                    item_time = item.get('time')
                            else:
                                # Use timestamp or time for Quarantine/Auth
                                item_time = item.get('time') or item.get(
                                    'timestamp') or item.get('starttime')

                            if item_time:
                                last_processed_time = item_time

                            buffer.append(item)
                            total_processed += 1
                            self.metrics.logs_processed += 1

                            # Periodically write buffer to disk
                            if len(buffer) >= chunk_size:
                                self.process_logs(buffer)
                                self.save_last_position(last_processed_time)
                                buffer.clear()

                    # Finished this page successfully
                    is_successful = True
                    break

                except requests.exceptions.HTTPError as http_error:
                    attempt += 1
                    self.metrics.errors_count += 1
                    detailed_error = self._parse_api_error(http_error.response)
                    url_with_params = (
                        http_error.response.url if http_error.response is not None
                        else self.config.url
                    )
                    duration_ms = round(api_elapsed * 1000, 2) if 'api_elapsed' in dir() else None

                    # HTTP 429 Rate Limit handling
                    if http_error.response is not None and http_error.response.status_code == 429:
                        retry_after = http_error.response.headers.get('Retry-After')
                        if retry_after:
                            try:
                                wait_seconds = int(retry_after)
                            except ValueError:
                                wait_seconds = 60
                            self.log_error(
                                f"Rate Limited (HTTP 429) for {url_with_params}. "
                                f"Retry-After: {retry_after}s (attempt {attempt})",
                                request_info=url_with_params, duration_ms=duration_ms
                            )
                            if attempt < retries:
                                MailLogger._shutdown_event.wait(wait_seconds)
                            continue

                        self.log_error(
                            f"Rate Limited (HTTP 429) for {url_with_params}. "
                            f"No Retry-After header (attempt {attempt})",
                            request_info=url_with_params, duration_ms=duration_ms
                        )
                        if attempt < retries:
                            delay = min(sleep_time * (2 ** (attempt - 1)), 60)
                            MailLogger._shutdown_event.wait(delay)
                        continue

                    self.log_error(
                        f"API HTTP Error for URL {url_with_params} (attempt {attempt}): "
                        f"{detailed_error}",
                        request_info=url_with_params, duration_ms=duration_ms
                    )
                    if attempt < retries:
                        delay = min(sleep_time * (2 ** (attempt - 1)), 60)
                        MailLogger._shutdown_event.wait(delay)
                except requests.exceptions.RequestException as req_error:
                    attempt += 1
                    self.metrics.errors_count += 1
                    failed_url = getattr(
                        req_error.request, 'url', self.config.url) if hasattr(
                        req_error, 'request') else self.config.url
                    duration_ms = round(api_elapsed * 1000, 2) if 'api_elapsed' in dir() else None

                    # Classify the connection error
                    error_label = self._classify_connection_error(req_error, failed_url)
                    self.log_error(
                        f"{error_label} for {failed_url} (attempt {attempt}): {req_error}",
                        request_info=failed_url, duration_ms=duration_ms
                    )

                    if attempt < retries:
                        delay = min(sleep_time * (2 ** (attempt - 1)), 60)
                        MailLogger._shutdown_event.wait(delay)
                except ValueError:
                    raise
                except Exception as unexpected_error: # pylint: disable=broad-exception-caught
                    self.log_error(
                        f"Unexpected error: {unexpected_error}", request_info=self.config.url)
                    self.save_last_position(last_processed_time)
                    buffer.clear()
                    self.metrics.errors_count += 1
                    raise

            if is_successful:
                # Finished a page or interval portion successfully
                if buffer:
                    self.process_logs(buffer)
                    buffer.clear()
                # Update position to the end of this successful interval/page
                last_processed_time = e
                self.save_last_position(last_processed_time)
            elif not self._shutdown_requested and count_all < self.config.max_records_per_page:
                # If we didn't succeed and it wasn't a split, raise
                raise RuntimeError(
                    f"Failed to retrieve logs for range [{s}, {e}] after {retries} attempts.")

        # Döngü bittikten sonra kalan buffer'ı da yaz
        if buffer:
            self.process_logs(buffer)
            buffer.clear()

        self.save_last_position(last_processed_time)  # Final checkpoint

        self.log_message(
            f"Finished retrieving {self.config.api_category} logs, "
            f"processed {total_processed} items"
        )
        return total_processed

    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    def retrieve_detailed_log(self, queue_id: str, event_time: int, retries: Optional[int] = None,
                             sleep_time: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves detailed log information for specific mail event.

        Fetches extended information for a mail event and removes unnecessary fields.

        Args:
            queue_id: Unique identifier for mail queue
            event_time: Event timestamp
            retries: Maximum number of retry attempts
            sleep_time: Seconds to wait between retries

        Returns:
            Detailed log information with unnecessary fields removed

        Raises:
            Exception: If retrieval fails after maximum retries
        """
        retries = retries or self.config.detail_retries
        sleep_time = sleep_time or self.config.detail_sleep_time
        detailed_log_url = f'{self.config.url}/{queue_id}?time={event_time}'
        attempt = 0
        while attempt < retries:
            try:
                # Track API timing
                api_start = time.perf_counter()
                if self.session:
                    response = self.session.get(
                        detailed_log_url, timeout=self.config.detail_timeout)
                else:
                    response = requests.get(
                        detailed_log_url, headers=self.auth_headers,
                        timeout=self.config.detail_timeout)
                api_elapsed = time.perf_counter() - api_start
                self.metrics.record_api_call(api_elapsed)

                response.raise_for_status()
                try:
                    detailed_log = response.json()
                except ValueError:
                    self.log_error(f"JSON decode error: {response.text}", request_info=response.url)
                    raise
                # Successful retrieval
                # List of fields to remove from the detailed log
                fields_to_remove = ['logs', 'transactions', 'filters', 'emails']

                # Remove specified fields from the detailed log
                for fld in fields_to_remove:
                    if fld in detailed_log:
                        del detailed_log[fld]
                return detailed_log

            except requests.exceptions.HTTPError as http_error:
                attempt += 1
                detailed_error = self._parse_api_error(http_error.response)
                url_with_params = (
                    http_error.response.url if http_error.response is not None
                    else detailed_log_url
                )
                duration_ms = round(api_elapsed * 1000, 2) if 'api_elapsed' in dir() else None

                # HTTP 429 Rate Limit handling
                if http_error.response is not None and http_error.response.status_code == 429:
                    retry_after = http_error.response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_seconds = int(retry_after)
                        except ValueError:
                            wait_seconds = 60
                        self.log_error(
                            f"Rate Limited (HTTP 429) for {url_with_params}. "
                            f"Retry-After: {retry_after}s (attempt {attempt})",
                            request_info=url_with_params, duration_ms=duration_ms
                        )
                        if attempt < retries:
                            MailLogger._shutdown_event.wait(wait_seconds)
                        else:
                            raise
                        continue

                if attempt < retries:
                    MailLogger._shutdown_event.wait(sleep_time)
                else:
                    self.log_error(
                        f"API HTTP Error for URL {url_with_params} after {retries} "
                        f"attempts: {detailed_error}",
                        request_info=url_with_params, duration_ms=duration_ms
                    )
                    raise
            except Exception as detail_error: # pylint: disable=broad-exception-caught
                attempt += 1
                duration_ms = round(api_elapsed * 1000, 2) if 'api_elapsed' in dir() else None
                if attempt < retries:
                    MailLogger._shutdown_event.wait(sleep_time)
                else:
                    # Classify connection errors
                    if isinstance(detail_error, requests.exceptions.RequestException):
                        # Classify the connection error
                        error_label = self._classify_connection_error(
                            detail_error, detailed_log_url)
                        self.log_error(
                            f"{error_label} for {detailed_log_url} after {retries} "
                            f"attempts: {detail_error}",
                            request_info=detailed_log_url, duration_ms=duration_ms
                        )
                    else:
                        self.log_error(
                            f"Failed to retrieve detailed log from {detailed_log_url} "
                            f"after {retries} attempts: {detail_error}",
                            request_info=detailed_log_url, duration_ms=duration_ms
                        )
                    raise
        # This point should be unreachable given the raise/return structure above
        raise RuntimeError(f"Failed to retrieve detailed log from {detailed_log_url}")

    def _mask_api_key(self, api_key: str) -> str:
        """
        Masks the API key for safe logging, showing only first and last 4 characters.

        Args:
            api_key: The full API key

        Returns:
            Masked API key string (e.g., 'abcd...1234')
        """
        if not api_key or len(api_key) <= 8:
            return '***'
        return f"{api_key[:4]}...{api_key[-4:]}"

    def _check_dns(self, url: str) -> bool:
        """
        Verifies if the hostname in the URL can be resolved.

        Args:
            url: The URL to check

        Returns:
            True if hostname resolves or URL is invalid/no hostname, False if DNS resolution fails
        """
        try:
            hostname = urlparse(url).hostname
            if hostname:
                socket.gethostbyname(hostname)
                return True
        except socket.gaierror:
            return False
        except Exception: # pylint: disable=broad-exception-caught
            return True
        return True

    def _classify_connection_error(self, error: Exception, url: str) -> str:
        """
        Classifies a connection error into a human-readable category.

        Args:
            error: The exception to classify
            url: The URL that caused the error

        Returns:
            A descriptive error label string
        """
        error_str = str(error).lower()

        # Check for timeout
        if (isinstance(error, requests.exceptions.Timeout) or
                'timeout' in error_str or 'timed out' in error_str):
            return "Connection Timeout"

        # Check for connection refused
        if isinstance(error, requests.exceptions.ConnectionError):
            if ('connection refused' in error_str or '[errno 111]' in error_str or
                    '[winerror 10061]' in error_str):
                return "Connection Refused"
            # Check for DNS failure
            if not self._check_dns(url):
                return (
                    "DNS Resolution Failed. Please check your internet connection or DNS settings"
                )
            return "Connection Error"

        # Check for SSL errors
        if 'ssl' in error_str or 'certificate' in error_str:
            return "SSL/TLS Error"

        return "Request Error"

    # pylint: disable=too-many-locals
    def log_error(
            self, error_message: str, request_info: Optional[str] = None,
            duration_ms: Optional[float] = None) -> None:
        """
        Logs error messages to file with timestamp.

        Args:
            error_message: Error message to log
            request_info: Optional request URL or information
            duration_ms: Optional request duration in milliseconds
        """
        error_data = {
            "time": int(datetime.now().timestamp()),
            "error": str(error_message),
            "api_key": self._mask_api_key(self.config.api_key),
            "domain": self.config.domain,
            "type": self.config.log_type
        }
        if request_info:
            error_data["request"] = request_info
        if duration_ms is not None:
            error_data["duration_ms"] = duration_ms
        error_json = json.dumps(error_data, ensure_ascii=False)

        # Use timestamped filename if pattern has date tokens
        pattern = self.config.error_log_file_name
        has_date_tokens = any(tok in pattern for tok in ("%Y", "%y", "%m", "%d", "%H", "%M", "%S"))

        if has_date_tokens:
            resolved_filename = datetime.now().strftime(pattern)
            if os.path.isabs(resolved_filename):
                error_log_path = resolved_filename
            else:
                error_log_path = os.path.join(self.config.log_directory, resolved_filename)
        else:
            suffix = f"_{self.config.section_name}" if self.config.section_name else ""
            error_log_path = os.path.join(self.config.log_directory, f'errors{suffix}.log')

        try:
            error_dir = os.path.dirname(error_log_path)
            if error_dir and not os.path.exists(error_dir):
                os.makedirs(error_dir, exist_ok=True)

            with open(error_log_path, 'a', encoding='utf-8') as log_file:
                log_file.write(error_json + "\n")
        except Exception as e: # pylint: disable=broad-exception-caught
            # Fallback to console if file logging fails
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            prefix = f"[{self.config.section_name}] " if self.config.section_name else ""
            print(f"[{timestamp}] {prefix}CRITICAL: Failed to log error to {error_log_path}: {e}")
            print(f"[{timestamp}] {prefix}ORIGINAL ERROR: {error_message}")

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
    def split_and_retrieve_logs(self) -> None:
        """
        Manages log retrieval by splitting time range into manageable intervals.

        Uses `max_time_gap` as the chunk size for each API request. Updates
        position tracking after each successful interval retrieval.
        """
        endtime = int(datetime.now().timestamp())  # Get the current time as Unix timestamp
        self.log_message(
            f"End time: {endtime} ("
            f"{datetime.fromtimestamp(endtime).strftime('%Y-%m-%d %H:%M:%S')})")
        last_position = self.load_last_position()
        if last_position is not None:
            start_time = last_position
        else:
            start_time = self.config.start_time

        self.log_message(
            f"Start time: {start_time} ("
            f"{datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')})")

        # Enforce 7-day limit for quarantine category
        if self.config.api_category == 'quarantine':
            seven_days_ago = int(datetime.now().timestamp()) - (7 * 24 * 60 * 60)
            if start_time < seven_days_ago:
                self.log_message(
                    f"WARNING: Quarantine logs have a 7-day lookback limit. "
                    f"Clipping start_time from "
                    f"{datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')} "
                    f"to {datetime.fromtimestamp(seven_days_ago).strftime('%Y-%m-%d %H:%M:%S')}")
                start_time = seven_days_ago

        # Validate: start_time cannot be greater than end_time
        if start_time >= endtime:
            self.log_message(
                f"WARNING: start_time ({start_time}) is greater than or equal to "
                f"end_time ({endtime}). Skipping log retrieval.")
            return

        time_diff = endtime - start_time
        fourteen_days_seconds = 14 * 24 * 60 * 60
        max_allowed_gap = min(self.config.max_time_gap, fourteen_days_seconds)
        chunk_size = min(self.config.split_interval,
                         max_allowed_gap) if self.config.split_interval else max_allowed_gap

        self.log_message(
            f"Starting {self.config.api_category} log retrieval from {start_time} to {endtime}")

        total_processed = 0

        # If the time difference exceeds the maximum allowed gap,
        # split the request into smaller intervals
        if time_diff > chunk_size:
            current_time = start_time
            # Split the time range into intervals and fetch logs for each interval
            while current_time < endtime:
                if self._shutdown_requested:
                    self.log_message("Shutdown requested during interval processing")
                    break

                # Use configured chunk size but never exceed the allowed gap
                next_time = min(current_time + chunk_size, endtime)
                self.log_message(
                    f"Fetching {self.config.api_category} logs from {current_time} to {next_time}")
                # Logs are streamed and written inside retrieve_logs
                processed = self.retrieve_logs(current_time, next_time)
                total_processed += processed
                self.update_heartbeat()  # Update heartbeat after each interval
                current_time = next_time  # Update the current time for the next interval
        else:
            # If the time difference is small enough, fetch the logs in a single request
            self.log_message(
                f"Fetching {self.config.api_category} logs from {start_time} to {endtime}")
            # Logs are streamed and written inside retrieve_logs
            processed = self.retrieve_logs(start_time, endtime)
            total_processed += processed
            self.update_heartbeat()  # Update heartbeat

        # Özet bilgi
        self.log_message(
            f"Summary: processed {total_processed} logs between "
            f"{datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')} and "
            f"{datetime.fromtimestamp(endtime).strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def acquire_lock(self, lock_file_path: str) -> None:
        """
        Acquires process lock to prevent multiple instances.

        Implements cross-platform file locking mechanism.

        Args:
            lock_file_path: Path to lock file

        Raises:
            IOError: If another instance is already running
        """
        self.lock_file_path = lock_file_path
        # Use open() directly because the lock must remain held for the process lifetime
        self.lock_file = open(  # pylint: disable=consider-using-with
            self.lock_file_path, 'w', encoding='utf-8')
        try:
            if os.name == 'nt':
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.log_message("Lock acquired")
        except IOError:
            self.log_message("Another instance is already running.")
            self.lock_file.close()  # Ensure the file is closed if an error occurs
            sys.exit(1)

    def release_lock(self) -> None:
        """
        Releases process lock and removes lock file.

        Handles both Windows and Unix lock mechanisms.

        Raises:
            Exception: If error occurs while releasing lock
        """
        if not hasattr(self, 'lock_file'):
            return
        try:
            if self.lock_file and not self.lock_file.closed:
                if os.name == 'nt':
                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self.lock_file, fcntl.LOCK_UN)
                self.lock_file.close()
                os.remove(self.lock_file_path)  # Use the stored lock file path
                # Just print to console, don't log to file
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                prefix = f"[{self.config.section_name}] " if self.config.section_name else ""
                print(f"[{timestamp}] {prefix}Lock released")
        except Exception as e:
            self.log_error(f"Error releasing lock: {e}", request_info=self.lock_file_path)
            raise

    def process_logs(self, logs: List[Dict[str, Any]]) -> None:
        """
        Processes and saves retrieved logs to file.

        Configures logging for email data and ensures proper encoding.

        Args:
            logs: List of log entries to process
        """
        log_file_name = self.generate_log_file_name()

        # Email logger configuration - only for email logs
        # Use instance email_logger to align with log_email()
        email_logger = self.email_logger
        # Configure handler for email logs
        email_handler = logging.FileHandler(log_file_name, encoding='utf-8')
        email_handler.setFormatter(logging.Formatter('%(message)s'))

        # Remove any existing handlers to prevent duplicate logging
        for handler in email_logger.handlers[:]:
            email_logger.removeHandler(handler)

        email_logger.addHandler(email_handler)

        # Save only the email logs
        for item in logs:
            if isinstance(item, dict):  # Only save email logs
                email_logger.info(json.dumps(item, ensure_ascii=False))

        # Remove and close the handler after we're done to avoid descriptor leaks
        email_logger.removeHandler(email_handler)
        email_handler.close()

    def log_metrics_summary(self) -> None:
        """Logs a summary of collected metrics."""
        metrics = self.metrics.to_dict()
        self.log_message("=== Metrics Summary ===")
        self.log_message(f"  Logs processed: {metrics['logs_processed']}")
        self.log_message(f"  Errors: {metrics['errors_count']} ({metrics['error_rate_percent']}%)")
        self.log_message(f"  API calls: {metrics['api_calls']}")
        self.log_message(f"  Avg API time: {metrics['avg_api_time_ms']}ms")
        self.log_message(f"  Min API time: {metrics['min_api_time_ms']}ms")
        self.log_message(f"  Max API time: {metrics['max_api_time_ms']}ms")
        self.log_message(f"  Throughput: {metrics['logs_per_second']} logs/sec")
        self.log_message(f"  Logs per API call: {metrics['avg_logs_per_api_call']}")
        self.log_message(f"  Total elapsed: {metrics['elapsed_time_seconds']}s")
        self.log_message("=======================")

    def run(self) -> None:
        """
        Executes main log retrieval and processing workflow.

        Orchestrates the entire logging process including retrieval,
        processing, and error handling.

        Raises:
            Exception: If any error occurs during execution
        """
        try:
            self.update_heartbeat("running")
            self.split_and_retrieve_logs()
            self.log_metrics_summary()
            self.update_heartbeat("completed")
        except Exception as e: # pylint: disable=broad-exception-caught
            self.log_error(f"Error during execution: {e}")
            self.update_heartbeat("error")
            raise


def discover_sections(cfg: configparser.ConfigParser) -> List[str]:
    """Find all [MailLogger:*] sections in config."""
    return [s for s in cfg.sections() if s.startswith('MailLogger:')]


def get_section_suffix(section_name: str) -> str:
    """Extract suffix from section name for file naming."""
    if ':' in section_name:
        return section_name.split(':', 1)[1]
    return 'default'


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def create_config_for_section(
        cfg: configparser.ConfigParser,
        section_name: str) -> Tuple[MailLoggerConfig, str]:
    """Create MailLoggerConfig from a config section."""
    suffix = get_section_suffix(section_name)

    # Establish script directory for relative path resolution
    sect_script_dir = os.path.dirname(os.path.abspath(__file__))

    # Read values with fallbacks from DEFAULT section
    api_key = cfg.get(section_name, 'api_key')

    # Validate: API key cannot be empty
    if not api_key or api_key.strip() == '' or api_key == 'YOUR_API_KEY_HERE':
        raise ValueError(
            f"Section {section_name}: 'api_key' is required and "
            f"cannot be empty or placeholder.")

    domain = cfg.get(section_name, 'domain', fallback='')
    log_type = cfg.get(section_name, 'type', fallback='outgoinglog')
    api_category = cfg.get(section_name, 'category', fallback='mail')

    # Determine URL based on category
    default_urls = {
        'mail': 'https://yenipanel-api.uzmanposta.com/api/v2/logs/mail',
        'quarantine': 'https://yenipanel-api.uzmanposta.com/api/v2/quarantines',
        'authentication': 'https://yenipanel.uzmanposta.com/api/v2/logs/authentication'
    }

    # Priority:
    # 1. Explicitly set in the SECTION itself (ignore DEFAULT)
    # 2. Category-specific default
    # 3. If category is 'mail' (default), then fallback to [DEFAULT] section's 'url' if any

    url = None
    # Check if URL is locally defined in this section
    if cfg.has_section(section_name) and cfg.has_option(section_name, 'url'):
        url = cfg.get(section_name, 'url')

    if not url:
        # Use category default
        url = default_urls.get(api_category, default_urls['mail'])

        # Special case for 'mail' category: allow [DEFAULT] url for backward compatibility
        if api_category == 'mail' and cfg.has_option('DEFAULT', 'url'):
            url = cfg.get('DEFAULT', 'url')

    # Log resolution detail for diagnostics
    print(
        f"--- CONFIG DEBUG --- Section: {section_name} -> "
        f"Category: {api_category}, URL: {url}")

    if log_type in ['quarantine', 'hold'] and api_category == 'mail':
        print(
            f"WARNING: Section {section_name} has type '{log_type}' but "
            f"category is 'mail'. Did you forget 'category = quarantine'?")

    # Resolve log directory: if relative, make it relative to script_dir
    raw_log_dir = cfg.get(section_name, 'log_directory', fallback='./output')
    if not os.path.isabs(raw_log_dir):
        base_log_dir = os.path.abspath(os.path.join(sect_script_dir, raw_log_dir))
    else:
        base_log_dir = raw_log_dir

    # Construct detailed log directory: base/domain/category/type
    # If domain is empty (auth/quarantine might be global), use 'global'
    display_domain = domain if domain else 'global'

    # For authentication category, skip the type subdirectory since it's not applicable
    # For quarantine, skip if type equals category to avoid quarantine/quarantine
    if api_category == 'authentication':
        log_directory = os.path.join(base_log_dir, display_domain, api_category)
    elif api_category == 'quarantine' and log_type == 'quarantine':
        # Avoid redundant quarantine/quarantine path
        log_directory = os.path.join(base_log_dir, display_domain, api_category)
    else:
        # mail category always uses type, quarantine with 'hold' type uses subdirectory
        log_directory = os.path.join(base_log_dir, display_domain, api_category, log_type)

    # Generate stable instance id for this section
    unique_id_string = f"{api_key}{domain}{log_type}{api_category}{url}"
    section_hash = hashlib.md5(unique_id_string.encode('utf-8')).hexdigest()[:8]

    # Anchor positions and locks to script directory as well
    positions_dir = os.path.join(sect_script_dir, 'positions')
    locks_dir = os.path.join(sect_script_dir, 'locks')

    # Position file: use config value or auto-generate
    position_file_config = cfg.get(section_name, 'position_file', fallback=None)
    if position_file_config:
        if "{id}" in position_file_config:
            res_pos = position_file_config.replace("{id}", section_hash)
        elif "{section}" in position_file_config:
            res_pos = position_file_config.replace("{section}", suffix)
        else:
            res_pos = position_file_config

        # Ensure absolute path
        if not os.path.isabs(res_pos):
            position_file = os.path.abspath(os.path.join(sect_script_dir, res_pos))
        else:
            position_file = res_pos
    else:
        position_file = os.path.join(positions_dir, f"{suffix}.pos")

    # Lock file: use config value or auto-generate
    lock_file_config = cfg.get(section_name, 'lock_file_path', fallback=None)
    if lock_file_config:
        if "{id}" in lock_file_config:
            res_lock = lock_file_config.replace("{id}", section_hash)
        elif "{section}" in lock_file_config:
            res_lock = lock_file_config.replace("{section}", suffix)
        else:
            res_lock = lock_file_config

        # Ensure absolute path
        if not os.access(res_lock, os.F_OK) and not os.path.isabs(res_lock):
            lock_file_path = os.path.abspath(os.path.join(sect_script_dir, res_lock))
        else:
            lock_file_path = res_lock
    else:
        lock_file_path = os.path.join(locks_dir, f"{suffix}.lock")

    # Heartbeat file: use config value or auto-generate
    heartbeat_file_config = cfg.get(section_name, 'heartbeat_file', fallback=None)
    if heartbeat_file_config:
        if "{section}" in heartbeat_file_config:
            res_hb = heartbeat_file_config.replace("{section}", suffix)
        else:
            res_hb = heartbeat_file_config

        heartbeat_file = res_hb
    else:
        heartbeat_file = f"{suffix}_heartbeat.json"

    # Create config dataclass
    mail_config = MailLoggerConfig(
        api_key=api_key, log_directory=log_directory, log_file_name_format=cfg.get(
            section_name, 'log_file_name_format', fallback='{domain}_{type}_%Y-%m-%d_%H.log'),
        position_file=position_file,
        start_time=max(
            0, cfg.getint(
                section_name, 'start_time', fallback=int(datetime.now().timestamp()) - 60)),
        domain=domain, url=url, log_type=log_type, api_category=api_category,
        split_interval=cfg.getint(section_name, 'split_interval', fallback=300),
        max_time_gap=cfg.getint(section_name, 'max_time_gap', fallback=3600),
        verbose=cfg.getboolean(section_name, 'verbose', fallback=True),
        message_log_file_name=cfg.get(
            section_name, 'message_log_file_name', fallback='messages_%Y-%m-%d_%H.log'),
        message_log_retention_count=cfg.getint(
            section_name, 'message_log_retention_count', fallback=2),
        list_timeout=cfg.getint(section_name, 'list_timeout', fallback=300),
        detail_timeout=cfg.getint(section_name, 'detail_timeout', fallback=120),
        list_retries=cfg.getint(section_name, 'list_retries', fallback=10),
        list_sleep_time=cfg.getint(section_name, 'list_sleep_time', fallback=2),
        detail_retries=cfg.getint(section_name, 'detail_retries', fallback=10),
        detail_sleep_time=cfg.getint(section_name, 'detail_sleep_time', fallback=2),
        max_records_per_page=cfg.getint(
            section_name, 'max_records_per_page', fallback=1000),
        heartbeat_file=heartbeat_file, lock_file_path=lock_file_path, section_name=suffix,
        max_parallel_details=cfg.getint(section_name, 'max_parallel_details', fallback=2),
        use_session=cfg.getboolean(section_name, 'use_session', fallback=True),
        error_log_file_name=cfg.get(
            section_name, 'error_log_file_name', fallback='errors_%Y-%m-%d_%H.log'),
        error_log_retention_count=cfg.getint(
            section_name, 'error_log_retention_count', fallback=2),)

    return mail_config, lock_file_path


def run_section(cfg: configparser.ConfigParser, section_name: str) -> bool:
    """Run a single section. Returns True if successful, False if skipped/failed."""
    try:
        mail_config, lock_file_path = create_config_for_section(cfg, section_name)

        # Ensure directories exist (thread-safe)
        for dir_path in ['./positions', './locks', mail_config.log_directory]:
            os.makedirs(dir_path, exist_ok=True)

        print(f"[{get_section_suffix(section_name)}] Starting...")
        print(f"[{get_section_suffix(section_name)}] Lock file: {lock_file_path}")

        mail_logger = MailLogger(mail_config)
        mail_logger.acquire_lock(lock_file_path)
        try:
            mail_logger.run()
            return True
        finally:
            mail_logger.close()
            mail_logger.release_lock()

    except SystemExit:
        # Lock already held by another instance
        print(f"[{get_section_suffix(section_name)}] Skipped (already running)")
        return False
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"[{get_section_suffix(section_name)}] Error: {e}")
        return False


def main() -> None:
    """Main entry point for Uzman Posta Mail Event Logger."""
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Uzman Posta Mail Event Logger')
    parser.add_argument('--config', default='uzmanposta.ini',
                        help='Config file path (default: uzmanposta.ini)')
    parser.add_argument(
        '--section', help='Specific section to run (e.g., MailLogger:domain-incoming)')
    parser.add_argument('--all', action='store_true', help='Run all configured sections')
    parser.add_argument('--parallel', action='store_true',
                        help='Run sections in parallel (requires --all)')
    parser.add_argument(
        '--max-workers', type=int, default=5,
        help='Maximum number of parallel workers (default: 5)')
    parser.add_argument('--list', action='store_true', help='List all available sections and exit')
    args = parser.parse_args()

    # Establish script directory for path resolution
    script_directory = os.path.dirname(os.path.abspath(__file__))

    # Check if config file exists
    config_file = args.config
    if not os.path.isabs(config_file):
        config_file = os.path.abspath(os.path.join(script_directory, config_file))

    if not os.path.exists(config_file):
        print(f"Configuration file '{config_file}' not found.")
        sys.exit(1)

    # Load configuration from file
    cfg_parser = configparser.ConfigParser(interpolation=None)
    cfg_parser.read(config_file, encoding='utf-8-sig')

    # Discover available sections
    multi_sections = discover_sections(cfg_parser)
    has_legacy_section = cfg_parser.has_section('MailLogger')

    # --list: Show available sections and exit
    if args.list:
        print("Available sections:")
        if has_legacy_section:
            print("  - MailLogger (legacy)")
        for section in multi_sections:
            print(f"  - {section}")
        sys.exit(0)

    # Determine which sections to run
    sections_to_run: List[str] = []

    if args.section:
        # Run specific section
        if args.section in cfg_parser.sections():
            sections_to_run = [args.section]
        else:
            print(f"Section '{args.section}' not found in config.")
            available_sections = (
                ', '.join(multi_sections) if multi_sections else 'MailLogger (legacy)'
            )
            print("Available: " + available_sections)
            sys.exit(1)
    elif args.all:
        # Run all MailLogger:* sections
        if multi_sections:
            sections_to_run = multi_sections
        else:
            print("No MailLogger:* sections found. Use --section MailLogger for legacy mode.")
            sys.exit(1)
    else:
        # Default behavior: legacy single section or auto-detect
        if has_legacy_section and not multi_sections:
            sections_to_run = ['MailLogger']
        elif multi_sections and not has_legacy_section:
            # Auto-run all if only multi-sections exist
            sections_to_run = multi_sections
            print(f"Found {len(multi_sections)} sections, running all...")
        elif multi_sections:
            print("Multiple section types found. Please specify:")
            print("  --all              Run all MailLogger:* sections")
            print("  --section NAME     Run specific section")
            print("\nAvailable sections:")
            for section in multi_sections:
                print(f"  - {section}")
            sys.exit(1)
        else:
            print("No MailLogger sections found in config.")
            sys.exit(1)

    # Run sections
    results = {'success': 0, 'skipped': 0, 'failed': 0}

    try:
        if args.parallel and len(sections_to_run) > 1:
            # Parallel execution using ThreadPoolExecutor
            # Limit workers to prevent API throttling
            actual_workers = min(len(sections_to_run), args.max_workers)
            print(
                f"Running {len(sections_to_run)} sections in parallel with "
                f"{actual_workers} workers... (Press Ctrl+C to stop)"
            )
            with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                future_to_section = {
                    executor.submit(run_section, cfg_parser, section): section
                    for section in sections_to_run
                }
                try:
                    for future in as_completed(future_to_section):
                        section = future_to_section[future]
                        try:
                            is_success = future.result()
                            if is_success:
                                results['success'] += 1
                            else:
                                results['skipped'] += 1
                        except Exception as e: # pylint: disable=broad-exception-caught
                            print(f"[{get_section_suffix(section)}] Thread error: {e}")
                            results['failed'] += 1
                except KeyboardInterrupt:
                    print("\nMain thread received Ctrl+C, notifying workers...")
                    MailLogger._shutdown_event.set()  # pylint: disable=protected-access
                    # Wait for threads to finish
                    executor.shutdown(wait=True)
        else:
            # Sequential execution
            for section in sections_to_run:
                if MailLogger._shutdown_event.is_set():  # pylint: disable=protected-access
                    break
                is_success = run_section(cfg_parser, section)
                if is_success:
                    results['success'] += 1
                else:
                    results['skipped'] += 1
    except KeyboardInterrupt:
        print("\nShutdown requested via Ctrl+C")
        MailLogger._shutdown_event.set()  # pylint: disable=protected-access

    # Print summary if multiple sections
    if len(sections_to_run) > 1:
        print("\n=== Summary ===")
        print(f"  Completed: {results['success']}/{len(sections_to_run)}")
        print(f"  Skipped:   {results['skipped']}")
        if results['failed'] > 0:
            print(f"  Failed:    {results['failed']}")


if __name__ == "__main__":
    main()
