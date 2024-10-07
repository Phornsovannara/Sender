import cv2
import websockets
import asyncio
import numpy as np
import threading
from kivy.app import App
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.uix.colorpicker import ColorPicker
from kivy.graphics import Color, Rectangle

# WebSocket URIs for the two ESP32 devices
URI_ESP32_1 = "ws://192.168.230.205:81"  # ESP32_1 (e.g., bottom part)
URI_ESP32_2 = "ws://192.168.230.171:81"  # ESP32_2 (e.g., top part)

# Global flag for streaming status
streaming = False

# Convert an RGB tuple to a 16-bit RGB565 value
def rgb_to_rgb565(r, g, b):
    r_565 = np.uint16(r & 0xF8) << 8  # Red component to 5 bits
    g_565 = np.uint16(g & 0xFC) << 3  # Green component to 6 bits
    b_565 = np.uint16(b) >> 3         # Blue component to 5 bits
    return r_565 | g_565 | b_565

# Function to send the frame data in smaller chunks
async def send_frame_data(websocket, frame_rgb565, chunk_size=1024 * 8):
    frame_bytes = frame_rgb565.tobytes()  # Convert the frame to bytes
    for i in range(0, len(frame_bytes), chunk_size):
        chunk = frame_bytes[i:i + chunk_size]
        await websocket.send(chunk)  # Send data in chunks

# Function to send image data to a specific ESP32 device
async def send_image_part(websocket, image_part):
    try:
        # Convert the image part to RGB565 format (16-bit per pixel)
        image_rgb565 = np.zeros((image_part.shape[0], image_part.shape[1]), dtype=np.uint16)
        for y in range(image_part.shape[0]):
            for x in range(image_part.shape[1]):
                r, g, b = image_part[y, x]
                image_rgb565[y, x] = rgb_to_rgb565(r, g, b)

        # Send the image data to the ESP32 in chunks
        await send_frame_data(websocket, image_rgb565)
        print("Image part sent successfully")

    except Exception as e:
        print(f"Error sending image part: {e}")

# Function to send images to both ESP32 devices simultaneously
async def send_image(image_path, websocket1, websocket2):
    # Read the image from the file
    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Unable to load image {image_path}.")
        return

    # Resize the image to match the ESP32 panel resolution (192x128)
    image_resized = cv2.resize(image, (64 * 4, 128 * 2))
    image_rgb = cv2.cvtColor(image_resized, cv2.COLOR_BGR2RGB)

    # Split the image into top and bottom parts
    image_top = image_rgb[:128, :]  # Top part (192x64)
    image_bottom = image_rgb[128:, :]  # Bottom part (192x64)

    # Send the top part to ESP32_2 and the bottom part to ESP32_1 simultaneously
    await asyncio.gather(
        send_image_part(websocket2, image_top),        # Send top part to ESP32_2
        send_image_part(websocket1, image_bottom)      # Send bottom part to ESP32_1 without rotation
    )

# Function to listen for "K" from both ESP32s
async def listen_for_K(websocket1, websocket2):
    received_K1 = False
    received_K2 = False

    while not (received_K1 and received_K2):
        if not received_K1:
            response1 = await websocket1.recv()
            if response1 == "K":
                print("Received 'K' from ESP32_1")
                received_K1 = True

        if not received_K2:
            response2 = await websocket2.recv()
            if response2 == "K":
                print("Received 'K' from ESP32_2")
                received_K2 = True

    return received_K1 and received_K2

# Function to manage WebSocket connections and image streaming
async def websocket_communication(image_paths, delay_between_images):
    try:
        async with websockets.connect(URI_ESP32_1, timeout=10) as websocket1, \
                   websockets.connect(URI_ESP32_2, timeout=10) as websocket2:
            while streaming:
                for image_path in image_paths:
                    if image_path:  # Only process valid image paths
                        print(f"Sending image: {image_path}")
                        await send_image(image_path, websocket1, websocket2)

                        # Listen for 'K' before sending 'P'
                        print("Waiting for 'K' from both ESP32 devices...")
                        if await listen_for_K(websocket1, websocket2):
                            print("Received 'K'. Sending 'P'...")

                            await asyncio.gather(
                                websocket1.send('P'),
                                websocket2.send('P')
                            )

                        await asyncio.sleep(delay_between_images)
                    if not streaming:
                        break
    except Exception as e:
        print(f"WebSocket error: {e}")

# Start WebSocket communication in a separate thread
def start_websocket_thread(image_paths):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(websocket_communication(image_paths, 0.05))

