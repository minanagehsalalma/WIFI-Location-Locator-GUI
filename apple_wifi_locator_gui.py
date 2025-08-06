import os
import re
import math
import random
import tkinter as tk
from tkinter import ttk, messagebox
from io import BytesIO
import webbrowser
from typing import Tuple, Union

import requests
from PIL import Image, ImageTk, ImageDraw, ImageFont
from google.protobuf.message import DecodeError

# Keep protobuf pure-Python on Windows
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

# ---- Apple proto import ----
try:
    from helpers.BSSIDApple_pb2 import BSSIDResp
except TypeError as exc:
    raise RuntimeError("Incompatible protobuf library detected. Install 'protobuf>=3.20,<4'.") from exc

# Configuration
GOOGLE_MAPS_API_KEY = "AIzaSyA9PXUACtgDHe8W3JJD6_VDfV-hoWdH7TA"
OSM_TILE_SERVERS = ["a.tile.openstreetmap.org", "b.tile.openstreetmap.org", "c.tile.openstreetmap.org"]
USE_GOOGLE_MAPS = True  # Set to False to skip Google Maps and use OSM only
TILE_SIZE = 256
DEFAULT_ZOOM = 15
VIEW_TILES = 3  # 3x3 patch for OSM
MAP_WIDTH, MAP_HEIGHT = 600, 400  # larger map display
UA = {"User-Agent": "wifi-locator/2.0 (+modern-gui)"}

# Modern color scheme
COLORS = {
    'bg': '#1a1a1a',
    'card': '#2d2d2d', 
    'accent': '#007AFF',
    'success': '#34C759',
    'error': '#FF3B30',
    'text': '#FFFFFF',
    'text_secondary': '#8E8E93',
    'border': '#3A3A3C'
}


def lookup_location(mac: str) -> Union[Tuple[float, float], str]:
    """Return (lat, lon) or an error string."""
    if not re.match(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$", mac):
        return "Invalid MAC address format. Use XX:XX:XX:XX:XX:XX"
    mac = mac.lower()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Accept-Charset": "utf-8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-us",
        "User-Agent": "locationd/1753.17 CFNetwork/711.1.12 Darwin/14.0.0",
    }

    data_bssid = f"\x12\x13\n\x11{mac}\x18\x00\x20\x01"
    data = (
        "\x00\x01\x00\x05en_US\x00\x13com.apple.locationd\x00\x0a"
        "8.1.12B411\x00\x00\x00\x01\x00\x00\x00"
        + chr(len(data_bssid))
        + data_bssid
    )

    try:
        resp = requests.post(
            "https://gs-loc.apple.com/clls/wloc",
            headers=headers,
            data=data,
            timeout=15,
        )
        bssid_response = BSSIDResp()
        bssid_response.ParseFromString(resp.content[10:])
        if bssid_response.wifi:
            lat_i = bssid_response.wifi[0].location.lat
            lon_i = bssid_response.wifi[0].location.lon
            if lat_i == 18000000000:
                return "Location not found in Apple's database"
            return lat_i / 1e8, lon_i / 1e8
        return "Location not found in Apple's database"
    except DecodeError as exc:
        return f"Failed to decode Apple response: {exc}"
    except requests.RequestException as exc:
        return f"Network error: {exc}"


def fetch_google_maps_image(lat: float, lon: float, zoom: int = DEFAULT_ZOOM, 
                          width: int = MAP_WIDTH, height: int = MAP_HEIGHT) -> Image.Image:
    """Fetch static map from Google Maps API."""
    base_url = "https://maps.googleapis.com/maps/api/staticmap"
    params = {
        'center': f"{lat},{lon}",
        'zoom': zoom,
        'size': f"{width}x{height}",
        'maptype': 'roadmap',
        'markers': f"color:red|size:mid|{lat},{lon}",
        'key': GOOGLE_MAPS_API_KEY,
        'format': 'png',
        'scale': 1
    }
    
    response = requests.get(base_url, params=params, timeout=15)
    response.raise_for_status()
    
    # Check if response is an error image from Google
    if 'error' in response.headers.get('content-type', '').lower():
        raise requests.RequestException("Google Maps API returned an error")
    
    return Image.open(BytesIO(response.content)).convert("RGBA")


