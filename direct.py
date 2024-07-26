import requests
import logging

# Enable logging
logging.basicConfig(level=logging.DEBUG)

url = 'https://apis-internal.intel.com/mi6/v1/supported-use-cases'
headers = {
    'Authorization': 'Bearer '
}
proxies = {
    'http': 'http://proxy-dmz.intel.com:912',
    'https': 'http://proxy-dmz.intel.com:912',
}

try:
    response = requests.get(url, headers=headers,proxies=proxies, timeout=30)
    print(response.status_code)
    print(response.json())  # Assuming the response is in JSON format
except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}")
