import tkinter as tk  # Importing tkinter for the GUI
from tkinter import filedialog, messagebox, ttk  # Importing extra GUI components like file dialogs, message boxes, and progress bars
import yt_dlp  # Importing yt-dlp to handle downloading YouTube videos
import os  # Importing os for file and directory management
import shutil  # Importing shutil to check if FFmpeg is installed
import logging  # Importing logging to handle error logging
import json  # Importing json for saving and loading configuration settings
import re  # Importing re for validating YouTube URLs
import threading  # Importing threading to handle video downloads in the background
import queue  # Importing queue for managing thread communication

CONFIG_FILE = "config.json"  # Name of the configuration file to store settings
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')  # Setting up logging to track info and errors

# Function to check if FFmpeg is installed
def is_ffmpeg_installed():
    """Checks if FFmpeg is installed by verifying if it's in system path."""
    return shutil.which("ffmpeg") is not None  # If FFmpeg is in the system path, return True, else False

# Function to validate if a given directory is accessible and writable
def validate_directory(directory):
    """Checks if the given directory exists and is writable."""
    return os.path.isdir(directory) and os.access(directory, os.W_OK)  # Returns True if the directory exists and can be written to

# Function to validate a YouTube URL using a regular expression
def is_valid_youtube_url(url):
    """Validates if a given URL is a valid YouTube link."""
    youtube_regex = (
        r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'  # Regular expression to match YouTube URLs
    )
    return re.match(youtube_regex, url)  # Checks if the input URL matches the pattern

# Function to load saved configuration settings (like download directory and dark mode)
def load_config():
    """Loads the configuration from the config file."""
    if os.path.exists(CONFIG_FILE):  # If the config file exists
        with open(CONFIG_FILE, "r") as file:  # Open the config file in read mode
            config = json.load(file)  # Load the JSON data from the file
            return config.get("download_directory", os.getcwd()), config.get("dark_mode", False)  # Return saved settings or defaults
    return os.getcwd(), False  # Return default settings if config file is not found

# Function to save configuration settings (like download directory and dark mode) to a config file
def save_config(download_directory, dark_mode):
    """Saves the configuration to the config file."""
    config = {"download_directory": download_directory, "dark_mode": dark_mode}  # Create a dictionary of the settings
    with open(CONFIG_FILE, "w") as file:  # Open the config file in write mode
        json.dump(config, file)  # Save the dictionary as JSON to the config file

# Function to download a YouTube video with progress tracking
def download_video_with_progress(user_input, download_dir, output_format, progress_callback, q):
    """Downloads a YouTube video with progress tracking."""
    
    def progress_hook(d):
        """Progress hook to update the progress bar."""
        if d['status'] == 'downloading':  # If the video is currently downloading
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')  # Get the total file size
            downloaded_bytes = d.get('downloaded_bytes', 0)  # Get the amount downloaded so far
            if total_bytes and downloaded_bytes:  # If the total size and downloaded size are available
                progress = int((downloaded_bytes / total_bytes) * 100)  # Calculate the download progress percentage
            else:
                progress = 0  # If total size is unknown, set progress to 0
            q.put(progress)  # Put the progress value in the queue for the main thread to update the progress bar

    # yt-dlp options for video download
    ydl_opts = {
        'format': 'best',  # Download the best available format
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),  # Save the file with the video title and appropriate extension
        'noplaylist': True,  # Disable downloading entire playlists (only download the single video)
        'progress_hooks': [progress_hook],  # Set the progress hook to track download progress
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',  # Use FFmpeg for converting the video after download
            'preferedformat': output_format,  # Convert the video to the selected output format (e.g., mp4, mp3, mov)
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # Initialize the yt-dlp downloader with the options
            ydl.download([user_input])  # Download the video from the given URL
        q.put("Download Complete")  # Send a completion message to the main thread
    except Exception as e:
        logging.error(f"Download error: {e}")  # Log any errors during the download process
        q.put(f"Download Error: {e}")  # Send the error message to the main thread