# --------- OSM tile stitching (fallback) ----------
def latlon_to_tilexy(lat: float, lon: float, z: int) -> Tuple[float, float]:
    """Fractional tile (x, y) for slippy map at zoom z."""
    lat = max(min(lat, 85.05112878), -85.05112878)  # web mercator clamp
    n = 2.0 ** z
    xtile = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    ytile = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def fetch_osm_tile(z: int, x: int, y: int) -> Image.Image:
    """Fetch a single OSM tile."""
    host = random.choice(OSM_TILE_SERVERS)
    url = f"https://{host}/{z}/{x}/{y}.png"
    r = requests.get(url, headers=UA, timeout=10)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGBA")


def build_osm_map(lat: float, lon: float, z: int = DEFAULT_ZOOM, 
                  out_w: int = MAP_WIDTH, out_h: int = MAP_HEIGHT) -> Image.Image:
    """Build map using OpenStreetMap tiles."""
    # center tile (fractional)
    tx, ty = latlon_to_tilexy(lat, lon, z)
    cx, cy = int(math.floor(tx)), int(math.floor(ty))

    # stitch a VIEW_TILES x VIEW_TILES patch around center
    half = VIEW_TILES // 2
    canvas = Image.new("RGBA", (TILE_SIZE * VIEW_TILES, TILE_SIZE * VIEW_TILES), (255, 255, 255, 0))

    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            x = (cx + dx) % (2 ** z)  # wrap X
            y = cy + dy
            if y < 0 or y >= 2 ** z:
                continue
            try:
                tile = fetch_osm_tile(z, x, y)
                canvas.paste(tile, ((dx + half) * TILE_SIZE, (dy + half) * TILE_SIZE))
            except Exception:
                # leave missing tile blank
                pass

    # pixel offset of the exact lat/lon within the stitched patch
    px = (tx - (cx - half)) * TILE_SIZE
    py = (ty - (cy - half)) * TILE_SIZE

    # crop to desired output centered on (px, py)
    left = int(round(px - out_w / 2))
    top = int(round(py - out_h / 2))
    crop = canvas.crop((left, top, left + out_w, top + out_h))

    # draw a modern marker at the center
    draw = ImageDraw.Draw(crop)
    r = 8
    cx_out, cy_out = out_w // 2, out_h // 2
    
    # Drop shadow
    shadow_offset = 2
    draw.ellipse((cx_out - r + shadow_offset, cy_out - r + shadow_offset, 
                  cx_out + r + shadow_offset, cy_out + r + shadow_offset),
                 fill=(0, 0, 0, 100))
    
    # Main marker
    draw.ellipse((cx_out - r, cy_out - r, cx_out + r, cy_out + r),
                 fill=(255, 59, 48, 255), outline=(255, 255, 255, 255), width=3)
    draw.ellipse((cx_out - r//2, cy_out - r//2, cx_out + r//2, cy_out + r//2),
                 fill=(255, 255, 255, 255))

    # Modern attribution
    strip_h = 24
    draw.rectangle((0, out_h - strip_h, out_w, strip_h), fill=(0, 0, 0, 150))
    draw.text((8, out_h - strip_h + 6), "© OpenStreetMap contributors", 
              fill=(255, 255, 255, 255))

    return crop


def get_map_image(lat: float, lon: float, zoom: int = DEFAULT_ZOOM) -> Tuple[Image.Image, str]:
    """Get map image, trying Google Maps first, then OSM fallback."""
    if USE_GOOGLE_MAPS and GOOGLE_MAPS_API_KEY:
        try:
            # Try Google Maps first
            image = fetch_google_maps_image(lat, lon, zoom, MAP_WIDTH, MAP_HEIGHT)
            return image, "Google Maps"
        except requests.exceptions.HTTPError as e:
            if "403" in str(e):
                print(f"Google Maps API key issue (403 Forbidden). Enable 'Maps Static API' in Google Cloud Console.")
                print(f"Your key currently has: Maps JavaScript API (need Maps Static API)")
            else:
                print(f"Google Maps HTTP error: {e}")
        except Exception as e:
            print(f"Google Maps failed: {e}")
        
        print("Falling back to OpenStreetMap...")
    
    try:
        # Use OpenStreetMap
        image = build_osm_map(lat, lon, zoom, MAP_WIDTH, MAP_HEIGHT)
        return image, "OpenStreetMap"
    except Exception as e:
        if USE_GOOGLE_MAPS:
            raise Exception(f"Both map services failed. Google Maps API issue (check API key permissions), OSM: {e}")
        else:
            raise Exception(f"OpenStreetMap failed: {e}")


def setup_modern_style(root: tk.Tk) -> ttk.Style:
    """Configure modern dark theme."""
    style = ttk.Style()
    
    # Configure colors for modern look
    style.configure('Title.TLabel', 
                   font=('SF Pro Display', 24, 'bold'), 
                   foreground=COLORS['text'],
                   background=COLORS['bg'])
    
    style.configure('Heading.TLabel',
                   font=('SF Pro Display', 12, 'bold'),
                   foreground=COLORS['text'],
                   background=COLORS['bg'])
    
    style.configure('Body.TLabel',
                   font=('SF Pro Text', 11),
                   foreground=COLORS['text_secondary'],
                   background=COLORS['bg'])
    
    style.configure('Status.TLabel',
                   font=('SF Pro Text', 11),
                   foreground=COLORS['success'],
                   background=COLORS['bg'])
    
    style.configure('Error.TLabel',
                   font=('SF Pro Text', 11),
                   foreground=COLORS['error'],
                   background=COLORS['bg'])
    
    style.configure('Modern.TEntry',
                   fieldbackground='#FFFFFF',  # White background
                   foreground='#000000',       # Black text
                   bordercolor=COLORS['border'],
                   insertcolor='#000000',      # Black cursor
                   selectbackground='#007AFF', # Blue selection
                   selectforeground='#FFFFFF', # White selected text
                   font=('Arial', 11))
    
    # Alternative button style that should work better
    style.configure('Modern.TButton',
                   font=('Arial', 10, 'bold'),
                   relief='flat',
                   borderwidth=0,
                   padding=(10, 6))
    
    style.map('Modern.TButton',
             background=[('!active', COLORS['accent']), ('active', '#0051D5'), ('pressed', '#004CCC')],
             foreground=[('!active', '#FFFFFF'), ('active', '#FFFFFF'), ('pressed', '#FFFFFF')])
    
    style.configure('Modern.TSpinbox',
                   fieldbackground=COLORS['card'],
                   foreground=COLORS['text'],
                   bordercolor=COLORS['border'],
                   font=('SF Pro Text', 10))
    
    style.configure('Modern.TFrame',
                   background=COLORS['card'],
                   relief='flat',
                   borderwidth=1)
    
    return style


def create_modern_gui():
    """Create the modern GUI application."""
    root = tk.Tk()
    root.title("Wi-Fi Locator GUI")
    root.geometry("720x700")
    root.configure(bg=COLORS['bg'])
    root.resizable(True, True)
    
    # Set up modern styling
    style = setup_modern_style(root)
    
    # Configure grid weights
    root.columnconfigure(0, weight=1)
    root.rowconfigure(4, weight=1)  # Map area expands
    
    # Title section
    title_frame = tk.Frame(root, bg=COLORS['bg'], pady=20)
    title_frame.grid(row=0, column=0, sticky='ew', padx=20)
    
    title_label = ttk.Label(title_frame, text="Wi-Fi Locator GUI", style='Title.TLabel')
    title_label.pack()
    
    subtitle_label = ttk.Label(title_frame, text="Enter BSSID to find location", style='Body.TLabel')
    subtitle_label.pack(pady=(5, 0))
    
    # Input section
    input_frame = ttk.Frame(root, style='Modern.TFrame', padding=20)
    input_frame.grid(row=1, column=0, sticky='ew', padx=20, pady=(0, 15))
    input_frame.columnconfigure(1, weight=1)
    
    ttk.Label(input_frame, text="BSSID:", style='Heading.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 5))
    
    # MAC entry with modern styling
    mac_frame = tk.Frame(input_frame, bg=COLORS['card'])
    mac_frame.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(0, 15))
    mac_frame.columnconfigure(0, weight=1)
    
    mac_entry = ttk.Entry(mac_frame, style='Modern.TEntry', font=('Monaco', 12))
    mac_entry.grid(row=0, column=0, sticky='ew', padx=10, pady=10)
    mac_entry.insert(0, "00:00:00:00:00:00")
    
    # Zoom control
    zoom_frame = tk.Frame(input_frame, bg=COLORS['card'])
    zoom_frame.grid(row=2, column=0, sticky='w')
    ttk.Label(zoom_frame, text="Zoom:", style='Body.TLabel', background=COLORS['card']).pack(side='left')
    zoom_var = tk.IntVar(value=DEFAULT_ZOOM)
    zoom_spinbox = ttk.Spinbox(zoom_frame, from_=1, to=20, textvariable=zoom_var, 
                              width=4, style='Modern.TSpinbox')
    zoom_spinbox.pack(side='left', padx=(10, 0))
    
    # Lookup button - use regular tk.Button for better control
    lookup_btn = tk.Button(input_frame, text="Lookup",
                          bg=COLORS['accent'], fg='white',
                          font=('Arial', 10, 'bold'),
                          relief='flat', bd=0, padx=15, pady=8)
    lookup_btn.grid(row=2, column=2, sticky='e')
    
    # Status section
    status_frame = tk.Frame(root, bg=COLORS['bg'])
    status_frame.grid(row=2, column=0, sticky='ew', padx=20)
    
    status_var = tk.StringVar(value="Enter a BSSID and press Lookup")
    status_label = ttk.Label(status_frame, textvariable=status_var, style='Body.TLabel')
    status_label.pack(anchor='w')
    
    # Map provider indicator
    provider_var = tk.StringVar(value="")
    provider_label = ttk.Label(status_frame, textvariable=provider_var, style='Body.TLabel')
    provider_label.pack(anchor='e')
    
    # Map display section
    map_frame = ttk.Frame(root, style='Modern.TFrame', padding=10)
    map_frame.grid(row=4, column=0, sticky='nsew', padx=20, pady=15)
    map_frame.columnconfigure(0, weight=1)
    map_frame.rowconfigure(0, weight=1)
    
    # Map canvas with modern border - fixed sizing
    map_canvas = tk.Canvas(map_frame, bg=COLORS['card'], highlightthickness=0,
                          relief='flat', bd=0, width=MAP_WIDTH, height=MAP_HEIGHT)
    map_canvas.grid(row=0, column=0, sticky='nsew')
    map_canvas.grid_propagate(False)  # Prevent canvas from shrinking
    
    # Placeholder text
    placeholder_text = map_canvas.create_text(MAP_WIDTH//2, MAP_HEIGHT//2, 
                                            text="Map will appear here\nafter lookup",
                                            fill=COLORS['text_secondary'], 
                                            font=('Arial', 14), 
                                            justify='center')
    
    # Actions section
    actions_frame = tk.Frame(root, bg=COLORS['bg'])
    actions_frame.grid(row=5, column=0, sticky='ew', padx=20, pady=(0, 20))
    
    def open_in_maps(lat: float, lon: float, zoom: int):
        """Open location in Google Maps with a pin."""
        # Use the correct Google Maps URL format with a pin
        google_url = f"https://www.google.com/maps/place/{lat},{lon}/@{lat},{lon},{zoom}z"
        webbrowser.open(google_url)
    
    def open_in_osm(lat: float, lon: float, zoom: int):
        """Open location in OpenStreetMap."""
        osm_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map={zoom}/{lat}/{lon}"
        webbrowser.open(osm_url)
    
    def copy_coordinates(lat: float, lon: float):
        """Copy coordinates to clipboard."""
        coords = f"{lat:.8f},{lon:.8f}"
        root.clipboard_clear()
        root.clipboard_append(coords)
        # Show temporary feedback
        original_text = status_var.get()
        status_var.set("Coordinates copied to clipboard!")
        root.after(2000, lambda: status_var.set(original_text))
    
    def perform_lookup():
        """Main lookup function."""
        mac = mac_entry.get().strip()
        zoom = zoom_var.get()
        
        # Clear previous results
        for widget in actions_frame.winfo_children():
            widget.destroy()
        map_canvas.delete("all")
        provider_var.set("")
        
        # Show loading state
        status_var.set("Looking up location...")
        root.update()
        
        # Perform lookup
        result = lookup_location(mac)
        
        if isinstance(result, tuple):
            lat, lon = result
            try:
                # Get map image
                map_image, provider = get_map_image(lat, lon, zoom)
                
                # Display map with proper sizing
                photo = ImageTk.PhotoImage(map_image)
                map_canvas.delete("all")  # Clear previous content
                map_canvas.configure(width=map_image.width, height=map_image.height)
                map_canvas.create_image(map_image.width//2, map_image.height//2, image=photo)
                map_canvas.image = photo  # Prevent garbage collection
                
                # Update status
                status_var.set(f"Location found: {lat:.6f}, {lon:.6f}")
                provider_var.set(f"Map: {provider}")
                
                # Add action buttons with better styling
                btn_frame = tk.Frame(actions_frame, bg=COLORS['bg'])
                btn_frame.pack(fill='x')
                
                # Create buttons with explicit styling
                copy_btn = tk.Button(btn_frame, text="Copy Coordinates",
                                   command=lambda: copy_coordinates(lat, lon),
                                   bg=COLORS['accent'], fg='white', 
                                   font=('Arial', 10, 'bold'),
                                   relief='flat', bd=0, padx=15, pady=8)
                copy_btn.pack(side='left', padx=(0, 10))
                
                maps_btn = tk.Button(btn_frame, text="Open in Google Maps",
                                   command=lambda: open_in_maps(lat, lon, zoom),
                                   bg=COLORS['accent'], fg='white',
                                   font=('Arial', 10, 'bold'),
                                   relief='flat', bd=0, padx=15, pady=8)
                maps_btn.pack(side='left', padx=(0, 10))
                
                osm_btn = tk.Button(btn_frame, text="Open in OSM",
                                  command=lambda: open_in_osm(lat, lon, zoom),
                                  bg=COLORS['accent'], fg='white',
                                  font=('Arial', 10, 'bold'),
                                  relief='flat', bd=0, padx=15, pady=8)
                osm_btn.pack(side='left')
                
            except Exception as e:
                status_var.set(f"Failed to load map: {str(e)}")
                map_canvas.create_text(MAP_WIDTH//2, MAP_HEIGHT//2, 
                                     text=f"Map loading failed\n{str(e)[:50]}...",
                                     fill=COLORS['error'], 
                                     font=('Arial', 12), 
                                     justify='center')
        else:
            status_var.set(f"Error: {result}")
            map_canvas.create_text(MAP_WIDTH//2, MAP_HEIGHT//2, 
                                 text="Location not found\nTry a different BSSID",
                                 fill=COLORS['error'], 
                                 font=('Arial', 14), 
                                 justify='center')
    
    # Wire up events
    lookup_btn.configure(command=perform_lookup)
    root.bind('<Return>', lambda e: perform_lookup())
    mac_entry.bind('<Return>', lambda e: perform_lookup())
    
    # Focus on entry
    mac_entry.focus()
    mac_entry.select_range(0, tk.END)
    
    root.mainloop()


if __name__ == "__main__":
    create_modern_gui()