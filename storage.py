import json
import os
from loguru import logger

def save_operation(data):
    # Get the current working directory
    current_path = os.getcwd()
    # Build a path relative to the current directory
    file_path = os.path.join(current_path, "data", "operation_data.json")
    
    # Ensure the directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    # Load existing data if the file exists
    if os.path.exists(file_path):
        logger.info("File path exists")
        try:
            with open(file_path, "r") as file:
                existing_data = json.load(file)
        except json.JSONDecodeError:
            existing_data = []
    else:
        existing_data = []

    # Append the new operation data to the list
    existing_data.append(data)

    # Save the updated list back to the file
    with open(file_path, "w") as file:
        json.dump(existing_data, file, indent=4)
    logger.info("Stored data")

# Example of operation data
operation_data = {
    "operation": "Some operation",
    "timestamp": "2025-02-18T15:30:00",
    "result": "Success"
}

if __name__ == "__main__":
    # Save the operation data
    save_operation(operation_data)
