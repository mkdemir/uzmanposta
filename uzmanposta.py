"""
This module provides the `MailLogger` class for logging and processing incoming and outgoing mail events.
It supports retrieving logs from the Uzman Posta API and saving them to log files in a specified directory.

The `MailLogger` handles API requests, manages logging positions, and processes mail data for analysis and storage.
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
import time
import requests


class MailLogger:
    """
    A class for logging mail events (both incoming and outgoing) retrieved from the Uzman Posta API.

    Attributes:
        api_key (str): The API key required for authenticating with the Uzman Posta API.
        log_directory (str): The directory where log files will be saved.
        log_file_name_format (str): The format string for generating log file names using `strftime` formatting.
        position_file (str): The file used to store the last operation position (timestamp) for log retrieval.
        start_time (int): The starting time (in Unix timestamp format) for retrieving mail logs.
        domain (str): The domain or email address for which mail logs are being retrieved.
        url (str): The API URL used to fetch mail logs.
        log_type (str): The type of mail logs to retrieve ('incominglog' or 'outgoinglog').
        split_interval (int): The time interval (in seconds) for splitting API requests to avoid large gaps.
        max_time_gap (int): The maximum time gap (in seconds) allowed between the start and end times of a request.

    Methods:
        __init__(self, api_key, log_directory, log_file_name_format, position_file, start_time, domain, url, log_type, split_interval, max_time_gap):
            Initializes the `MailLogger` with the necessary parameters.
        setup_logging(self):
            Configures the logging setup, including the creation of the log directory if it doesn't exist.
        generate_log_file_name(self):
            Generates a log file name based on the provided format and current timestamp.
        save_last_position(self, endtime):
            Saves the Unix timestamp of the last successful operation to the position file.
        load_last_position(self):
            Loads the last operation position (timestamp) from the position file.
        retrieve_mail_logs(self, starttime, endtime, retries, sleep_time):
            Fetches mail logs from the Uzman Posta API within the specified time range.
        retrieve_detailed_log(self, queue_id, time, retries, sleep_time):
            Retrieves detailed log information for a specific `queue_id` and timestamp from the Uzman Posta API.
        log_error(self, error_message):
            Logs error messages to a log file for tracking and debugging.
        split_and_retrieve_logs(self):
            Splits the time range into smaller intervals if the gap between `start_time` and `end_time` exceeds the maximum allowed time gap.
        process_logs(self, logs):
            Processes the retrieved logs and saves them to a log file.
        run(self):
            Runs the log retrieval and processing script.
    """

    def __init__(self, api_key, log_directory, log_file_name_format, position_file, start_time, domain, url, log_type='outgoinglog', split_interval=300, max_time_gap=3600):
        """
        Initializes the `MailLogger` instance with the provided parameters.

        :param api_key: The API key used for authentication with the Uzman Posta service.
        :param log_directory: The directory to save log files.
        :param log_file_name_format: The format string for naming log files (using `strftime` format).
        :param position_file: The path to the file where the last operation position will be stored.
        :param start_time: The start time for fetching logs, in Unix timestamp format.
        :param domain: The domain or email address for which logs are being retrieved.
        :param url: The API URL for accessing the Uzman Posta service.
        :param log_type: The type of logs to retrieve ('incominglog' or 'outgoinglog'). Defaults to 'outgoinglog'.
        :param split_interval: The time interval (in seconds) to split API requests into smaller intervals. Defaults to 300 seconds (5 minutes).
        :param max_time_gap: The maximum allowed time gap between the start and end time for a single request, in seconds. Defaults to 3600 seconds (1 hour).
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

        self.setup_logging()

    def setup_logging(self):
        """
        Configures the logging setup. Creates the log directory if it does not exist.
        """
        if not os.path.exists(self.log_directory):
            os.makedirs(self.log_directory)

    def generate_log_file_name(self):
        """
        Generates a log file name based on the specified format and the current timestamp.

        :return: The generated log file name.
        """
        try:
            return os.path.join(self.log_directory, datetime.now().strftime(self.log_file_name_format))
        except ValueError as e:
            self.log_error(f"Invalid log file name format: {e}")
            return os.path.join(self.log_directory, "default_log.json")

    def save_last_position(self, endtime):
        """
        Saves the Unix timestamp of the last operation position to the position file.

        :param endtime: The Unix timestamp of the last operation position.
        """
        try:
            with open(self.position_file, 'w', encoding='utf-8') as file:
                file.write(str(endtime))
        except IOError as e:
            self.log_error(f"Failed to save last position: {e}")

    def load_last_position(self):
        """
        Loads the last operation position (Unix timestamp) from the position file.

        :return: The last operation position (Unix timestamp), or `None` if not found.
        """
        try:
            if os.path.exists(self.position_file):
                with open(self.position_file, 'r', encoding='utf-8') as file:
                    return int(file.read().strip())
        except IOError as e:
            self.log_error(f"Failed to load last position: {e}")
        return None

    def retrieve_mail_logs(self, starttime, endtime, retries=500, sleep_time=60):
        """
        Retrieves mail logs from the Uzman Posta API within the specified time range.

        :param starttime: The start time for fetching logs (Unix timestamp).
        :param endtime: The end time for fetching logs (Unix timestamp).
        :param retries: The maximum number of retries in case of failure.
        :param sleep_time: The time to wait (in seconds) between retries.
        :return: A list of retrieved mail logs in JSON format.
        """
        headers = {'Authorization': f'Bearer {self.api_key}'}
        params = {
            'starttime': starttime,
            'endtime': endtime,
            'domain': self.domain,
            'type': self.log_type
        }

        last_position = self.load_last_position()
        if last_position:
            params['starttime'] = int(last_position)

        attempt = 0
        while attempt < retries:
            try:
                response = requests.get(self.url, headers=headers, params=params)
                response.raise_for_status()  # If there's an error, it will raise an exception
                data = response.json()  # Parse the response as JSON
                # return data
            
                detailed_logs = []
                # You can update your data after processing each item
                for item in reversed(data):  # Iterating over each item in reverse order
                    queue_id = item.get('queue_id')  # Getting the 'queue_id' value of the item
                    # Accessing the 'recipients' list of the item
                    if queue_id != '' and queue_id is not None:
                        recipients = item.get('recipients', [])
                        if recipients:  # Checking if the 'recipients' list is not empty
                            recipient = recipients[0]  # Selecting the first recipient
                            queue_id_time = recipient.get('time')  # Getting the 'time' value of the recipient
                            if queue_id_time:  # Checking if the 'time' value exists
                                detailed_log = self.retrieve_detailed_log(queue_id, queue_id_time)  # Retrieving detailed log information
                                # item['detailed_log'] = detailed_log  # Adding detailed log information under the 'detailed_log' key of the item
                                detailed_logs.append(detailed_log)
                    else:
                        detailed_logs.append(item)

                return detailed_logs

            except Exception as e:
                attempt += 1
                self.log_error(f"Error retrieving mail logs (attempt {attempt}): {e}")
                if attempt < retries:
                    time.sleep(sleep_time)  # Sleep before retrying
                else:
                    raise Exception("Failed to retrieve mail logs after maximum retries.")

    def retrieve_detailed_log(self, queue_id, time, retries=500, sleep_time=60):
        """
        Retrieves detailed log information for a specific queue ID and timestamp.

        :param queue_id: The unique identifier for the mail queue.
        :param time: The timestamp for the mail event.
        :param retries: The maximum number of retries in case of failure.
        :param sleep_time: The time to wait (in seconds) between retries.
        :return: The detailed log information for the specified `queue_id` and `time`.
        """
        detailed_log_url = f'{self.url}/{queue_id}?time={time}'
        attempt = 0
        while attempt < retries:
            try:
                response = requests.get(detailed_log_url, headers={'Authorization': f'Bearer {self.api_key}'})
                response.raise_for_status()
                detailed_log = response.json()
                
                # If successful, reset retry counter
                attempt = 0  

                # List of fields to remove from the detailed log
                fields_to_remove = ['logs', 'transactions', 'filters', 'emails']

                # Remove specified fields from the detailed log
                for field in fields_to_remove:
                    if field in detailed_log:
                        del detailed_log[field]

                return detailed_log

            except Exception as e:
                attempt += 1
                self.log_error(f"Error retrieving detailed log for queue_id {queue_id} (attempt {attempt}): {e}")
                if attempt < retries:
                    time.sleep(sleep_time)  # Sleep before retrying
                else:
                    self.log_error(f"Failed to retrieve detailed log after {retries} attempts.")
                    raise Exception(f"Failed to retrieve detailed log for queue_id {queue_id} after {retries} attempts.")

    def log_error(self, error_message):
        """
        Logs an error message.
        Saves the error message in a log file.

        :param error_message: The error message to log
        """
        error_json = json.dumps({"time": int(datetime.now().timestamp()), "error": str(error_message)}, ensure_ascii=False)
        log_file_name = self.generate_log_file_name()
        with open(log_file_name, 'a', encoding='utf-8') as log_file:
            log_file.write(error_json + "\n")

    def split_and_retrieve_logs(self):
        """
        Splits the time range into smaller intervals (e.g., 5 minutes) if the difference between `start_time` and `end_time` exceeds the maximum allowed gap.
        Processes the logs for each interval separately.
        """
        endtime = int(datetime.now().timestamp())  # Get the current time as Unix timestamp
        time_diff = endtime - self.start_time  # Calculate the time difference between start and end

        # If the time difference exceeds the maximum allowed gap, split the request into smaller intervals
        if time_diff > self.max_time_gap:
            current_time = self.start_time
            # Split the time range into intervals and fetch logs for each interval
            while current_time < endtime:
                next_time = min(current_time + self.split_interval, endtime)  # Calculate the next time interval
                logs = self.retrieve_mail_logs(current_time, next_time)
                if logs:
                    self.save_last_position(str(next_time))  # Save the new position
                    self.process_logs(logs)  # Process and save the logs
                current_time = next_time  # Update the current time for the next interval
        else:
            # If the time difference is small enough, fetch the logs in a single request
            logs = self.retrieve_mail_logs(self.start_time, endtime)
            if logs:
                self.save_last_position(str(endtime))  # Save the new position
                self.process_logs(logs)  # Process and save the logs

    def process_logs(self, logs):
        """
        Processes and saves the retrieved logs into a log file.

        :param logs: The list of logs retrieved from the API.
        """
        log_file_name = self.generate_log_file_name()
        logging.basicConfig(filename=log_file_name,
                            level=logging.INFO,
                            format='%(message)s',
                            encoding='utf-8')

        # Save the logs in reverse order (newest first)
        for item in reversed(logs):
            logging.info(json.dumps(item, ensure_ascii=False))

    def run(self):
        """
        Executes the mail log retrieval and processing script.
        """
        self.split_and_retrieve_logs()


