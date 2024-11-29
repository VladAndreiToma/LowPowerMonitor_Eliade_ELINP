#/usr/bin/python3

import pexpect
import time
import subprocess
import os
import logging
import shutil
import re
import json
import time
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError

# author: Vlad Andrei Toma , engr.phys.


# Set up logging configuration
logging.basicConfig(
    filename='actions.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

def create_influxdb_client(host='localhost', port=8086, database='TPC_DT1415_Monitor', max_retries=5, retry_delay=2):
    client = None
    for attempt in range(max_retries):
        try:
            client = InfluxDBClient(host=host, port=port, database=database)
            # Optionally, check if the connection is successful by querying the server
            client.ping()  # This will raise an exception if the connection fails
            return client
        except (InfluxDBClientError, ConnectionError) as e:
            time.sleep(retry_delay)

    raise Exception(f"Failed to connect to InfluxDB after {max_retries} attempts.")


# a function to move all the stuff
def move_hardcopy_file():
    '''Move the hardcopy.0 file from the home directory to the script's directory.'''
    home_directory = os.path.expanduser('~')  # Get home directory
    source_file_path = os.path.join(home_directory, 'hardcopy.0')  # Full path to hardcopy.0
    script_directory = os.path.dirname(os.path.abspath(__file__))  # Get the script's directory
    destination_file_path = os.path.join(script_directory, 'hardcopy.0')  # Destination path

    try:
        shutil.move(source_file_path, destination_file_path)
        logging.info(f'Moved hardcopy.0 to {destination_file_path}')
    except FileNotFoundError:
        logging.info('The hardcopy.0 file does not exist in the home directory.')
    except Exception as e:
        logging.info(f'An error occurred: {e}')

def log_action(message):
    '''Log an action with a timestamp.'''
    logging.info(message)

def start_screen_session(session_name):
    '''Start a detached screen session.'''
    subprocess.run(['screen', '-S', session_name, '-dm'])
    log_action(f'Started screen session: {session_name}')

def connect_telnet_via_screen(session_name, ip, port):
    '''Start telnet in the screen session and send necessary commands.'''
    command = f'screen -S {session_name} -X stuff "telnet {ip} {port}\n"'
    subprocess.run(command, shell=True)
    log_action(f'Connecting to telnet {ip}:{port} in session: {session_name}')

    time.sleep(5)  # Increased wait time for connection
    p = pexpect.spawn(f'screen -r {session_name}')
    
    # Simulate the 'caen' and 'C' commands once connected
    p.expect(".*")  # Wait for the telnet prompt or connection message
    p.sendline("caen")
    log_action(f'Sent command "caen" to session: {session_name}')
    time.sleep(2)  # Increased delay before sending the next command
    p.sendline("d")
    log_action(f'Sent command "d" to session: {session_name}')
    time . sleep( 10 ) # make sure the screen renders :)))

    # Add an expectation here for the output after sending "C"
    try:
        p.expect(".*")  # Wait for any output or confirmation
        log_action("Received output after sending command 'C'")
    except pexpect.TIMEOUT:
        log_action("Timeout occurred while waiting for output after command 'C'")

    # Detach from the screen session after setup
    p.sendcontrol('a')  # Control+a to detach from the screen
    p.send('d')         # Detach screen
    log_action(f'Detached from screen session: {session_name}')

def remove_existing_screens():
    '''Remove all existing screen sessions.'''
    result = subprocess.run(['screen', '-ls'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sessions = result.stdout.splitlines()
    log_action('Checking for existing screen sessions.')

    for session in sessions:
        if '.TPC' in session and 'Detached' in session:
            session_name = session.split()[0]
            subprocess.run(['screen', '-S', session_name, '-X', 'quit'])
            log_action(f'Removed screen session: {session_name}')

# function to brush the raw textfile
def PARSE_HARDCOPY_DATA_TO_JSON( file_path ):
    '''code to parse to a managable db json file'''
    # Initialize a list to hold the channel data JSON objects
    channel_data_list = []
    
    # Read the content of the file
    with open(file_path, 'r') as file:
        content = file.readlines()

    # Extract the device name from the first line
    device_info = content[0].strip()
    match = re.search(r'DT(\d+)', device_info)
    device_name = f'DT{match.group(1)}' if match else 'Unknown'

    # Log channel lines for debugging
    for contentLine in content[1:]:
        # Strip whitespace from the line
        stripped_line = contentLine.strip()

        # Check if the line is not empty, contains 'Ch', and does not contain 'Channel'
        if len(stripped_line) > 0 and 'Ch' in stripped_line and 'Channel' not in stripped_line:
            # Log the channel information line for debugging purposes
            log_action(f'Channel info line: {stripped_line}')  # Already stripped for clarity

            # Now process the line to extract the channel data
            parts = stripped_line.split()
        
            if len(parts) >= 6:  # Ensure there are enough parts to unpack
                channel_id = parts[0][2]  # Extract the channel number (0, 1, 2, etc.)
            
                
                # Extract Vmon, Imon, Vset, Iset, and Pw values, skipping the "uA" entries
                channel_json = {
                    'measurement': device_name,                         # Set the measurement to the device name
                    'tags': {
                        'channel': channel_id                           # Tag for the channel ID
                    },
                    'fields': {
                        'Vmon': float(parts[1]),                        # Convert Vmon to float
                        'Imon': float(parts[2].replace('+', '')),      # Clean "+" from Imon and convert to float
                        'Vset': float(parts[4]),                        # Skip "uA" and get Vset
                        'Iset': float(parts[5]),                        # Skip "uA" and get Iset
                        'Pw': True if parts[7] == 'On' else False      # Convert Pw (On -> True, Off -> False)
                    }
                }
                log_action( f'channel json: { channel_json }'  )

# Append to the list of channel data

                # Append the channel JSON object to the list
                channel_data_list.append(channel_json)

                # Convert the list of channel JSON objects to JSON

                # Log the final JSON output for database insertion
    log_action(f'JSON for DB: {channel_data_list}')

    return channel_data_list



def create_hardcopy(session_name, output_file_path, client):
    '''Create a hardcopy of the current screen session and insert data into InfluxDB.'''
    # Execute the hardcopy command in the screen session
    command = f'screen -S {session_name} -X hardcopy {output_file_path}'
    subprocess.run(command, shell=True)
    log_action(f'Created hardcopy: {output_file_path}')
    
    JSON_To_Be_Inserted_In_InfluxDB = PARSE_HARDCOPY_DATA_TO_JSON(output_file_path)

    # Ensure JSON_To_Be_Inserted_In_InfluxDB is a list of dictionaries
    if isinstance(JSON_To_Be_Inserted_In_InfluxDB, str):
        log_action("Error: JSON_To_Be_Inserted_In_InfluxDB is a string instead of a list.")
        return

    # Write points to InfluxDB
    client.write_points(JSON_To_Be_Inserted_In_InfluxDB)

    log_action(f'JSON file to be inserted in DB: {JSON_To_Be_Inserted_In_InfluxDB}')
    
    # Write JSON data to InfluxDB
    client.write_points(JSON_To_Be_Inserted_In_InfluxDB)
    log_action(f'Inserted JSON into DB: {JSON_To_Be_Inserted_In_InfluxDB}')
    # move_hardcopy_file()  # Uncomment if you have this function implemented

def main():
    # Configuration
    IP_ADDRESS = '172.18.4.215'
    PORT = 1470
    SCREEN_SESSION = 'TPC'
    HARDCOPY_FILE_PATH = os.path.expanduser('~/hardcopy.0')  # Path for hardcopy file
    INTERVAL = 60  # Time in seconds to wait between each hardcopy

    # Remove all existing screens
    remove_existing_screens()

    # Start new screen session
    start_screen_session(SCREEN_SESSION)

    # Connect to telnet via the new screen session
    connect_telnet_via_screen(SCREEN_SESSION, IP_ADDRESS, PORT)

    try:
        while True:
            # Create a hardcopy of the screen session
            create_hardcopy(SCREEN_SESSION, HARDCOPY_FILE_PATH, client)

            # Wait for the specified interval before repeating
            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        log_action("Stopped periodic hardcopy creation.")
        print("Stopping periodic hardcopy creation.")

if __name__ == "__main__":
    client = create_influxdb_client()
    main()
