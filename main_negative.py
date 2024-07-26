import requests
import time
import json

import os
import glob
from docx import Document
conv_id = None  
# Replace with your Azure AD application details
TENANT_ID = ""
CLIENT_ID = ""
CLIENT_SECRET = ""
# Azure AD token endpoint
TOKEN_ENDPOINT = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
proxies = {
    'http': 'http://proxy-dmz.intel.com:912',
    'https': 'http://proxy-dmz.intel.com:912',
}


# Function to read all .py files in a folder
def read_all_py_files_in_folder(folder_path):
    # Get a list of all .py files in the folder
    py_files = glob.glob(os.path.join(folder_path, '*.py'))
    
    # Dictionary to store file names and their contents
    file_contents = {}

    # Read each .py file
    for py_file in py_files:
        with open(py_file, 'r') as file:
            content = file.read()
            file_contents[os.path.basename(py_file)] = content
    
    return file_contents

# Function to write content to a .py file
def write_to_py_file(file_path, content):
    with open(file_path, 'w') as file:
        file.write(content)

def get_access_token():

    global access_token
    global refresh_token

    """Retrieves an access token using the refresh token."""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "scope": f"api://{CLIENT_ID}/nononce openid email offline_access"
    }
    response = requests.post(TOKEN_ENDPOINT, headers=headers, data=data)
    access_token = response.json()["access_token"]
    refresh_token = response.json()["refresh_token"]

def store_and_refresh_token(conv_id=None):
    """Stores the access token and refreshes it after 50 minutes."""
    get_access_token()
    expires_in = 50 * 60  # 50 minutes in seconds
    expiry_time = time.time() + expires_in

    try:
        while True:
            # Use the access token for your API calls here
            apiHeaders = {
                "Authorization": f'Bearer {access_token}'
            }

            # Step 1: Open the file in read mode
            testplan = '22_3_FWVAL_TestPlan_SM_Encryption_Test_Plan_rev0.7.docx'
            testplan_path = 'negative_flow/22_3_FWVAL_TestPlan_SM_Encryption_Test_Plan_rev0.7.docx'
            doc = Document(testplan_path)

            # Extract the content of the document
            testplan_file_contents = "\n".join([paragraph.text for paragraph in doc.paragraphs])

            # Step 1: Open the file in read mode
            positive_flow = 'jtagtest_reconfig_without_negativeflow.py'
            positive_flow_path = 'negative_flow/jtagtest_reconfig_without_negativeflow.py'
            positive_flow_file = open(positive_flow_path, 'r')

            # Step 2: Read the contents of the file
            positive_flow_file_contents = positive_flow_file.read()

            token_limit = 5000
            payload = {
                "query": f"Below is the {testplan}. It's security testplan. Help me to understand it:\n\n{testplan_file_contents}\n\n Here is the positive flow. Help me to understand it:\n\n{positive_flow_file_contents} Help me comeout with negative test flow and generate the respective by refer to positive flow and without skip",
                #"query": f"Explain prepare_qspi_using_bfm in detail",
                "use_case": "generic",
                "temperature": 0.5,
                "inference_model": "azure.openai.gpt.4",
                "stream": True,
                "token_limit": token_limit,
                "tags": []
            }

            # Determine the endpoint based on conv_id
            if conv_id is None or conv_id == 0:
                url = 'https://apis-internal.intel.com/mi6/v1/conversations'
            else:
                url = f'https://apis-internal.intel.com/mi6/v1/conversations/{conv_id}'
            
            apiResponse = requests.request("POST",url, headers=apiHeaders,proxies=proxies,json=payload)
            print("API Call")
            # Handle the response
            if apiResponse.status_code == 200:
                print("Request was successful.")
                response_data = apiResponse.text.strip().split("\n")

                # Access the last data entry
                if response_data:
                    last_data_str = response_data[-1].split("data: ")[1]
                    last_data = json.loads(last_data_str)

                    # Access the assistant field
                    assistant_response = last_data['last_message']['assistant']
                    conversation_id_response = last_data['conversation_id']
                    conv_id = conversation_id_response
                    file_path = 'negative_flow/negative_flow.py'
                    print("Assistant's response:", assistant_response)
                    print("Conversation ID's response:", conversation_id_response)
                    write_to_py_file(file_path, assistant_response)
            else:
                print(f"Request failed with status code {apiResponse.status_code}")
                print(apiResponse.text)

            # Check for expiration and refresh if needed
            if time.time() >= expiry_time:
                print("Getting new access token")
                get_access_token()
                expiry_time = time.time() + expires_in

            time.sleep(30)  # Check for expiration every 30 seconds
    except KeyboardInterrupt:
        print("Program interrupted and stopped.")

if __name__ == "__main__":
    refresh_token = ""
    access_token = ""
    # Initialize conv_id
    conv_id = None  # Or set to 0 or any default value

    # Call the function

    store_and_refresh_token(conv_id)
