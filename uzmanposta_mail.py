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

import os
import sys
import json
import configparser
import logging
import argparse
from datetime import datetime
import time
import requests

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


class MailLogger:
    """
    Manages mail event logging from Uzman Posta API.

    Handles API communication, log processing, and file management for both incoming
    and outgoing mail events. Supports incremental logging with position tracking.

    Attributes:
        api_key: Authentication key for Uzman Posta API
        log_directory: Directory for storing log files
        log_file_name_format: strftime format for log filenames
        position_file: File tracking last processed timestamp
        start_time: Initial timestamp for log retrieval
        domain: Email domain to filter logs
        url: Uzman Posta API endpoint
        log_type: Type of logs to retrieve ('incominglog'/'outgoinglog')
        split_interval: Time window for splitting API requests (seconds)
        max_time_gap: Maximum allowed time range per request (seconds)
        verbose: Enable detailed logging
        message_log_file_name: Filename for verbose logs
    """

    def __init__(self, api_key, log_directory, log_file_name_format, position_file, start_time, domain, url, log_type='outgoinglog', split_interval=300, max_time_gap=3600, verbose=False,  message_log_file_name='messages.log'):
        """
        Initialize mail logger with configuration parameters.

        Args:
            api_key: Authentication key for API access
            log_directory: Directory path for log storage
            log_file_name_format: strftime format for log files
            position_file: Path to position tracking file
            start_time: Unix timestamp to start log collection
            domain: Email domain filter
            url: API endpoint URL
            log_type: Log category to retrieve (default: 'outgoinglog')
            split_interval: Request window size in seconds (default: 300)
            max_time_gap: Maximum time range per request in seconds (default: 3600)
            verbose: Enable detailed logging (default: False)
            message_log_file_name: Filename for verbose logs (default: 'messages.log')
        """
        self.api_key = api_key
        self.log_directory = log_directory
        self.log_file_name_format = log_file_name_format
        self.position_file = position_file
        self.start_time = start_time
        self.domain = domain
        self.url = url
        self.log_type = log_type
        self.split_interval = split_interval  # The time interval for splitting requests (e.g., 300 seconds = 5 minutes)
        self.max_time_gap = max_time_gap  # The maximum allowed gap between the start and end time (in seconds)
        self.verbose = verbose  # Add verbose flag
        self.message_log_file_name = message_log_file_name

        self.setup_logging()

    def log_message(self,message):
        """
        Log a timestamped message.

        Writes to file if verbose mode is enabled, otherwise prints to console.

        Args:
            message: Text to log
        """
        if self.verbose:
            self.message_logger.info(message)
        else:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{timestamp}] {message}")

    def log_email(self, email_data):
        """
        Log email data with timestamp.

        Args:
            email_data: Email event data to log
        """
        self.email_logger.info(email_data)

    def setup_logging(self):
        """
        Configures logging setup for the application.

        Creates the log directory if it doesn't exist and configures message logging
        when verbose mode is enabled. Raises PermissionError if log directory is not writable.

        Raises:
            PermissionError: If log directory is not writable
        """
        if not os.path.exists(self.log_directory):
                os.makedirs(self.log_directory)
        elif not os.access(self.log_directory, os.W_OK):
            raise PermissionError(f"Log directory '{self.log_directory}' is not writable.")

           # Set up a separate logger for general messages only if verbose is True
        if self.verbose:
            self.message_logger = logging.getLogger('message_logger')
            self.message_logger.setLevel(logging.INFO)
            
            # Create a file handler for the general messages using the configured file name
            message_log_file_path = os.path.join(self.log_directory, self.message_log_file_name)
            message_file_handler = logging.FileHandler(message_log_file_path, encoding='utf-8')
            message_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
            
            # Add the handler to the message logger
            self.message_logger.addHandler(message_file_handler)

    def generate_log_file_name(self):
        """
        Generates log file name based on configured format and current timestamp.

        Returns:
            str: Generated log file path

        Raises:
            ValueError: If log file name format is invalid
        """
        try:
            return os.path.join(self.log_directory, datetime.now().strftime(self.log_file_name_format))
        except ValueError as e:
            self.log_error(f"Invalid log file name format: {e}")
            self.log_message("Using default log file name due to invalid format.")
            return os.path.join(self.log_directory, "default_log.json")

    def save_last_position(self, endtime):
        """
        Saves the last processed timestamp to position file.

        Creates position directory if it doesn't exist.

        Args:
            endtime: Unix timestamp of last processed position

        Raises:
            PermissionError: If position directory is not writable
            IOError: If unable to write to position file
        """
        position_dir = os.path.dirname(self.position_file)
        if not os.path.exists(position_dir):
            os.makedirs(position_dir)
        if not os.access(position_dir, os.W_OK):
            raise PermissionError(f"Position file directory '{position_dir}' is not writable.")
        
        try:
            with open(self.position_file, 'w', encoding='utf-8') as file:
                file.write(str(endtime))
        except IOError as e:
            self.log_error(f"Failed to save last position: {e}")

    def load_last_position(self):
        """
        Loads the last processed timestamp from position file.

        Returns:
            int: Last processed timestamp, or None if position file doesn't exist

        Raises:
            PermissionError: If position file is not readable
            IOError: If unable to read position file
        """
        if os.path.exists(self.position_file):
            if not os.access(self.position_file, os.R_OK):
                raise PermissionError(f"Position file '{self.position_file}' is not readable.")
            try:
                with open(self.position_file, 'r', encoding='utf-8') as file:
                    return int(file.read().strip())
            except IOError as e:
                self.log_error(f"Failed to load last position: {e}")
        return None

    def retrieve_mail_logs(self, starttime, endtime, retries=500, sleep_time=1):
        """
        Retrieves mail logs from API within specified time range.

        Handles pagination by splitting requests when response size reaches limit.
        Includes retry logic for failed requests.

        Args:
            starttime: Start time for log retrieval (Unix timestamp)
            endtime: End time for log retrieval (Unix timestamp)
            retries: Maximum number of retry attempts (default: 500)
            sleep_time: Seconds to wait between retries (default: 1)

        Returns:
            list: Retrieved mail logs in JSON format

        Raises:
            requests.exceptions.RequestException: If API request fails
            ValueError: If response JSON is invalid
        """
        headers = {'Authorization': f'Bearer {self.api_key}'}
        params = {
            'starttime': starttime,
            'endtime': endtime,
            'domain': self.domain,
            'type': self.log_type
        }
        last_position = self.load_last_position()
        if last_position is not None:
            params['starttime'] = last_position
        else:
            params['starttime'] = starttime
        self.log_message("Params: " + str(params))

        attempt = 0
        while attempt < retries:
            try:
                self.log_message(f"Attempt {attempt + 1} to retrieve mail logs")
                response = requests.get(self.url, headers=headers, params=params, timeout=120)
                response.raise_for_status()  # If there's an error, it will raise an exception
                try:
                    data = response.json()  # Parse the response as JSON
                except ValueError:
                    self.log_error(f"JSON decode error: {response.text}")
                    raise
                self.log_message(f"Retrieved {len(data)} logs")
                if len(data) >= 1000:
                    self.log_message("Warning: Log count is 1000. Reducing end_time and retrying.")
                    # If we get 1000 or more logs, it means we might be missing some data
                    # So we split the time range into two parts and process each separately
                    
                    # Calculate middle point between start and end time
                    mid_time = (starttime + endtime) // 2
                    self.log_message(f"Mid time: {mid_time}")

                    # First, get logs for the first half
                    first_half_logs = self.retrieve_mail_logs(starttime, mid_time, retries, sleep_time)
                    self.log_message(f"First half logs: {len(first_half_logs)}")
                    
                    # Then, get logs for the second half
                    second_half_logs = self.retrieve_mail_logs(mid_time, endtime, retries, sleep_time)
                    self.log_message(f"Second half logs: {len(second_half_logs)}")

                    # Combine both results to get complete log set
                    return first_half_logs + second_half_logs

                # Process logs as usual
                detailed_logs = []
                count = 0
                for item in reversed(data):
                    count += 1
                    queue_id = item.get('queue_id')
                    if queue_id:
                        recipients = item.get('recipients', [])
                        if recipients:
                            recipient = recipients[0]
                            queue_id_time = recipient.get('time')
                            self.log_message(f"Count: {count}, queue_id: {queue_id}, queue_id_time: {queue_id_time}")
                            self.log_message(f"{len(data) - count} logs remaining")
                            if queue_id_time:
                                detailed_log = self.retrieve_detailed_log(queue_id, queue_id_time)
                                detailed_logs.append(detailed_log)
                    else:
                        detailed_logs.append(item)

                self.log_message("Finished retrieving mail logs")
                return detailed_logs

            except requests.exceptions.RequestException as e:
                attempt += 1
                self.log_error(f"Error retrieving mail logs (attempt {attempt}): {e}")
            except ValueError as e:
                self.log_error(f"JSON decode error: {e}")
                raise
            except Exception as e:
                self.log_error(f"Unexpected error: {e}")
                raise

    def retrieve_detailed_log(self, queue_id, time, retries=500, sleep_time=1):
        """
        Retrieves detailed log information for specific mail event.

        Fetches extended information for a mail event and removes unnecessary fields.

        Args:
            queue_id: Unique identifier for mail queue
            time: Event timestamp
            retries: Maximum number of retry attempts (default: 500)
            sleep_time: Seconds to wait between retries (default: 1)

        Returns:
            dict: Detailed log information with unnecessary fields removed

        Raises:
            Exception: If retrieval fails after maximum retries
        """
        self.log_message(f"Starting retrieve_detailed_log with queue_id={queue_id} and time={time}")
        detailed_log_url = f'{self.url}/{queue_id}?time={time}'
        attempt = 0
        while attempt < retries:
            try:
                self.log_message(f"Attempt {attempt + 1} to retrieve detailed log for queue_id {queue_id}")
                response = requests.get(detailed_log_url, headers={'Authorization': f'Bearer {self.api_key}'}, timeout=120)
                response.raise_for_status()
                try:
                    detailed_log = response.json()
                except ValueError:
                    self.log_error(f"JSON decode error: {response.text}")
                    raise
                # If successful, reset retry counter
                attempt = 0  

                # List of fields to remove from the detailed log
                fields_to_remove = ['logs', 'transactions', 'filters', 'emails']

                # Remove specified fields from the detailed log
                for field in fields_to_remove:
                    if field in detailed_log:
                        del detailed_log[field]
                self.log_message("Finished retrieving detailed log")
                return detailed_log

            except Exception as e:
                attempt += 1
                self.log_error(f"Error retrieving detailed log for queue_id {queue_id} (attempt {attempt}): {e}")
                # TODO: Add retry logic
                if attempt < retries:
                    time.sleep(sleep_time)  # Sleep before retrying
                else:
                    self.log_error(f"Failed to retrieve detailed log after {retries} attempts.")
                    raise Exception(f"Failed to retrieve detailed log for queue_id {queue_id} after {retries} attempts.")

    def log_error(self, error_message):
        """
        Logs error messages to file with timestamp.

        Args:
            error_message: Error message to log
        """
        error_json = json.dumps({"time": int(datetime.now().timestamp()), "error": str(error_message)}, ensure_ascii=False)
        log_file_name = self.generate_log_file_name()
        with open(log_file_name, 'a', encoding='utf-8') as log_file:
            log_file.write(error_json + "\n")

    def split_and_retrieve_logs(self):
        """
        Manages log retrieval by splitting time range into manageable intervals.

        Handles large time ranges by breaking them into smaller intervals based on
        configured max_time_gap. Updates position tracking after each successful
        interval retrieval.
        """
        endtime = int(datetime.now().timestamp())  # Get the current time as Unix timestamp
        self.log_message(f"End time: {endtime} ({datetime.fromtimestamp(endtime).strftime('%Y-%m-%d %H:%M:%S')})")
        last_position = self.load_last_position()
        if last_position:
            start_time = last_position
        else:
            start_time = self.start_time
        self.log_message(f"Start time: {start_time} ({datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')})")
        time_diff = endtime - start_time  # Calculate the time difference between start and end
        # Convert time difference to days, hours, minutes, and seconds
        days, remainder = divmod(time_diff, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.log_message(f"Time difference: {time_diff} seconds ({days} days, {hours} hours, {minutes} minutes, {seconds} seconds)")

        # If the time difference exceeds the maximum allowed gap, split the request into smaller intervals
        if time_diff > self.max_time_gap:
            current_time = start_time
            # Split the time range into intervals and fetch logs for each interval
            while current_time < endtime:
                next_time = min(current_time + self.split_interval, endtime)  # Calculate the next time interval
                self.log_message(f"Fetching logs from {current_time} ({datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')}) to {next_time} ({datetime.fromtimestamp(next_time).strftime('%Y-%m-%d %H:%M:%S')})")
                logs = self.retrieve_mail_logs(current_time, next_time)
                if logs:
                    self.save_last_position(next_time)  # Save the new position
                    self.process_logs(logs)  # Process and save the logs
                current_time = next_time  # Update the current time for the next interval
        else:
            # If the time difference is small enough, fetch the logs in a single request
            self.log_message(f"Fetching logs from {start_time} ({datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')}) to {endtime} ({datetime.fromtimestamp(endtime).strftime('%Y-%m-%d %H:%M:%S')})")
            logs = self.retrieve_mail_logs(start_time, endtime)
            if logs:
                self.save_last_position(endtime)  # Save the new position
                self.process_logs(logs)  # Process and save the logs

    def acquire_lock(self, lock_file_path):
        """
        Acquires process lock to prevent multiple instances.

        Implements cross-platform file locking mechanism.

        Args:
            lock_file_path: Path to lock file

        Raises:
            IOError: If another instance is already running
        """
        self.lock_file_path = lock_file_path
        self.lock_file = open(self.lock_file_path, 'w')
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

    def release_lock(self):
        """
        Releases process lock and removes lock file.

        Handles both Windows and Unix lock mechanisms.

        Raises:
            Exception: If error occurs while releasing lock
        """
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
                print(f"[{timestamp}] Lock released")
        except Exception as e:
            self.log_error(f"Error releasing lock: {e}")
            raise

    def process_logs(self, logs):
        """
        Processes and saves retrieved logs to file.

        Configures logging for email data and ensures proper encoding.

        Args:
            logs: List of log entries to process
        """
        log_file_name = self.generate_log_file_name()
        
        # Email logger configuration - only for email logs
        email_logger = logging.getLogger('email_logger')
        email_logger.setLevel(logging.INFO)
        
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

        # Remove the handler after we're done
        email_logger.removeHandler(email_handler)

    def run(self):
        """
        Executes main log retrieval and processing workflow.

        Orchestrates the entire logging process including retrieval,
        processing, and error handling.

        Raises:
            Exception: If any error occurs during execution
        """
        try:
            self.split_and_retrieve_logs()
        except Exception as e:
            self.log_error(f"Error during execution: {e}")
            raise

if __name__ == "__main__":

    # Check if config file exists
    config_file = 'uzmanposta.ini'
    if not os.path.exists(config_file):
        print(f"Configuration file '{config_file}' not found.")
        sys.exit(1)

    # Load configuration from file
    config = configparser.ConfigParser()
    config.read(config_file)

    # Extract configuration values
    api_key = config.get('MailLogger', 'api_key')
    log_directory = config.get('MailLogger', 'log_directory')
    log_file_name_format = config.get('MailLogger', 'log_file_name_format')
    position_file = config.get('MailLogger', 'position_file')
    start_time = config.getint('MailLogger', 'start_time')
    domain = config.get('MailLogger', 'domain')
    url = config.get('MailLogger', 'url')
    log_type = config.get('MailLogger', 'type', fallback='outgoinglog')
    split_interval = config.getint('MailLogger', 'split_interval', fallback=300)
    max_time_gap = config.getint('MailLogger', 'max_time_gap', fallback=3600)
    verbose = config.getboolean('MailLogger', 'verbose', fallback=False)
    lock_file_path = config.get('MailLogger', 'lock_file_path', fallback='uzmanposta.lock')
    message_log_file_name = config.get('MailLogger', 'message_log_file_name', fallback='messages.log')

    # Initialize MailLogger instance and run the script
    mail_logger = MailLogger(
        api_key,
        log_directory,
        log_file_name_format,
        position_file,
        start_time,
        domain,
        url,
        log_type,
        split_interval,
        max_time_gap,
        verbose,
        message_log_file_name
    )

    mail_logger.acquire_lock(lock_file_path)
    try:

        mail_logger.run()  # Run the mail logger script
    finally:
        mail_logger.release_lock()
