import requests
import time
import json

import os
import glob
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
            folder_path = 'util/fwval_lib'
            files_contents = read_all_py_files_in_folder(folder_path)
            # Print the contents of each file
            token_limit = 1000
            for file_name, content in files_contents.items():
                print(f"Below is the {file_name}")
                payload = {
                    "query": f"Below is the {file_name}. Help me to understand it:\n\n{content}",
                    #"query": f"Explain prepare_qspi_using_bfm in detail",
                    "use_case": "generic",
                    "temperature": 0.5,
                    "inference_model": "azure.openai.gpt.4",
                    "stream": True,
                    "token_limit": token_limit,
                    "tags": []
                }
                token_limit = token_limit + 1000


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
                        print("Assistant's response:", assistant_response)
                        print("Conversation ID's response:", conversation_id_response)
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
    refresh_token = "0.AQ0AiI3JRkTj1E6Elk7XcS4lXep1yRG9JTFIoKa6A-VNmwwNAF0.AgABAwEAAAApTwJmzXqdR4BN2miheQMYAgDs_wUA9P8unjhkQNneVIudzFvmjYfIC71aAP6yaEpzO5aoWy8nbcVU4UPGXgYiHr5Pt5xY0X3r41Eq0rD8MQbP_fWs9Zpej2ISNgSWYE0uHfRruU8iKWY6FuZ47JZxITtEhsp3r-jcn5Kmgyg2VeONSDqPCWR2K1vDcNGpQCyo3RzEWTvAaMEsSRJhJO5i-Y405QSjqOyVmDF3HK_kgV3K0LcaVDam392du_xFgdaWA6rB5sS0vzq7sLGzzg66Lh9jaH83tE0sSsO2w88s6nKW98xDsziLa7_LkVOhNNlX5DCnULtKV2afBGnhKXqYodTBlStmdpvfsfKSj8FYyrtRPhv1knd95MBE9q5oA8qcwl56q48ZzKicKF3QlrUEQ0yRy8W5rHzpgh6xIJOE7T1yVaV7NNvo_kBLdvdCqL6EjMjOrkIq_L91Y26TJdGYEghmeUiFDF1sn6zJHGxeGBqoMQ-K48CvxMvX_fzcQz1vVdjxmNkHpVJY7cs_6Tsp7T7DrhfM7hKOBCL1a3h_Gd4s1h9DKr5CSEDcwq22sDyJmYt7pryMSMqJucVF7Row7xtntV_DPE-WBwJivjJXeJPkHXIEbsQ5MQlt95wmR-rGF13z7EJ25CaQ5zDqDmjRH23SBYi0N9dFpbDbD6UjG-LGeR9mw1wXnf4KGUbrlCqH0Fv4GLv7KEFx6qvXpxdFwWGgGWjnjOy38QZzoJIH7lT5045mlMiR57qjFdlmPCFgfHmGFo9pJ889"
    access_token = ""
    # Initialize conv_id
    conv_id = None  # Or set to 0 or any default value

    # Call the function

    store_and_refresh_token(conv_id)
