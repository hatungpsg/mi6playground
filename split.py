import requests
import time
import json

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

def store_and_refresh_token():
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
            file_path = 'util/fwval_lib/qspi_2.py'
            # Using the 'with' statement to open the file
            with open(file_path, 'r') as file:
                file_contents = file.read()
            payload = {
                "query": f"Below is the qspi_2.py which is extended function from qspi_1.py. Help me to understand it:\n\n{file_contents}",
                #"query": f"What is ai",
                "use_case": "generic",
                "temperature": 0.5,
                "inference_model": "azure.openai.gpt.3.5",
                "stream": True,
                "token_limit": 600,
                "tags": []
            }
            #print(payload)
            apiResponse = requests.request("POST",'https://apis-internal.intel.com/mi6/v1/conversations/66a1dcf8d9f86ccd70bc5d27', headers=apiHeaders,proxies=proxies,json=payload)
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
    refresh_token = ""
    access_token = ""
    
    store_and_refresh_token()
