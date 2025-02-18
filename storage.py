import json
import os
from loguru import logger


def save_operation(data):
    # Define the path to the file (you can change this to a location in your persistent storage)
    file_path = "/data/operation_data.json"
    
    # Make sure the directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    # Check if the file exists and load existing data if it does
    if os.path.exists(file_path):
        logger.info("File path exists")
        with open(file_path, "r") as file:
            existing_data = json.load(file)
    else:
        existing_data = []

    # Add the new operation data to the list
    existing_data.append(data)

    # Save the updated list back to the file
    with open(file_path, "w") as file:
        json.dump(existing_data, file, indent=4)
    logger.info("stored data")

# Example of operation data
operation_data = {
    "operation": "Some operation",
    "timestamp": "2025-02-18T15:30:00",
    "result": "Success"
}
if __name__ == "__main__":

    # Save the operation data
    save_operation(operation_data)