if __name__ == "__main__":
    # Command-line argument parsing and script execution
    parser = argparse.ArgumentParser(description='Script for Collecting and Logging Mail Logs for Uzman Posta')
    parser.add_argument('--api_key', required=True, help='Uzman Posta API key')  # API key for authentication
    parser.add_argument('--log_directory', required=True, help='Directory for saving log files')  # Directory for log files
    parser.add_argument('--log_file_name_format', required=True, help='Format for log file names (e.g., mail_%Y%m%d%H%M.json)')  # Format for the log file name
    parser.add_argument('--position_file', required=True, help='File to store the last operation position')  # File for storing the last position
    parser.add_argument('--start_time', required=True, type=int, help='Start time for data retrieval (Unix timestamp)')  # Start time for the data retrieval (Unix timestamp)
    parser.add_argument('--domain', required=True, help='Domain or email address')  # Domain or email address for retrieving logs
    parser.add_argument('--url', required=True, help='API URL')  # URL for the API
    parser.add_argument('--type', default='outgoinglog', help='Log type: incominglog or outgoinglog')  # Type of log ('incominglog' or 'outgoinglog')
    parser.add_argument('--split_interval', type=int, default=300, help='Interval for splitting requests (seconds)')  # Interval for splitting the requests
    parser.add_argument('--max_time_gap', type=int, default=3600, help='Maximum time gap for splitting requests (seconds)')  # Maximum time gap between start and end time for splitting

    args = parser.parse_args()

    # Ensure that start_time is an integer
    try:
        start_time = int(args.start_time)
    except ValueError:
        print("Error: start_time must be an integer representing Unix timestamp.")
        sys.exit(1)

    # Initialize MailLogger instance and run the script
    mail_logger = MailLogger(
        args.api_key,
        args.log_directory,
        args.log_file_name_format,
        args.position_file,
        start_time,
        args.domain,
        args.url,
        args.type,
        args.split_interval,
        args.max_time_gap
    )

    mail_logger.run()  # Run the mail logger script
