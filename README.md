#  Wi-Fi Locator GUI

This project provides a sleek Tkinter GUI that queries Apple's Wi-Fi geolocation service for a given BSSID (Wi-Fi MAC address).
The application displays the latitude and longitude and renders the location on a built-in map. By default it uses OpenStreetMap, and it can optionally use Google Static Maps when a valid API key is supplied.
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

Enter a MAC address in the format `XX:XX:XX:XX:XX:XX` and click **Lookup** to query Apple's Wi-Fi location service and show the spot on the map.

To enable Google Static Maps instead of the default OpenStreetMap rendering, set either `GOOGLE_MAPS_STATIC_API_KEY` or `GOOGLE_MAPS_API_KEY` in your environment before launching the app.