# GUI application class for downloading YouTube videos
class DownloadManagerApp:
    """GUI Application for downloading YouTube videos."""
    def __init__(self, root):
        self.root = root  # Main window reference
        self.root.title("YouTube Video Downloader")  # Set window title
        self.root.geometry("500x500")  # Set window size
        self.download_directory, self.dark_mode = load_config()  # Load saved settings from the config file

        # GUI components for download directory
        self.dir_label = tk.Label(root, text="Download Directory:")
        self.dir_label.pack(pady=5)  # Add the label to the window with padding
        
        self.dir_entry = tk.Entry(root, width=50)  # Entry widget for the download directory
        self.dir_entry.insert(0, self.download_directory)  # Set the current directory as the default value
        self.dir_entry.pack(pady=5)
        
        self.change_dir_button = tk.Button(root, text="Change Directory", command=self.change_directory)  # Button to change directory
        self.change_dir_button.pack(pady=5)

        # GUI components for YouTube URL input
        self.input_label = tk.Label(root, text="Enter YouTube URL or Search Term:")
        self.input_label.pack(pady=5)
        
        self.input_entry = tk.Entry(root, width=50)  # Entry widget for the YouTube URL or search term
        self.input_entry.pack(pady=5)

        # GUI components for output format selection
        self.format_label = tk.Label(root, text="Choose Output Format:")
        self.format_label.pack(pady=5)
        self.format_var = tk.StringVar(value="mp4")  # Set default format to MP4
        self.format_frame = tk.Frame(root)  # Frame to hold the radio buttons for format selection
        self.format_frame.pack()
        
        # Radio buttons for selecting video format
        self.mp4_button = tk.Radiobutton(self.format_frame, text="MP4", variable=self.format_var, value="mp4")
        self.mp4_button.pack(side="left")  # MP4 option
        self.mp3_button = tk.Radiobutton(self.format_frame, text="MP3", variable=self.format_var, value="mp3")
        self.mp3_button.pack(side="left")  # MP3 option
        self.mov_button = tk.Radiobutton(self.format_frame, text="MOV", variable=self.format_var, value="mov")
        self.mov_button.pack(side="left")  # MOV option

        # Progress bar for showing download progress
        self.progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=10)

        # Button to start downloading the video
        self.download_button = tk.Button(root, text="Download", command=self.download_video)
        self.download_button.pack(pady=10)

        # Button to toggle between light and dark modes
        self.dark_mode_button = tk.Button(root, text="Toggle Dark Mode", command=self.toggle_dark_mode)
        self.dark_mode_button.pack(pady=10)

        # Queue to communicate between threads (for progress updates)
        self.q = queue.Queue()

        # If dark mode is enabled, apply dark mode to the window
        if self.dark_mode:
            self.toggle_dark_mode()

    def change_directory(self):
        """Change the download directory."""
        new_dir = filedialog.askdirectory(initialdir=self.download_directory, title="Select Download Directory")  # Open file dialog
        if new_dir:  # If the user selects a new directory
            self.dir_entry.delete(0, tk.END)  # Clear the current directory entry
            self.dir_entry.insert(0, new_dir)  # Set the new directory
            save_config(new_dir, self.dark_mode)  # Save the new directory setting
            self.download_directory = new_dir  # Update the download directory

    def start_download_thread(self):
        """Start the video download process in a separate thread."""
        user_input = self.input_entry.get()  # Get the YouTube URL or search term entered by the user
        if not is_valid_youtube_url(user_input):  # If the URL is not valid
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")  # Show error message
            return

        output_format = self.format_var.get()  # Get the selected output format (mp4, mp3, or mov)
        
        # Start the download in a separate thread to prevent blocking the GUI
        download_thread = threading.Thread(target=download_video_with_progress,
                                           args=(user_input, self.download_directory, output_format, self.update_progress, self.q))
        download_thread.start()  # Start the download thread

        # Periodically check the download progress
        self.root.after(100, self.check_download_progress)

    def check_download_progress(self):
        """Check the queue for new progress updates."""
        try:
            while True:  # Try to get all progress updates from the queue
                progress = self.q.get_nowait()  # Non-blocking check of the queue
                if isinstance(progress, int):  # If the progress is an integer (percentage)
                    self.update_progress(progress)  # Update the progress bar
                elif isinstance(progress, str):  # If the progress is a string (message)
                    messagebox.showinfo("Download Status", progress)  # Show a message box with the status
        except queue.Empty:  # If the queue is empty, just pass
            pass

        # Continue checking the download progress every 100 ms
        self.root.after(100, self.check_download_progress)

    def update_progress(self, value):
        """Update the progress bar based on the value."""
        self.progress['value'] = value  # Set the progress bar value
        self.root.update_idletasks()  # Update the GUI

    def download_video(self):
        """Start the download process when the user presses the download button."""
        self.start_download_thread()  # Start the download in a separate thread

    def toggle_dark_mode(self):
        """Toggles dark mode on and off."""
        bg_color = "#2E2E2E" if not self.dark_mode else "white"  # Set background color depending on dark mode
        fg_color = "white" if not self.dark_mode else "black"  # Set foreground color depending on dark mode
        self.root.configure(bg=bg_color)  # Apply background color to the root window
        for widget in self.root.winfo_children():  # Loop through all widgets in the window
            try:
                widget.configure(bg=bg_color, fg=fg_color)  # Set background and foreground color for each widget
            except tk.TclError:  # Some widgets don't support color settings
                pass
        self.dark_mode = not self.dark_mode  # Toggle the dark mode setting
        save_config(self.download_directory, self.dark_mode)  # Save the updated dark mode setting

# Main entry point to run the application
if __name__ == "__main__":
    root = tk.Tk()  # Create the root window
    app = DownloadManagerApp(root)  # Create the app instance
    root.mainloop()  # Start the main event loop to display the GUI