class ImageSenderApp(App):
    def build(self):
        # Set up the main layout
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)

        # Add background color to the layout
        with layout.canvas.before:
            Color(0.1, 0.1, 0.1, 1)  # Background color
            self.rect = Rectangle(size=layout.size, pos=layout.pos)

        # Bind the size and position updates for the rectangle
        layout.bind(size=self._update_rect, pos=self._update_rect)

       # Title label aligned to the left
        title_label = Label(
            text="TEED", 
            size_hint=(1, None), 
            height=50,  # You can adjust this height as needed
            font_size='24sp', 
            color=(1, 1, 1, 1), 
            halign='left',  # Horizontal alignment
            valign='middle'  # Vertical alignment
        )
        title_label.bind(size=title_label.setter('text_size'))  # Allow text size to change
        layout.add_widget(title_label)

        # Subtitle label centered
        subtitle_label = Label(
            text="Department of Telecommunication and Electronics Engineering", 
            size_hint=(1, None), 
            height=50,  # Adjust height if needed
            font_size='18sp', 
            color=(1, 1, 1, 1), 
            halign='center',  # Center the subtitle
            valign='middle'  # Vertical alignment
        )
        subtitle_label.bind(size=subtitle_label.setter('text_size'))  # Allow text size to change
        layout.add_widget(subtitle_label)

        # Scrollable section for image files
        scroll_layout = ScrollView(size_hint=(1, 0.7))
        self.image_grid = GridLayout(cols=3, padding=10, spacing=10, size_hint_y=None)
        self.image_grid.bind(minimum_height=self.image_grid.setter('height'))

        # Initialize image selection slots
        self.image_paths = [None] * 40
        self.labels = []
        for i in range(40):
            label = Label(text=f"Image {i+1}: No file selected", size_hint_y=None, height=40, color=(1, 1, 1, 1))
            self.labels.append(label)
            self.image_grid.add_widget(label)

            # Update button
            update_button = Button(text="Update", size_hint_y=None, height=40, background_color=(0.3, 0.5, 0.8, 1))
            update_button.bind(on_release=lambda btn, idx=i: self.update_image(idx))
            self.image_grid.add_widget(update_button)

            # Remove button
            remove_button = Button(text="Remove", size_hint_y=None, height=40, background_color=(0.8, 0.4, 0.4, 1))
            remove_button.bind(on_release=lambda btn, idx=i: self.remove_image(idx))
            self.image_grid.add_widget(remove_button)

        scroll_layout.add_widget(self.image_grid)
        layout.add_widget(scroll_layout)

        # Select, Run, and Stop buttons
        buttons_layout = BoxLayout(size_hint=(1, 0.1))
        select_button = Button(text="Select Images", size_hint=(0.33, 1), background_color=(0.3, 0.5, 0.8, 1))
        select_button.bind(on_release=self.select_images)
        buttons_layout.add_widget(select_button)

        run_button = Button(text="Run", size_hint=(0.33, 1), background_color=(0.4, 0.8, 0.4, 1))
        run_button.bind(on_release=self.start_streaming)
        buttons_layout.add_widget(run_button)

        stop_button = Button(text="Stop", size_hint=(0.33, 1), background_color=(0.8, 0.4, 0.4, 1))
        stop_button.bind(on_release=self.stop_streaming)
        buttons_layout.add_widget(stop_button)

        layout.add_widget(buttons_layout)

        return layout

    def _update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def select_images(self, instance):
        # Open file chooser to select multiple images
        file_chooser = FileChooserListView(multiselect=True)
        popup = Popup(title="Select Images", content=file_chooser, size_hint=(0.9, 0.9))

        def on_select(instance):
            selected = file_chooser.selection
            if selected:
                for i, path in enumerate(selected):
                    if i < len(self.image_paths):
                        self.image_paths[i] = path
                        self.labels[i].text = f"Image {i + 1}: {path.split('/')[-1]}"
            popup.dismiss()

        file_chooser.bind(on_submit=lambda *args: on_select(args))
        popup.open()

    def update_image(self, index):
        # Open file chooser to update the selected image
        file_chooser = FileChooserListView()
        popup = Popup(title=f"Update Image {index + 1}", content=file_chooser, size_hint=(0.9, 0.9))

        def on_select(instance):
            selected = file_chooser.selection
            if selected:
                self.image_paths[index] = selected[0]
                self.labels[index].text = f"Image {index + 1}: {selected[0].split('/')[-1]}"
            popup.dismiss()

        file_chooser.bind(on_submit=lambda *args: on_select(args))
        popup.open()

    def remove_image(self, index):
        self.image_paths[index] = None
        self.labels[index].text = f"Image {index + 1}: No file selected"

    def start_streaming(self, instance):
        global streaming
        streaming = True
        threading.Thread(target=start_websocket_thread, args=(self.image_paths,), daemon=True).start()

    def stop_streaming(self, instance):
        global streaming
        streaming = False

if __name__ == "__main__":
    ImageSenderApp().run()
