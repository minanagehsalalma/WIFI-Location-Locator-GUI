#  Wi-Fi Locator GUI

This project provides a sleek Tkinter GUI that queries Apple's Wi-Fi geolocation service for a given BSSID (Wi-Fi MAC address).
The application displays the latitude and longitude, and, when successful, embeds a Google Maps view of the location.
<img width="891" height="902" alt="image" src="https://github.com/user-attachments/assets/ff2c63c7-10ea-4982-829a-167578bc0d2e" />


## Requirements

- Python 3

## Installation

1.  Clone this repository or download the source code.
2.  Install the required Python packages:

    ```
    pip install -r requirements.txt
    ```

    This will install `requests`, `protobuf`, `tkinterweb`, and `pythonmonkey`.

## Usage

Run the application:

```
python apple_wifi_locator_gui.py
```

Enter a MAC address in the format `XX:XX:XX:XX:XX:XX`  and click **Lookup** to query Apple's Wi-Fi location service and show the spot on Google Maps.

