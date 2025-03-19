import tkinter as tk  # Import tkinter for GUI (Graphical User Interface) components
from tkinter import filedialog, messagebox, ttk  # Import extra GUI functionalities (file dialog, message boxes, and progress bar)
import yt_dlp  # Import yt_dlp for downloading YouTube videos
import os  # Import os to interact with the operating system (e.g., handling files and directories)
import shutil  # Import shutil for system-level operations like checking if FFmpeg is installed
import logging  # Import logging to log any errors or important messages
import json  # Import json to read/write configuration settings in a JSON file
import re  # Import re for using regular expressions, particularly to validate URLs

CONFIG_FILE = "config.json"  # Name of the configuration file
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')  # Set up logging format

# Check if FFmpeg is installed on the system by checking if it's available in the system path
def is_ffmpeg_installed():
    return shutil.which("ffmpeg") is not None  # Returns True if FFmpeg is installed, otherwise False

# Validate if a given directory exists and is writable (if you can save files in it)
def validate_directory(directory):
    return os.path.isdir(directory) and os.access(directory, os.W_OK)  # Returns True if directory is valid

# Validate if the provided URL is a valid YouTube URL using a regular expression
def is_valid_youtube_url(url):
    youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'  # Regex pattern to check YouTube URLs
    return re.match(youtube_regex, url)  # Returns True if URL matches the pattern

# Function to download a YouTube video with progress tracking
def download_video_with_progress(user_input, download_dir, output_format, progress_callback):
    def progress_hook(d):
        if d['status'] == 'downloading':  # If the video is being downloaded
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')  # Get the total file size
            downloaded_bytes = d.get('downloaded_bytes', 0)  # Get the number of bytes already downloaded
            if total_bytes and downloaded_bytes:
                progress = int((downloaded_bytes / total_bytes) * 100)  # Calculate download progress as percentage
            else:
                progress = 0  # If total size is unknown, set progress to 0
            progress_callback(progress)  # Update the progress bar in the GUI

    ydl_opts = {
        'format': 'best',  # Select the best available video format
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),  # Set the file name format (title + extension)
        'noplaylist': True,  # Don't download the entire playlist (only one video)
        'progress_hooks': [progress_hook],  # Use the progress hook to track progress
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',  # Use FFmpeg to convert the video
            'preferedformat': output_format,  # Set the preferred format (MP4, MP3, MOV, etc.)
        }],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # Initialize yt_dlp with the options
            ydl.download([user_input])  # Start downloading the video
    except Exception as e:
        logging.error(f"Download error: {e}")  # Log any errors that occur during the download process

# The main GUI application class for downloading YouTube videos
class DownloadManagerApp:
    def __init__(self, root):
        self.root = root  # Create the root window (the main GUI window)
        self.root.title("YouTube Video Downloader")  # Set the window title
        self.root.geometry("500x500")  # Set the window size (500x500 pixels)
        self.download_directory, self.dark_mode = load_config()  # Load saved settings for the download directory and dark mode

        # Label to show "Download Directory:"
        self.dir_label = tk.Label(root, text="Download Directory:")
        self.dir_label.pack(pady=5)  # Pack it into the window with padding for spacing

        # Text entry field where the user can see and edit the download directory
        self.dir_entry = tk.Entry(root, width=50)
        self.dir_entry.insert(0, self.download_directory)  # Insert the default directory path
        self.dir_entry.pack(pady=5)

        # Button to change the download directory by opening a file dialog
        self.change_dir_button = tk.Button(root, text="Change Directory", command=self.change_directory)
        self.change_dir_button.pack(pady=5)

        # Label for "Enter YouTube URL or Search Term:"
        self.input_label = tk.Label(root, text="Enter YouTube URL or Search Term:")
        self.input_label.pack(pady=5)

        # Text entry field for entering YouTube URL or search term
        self.input_entry = tk.Entry(root, width=50)
        self.input_entry.pack(pady=5)

        # Label for "Choose Output Format:"
        self.format_label = tk.Label(root, text="Choose Output Format:")
        self.format_label.pack(pady=5)
        
        # Default format is MP4, but user can choose other formats like MP3 or MOV
        self.format_var = tk.StringVar(value="mp4")  # Default value is "mp4"
        self.format_frame = tk.Frame(root)
        self.format_frame.pack()
        self.mp4_button = tk.Radiobutton(self.format_frame, text="MP4", variable=self.format_var, value="mp4")
        self.mp4_button.pack(side="left")  # MP4 button
        self.mp3_button = tk.Radiobutton(self.format_frame, text="MP3", variable=self.format_var, value="mp3")
        self.mp3_button.pack(side="left")  # MP3 button
        self.mov_button = tk.Radiobutton(self.format_frame, text="MOV", variable=self.format_var, value="mov")
        self.mov_button.pack(side="left")  # MOV button

        # Progress bar to show how much of the video has been downloaded
        self.progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=10)

        # Button to start the download when clicked
        self.download_button = tk.Button(root, text="Download", command=self.download_video)
        self.download_button.pack(pady=10)

        # Button to toggle dark mode
        self.dark_mode_button = tk.Button(root, text="Toggle Dark Mode", command=self.toggle_dark_mode)
        self.dark_mode_button.pack(pady=10)

        if self.dark_mode:  # If dark mode is enabled, apply dark theme
            self.toggle_dark_mode()

    # Function to allow the user to change the download directory by selecting a new one
    def change_directory(self):
        new_dir = filedialog.askdirectory(initialdir=self.download_directory, title="Select Download Directory")
        if new_dir:
            self.dir_entry.delete(0, tk.END)  # Clear the existing directory in the text field
            self.dir_entry.insert(0, new_dir)  # Insert the new directory path
            save_config(new_dir, self.dark_mode)  # Save the new directory in the configuration file
            self.download_directory = new_dir  # Update the current download directory

    # Function to update the progress bar during the download
    def update_progress(self, value):
        self.progress['value'] = value  # Set the progress bar value to the new percentage
        self.root.update_idletasks()  # Update the window to reflect the progress change

    # Function to handle the download process
    def download_video(self):
        user_input = self.input_entry.get()  # Get the URL or search term from the input field
        if not is_valid_youtube_url(user_input):  # Check if the input is a valid YouTube URL
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")  # Show error if invalid
            return

        output_format = self.format_var.get()  # Get the selected output format (e.g., MP4, MP3, MOV)
        
        # Check if the video has already been downloaded
        video_title = self.get_video_title(user_input)  # Get the video title for file name
        output_file = os.path.join(self.download_directory, f"{video_title}.{output_format}")  # Construct the file path
        
        # If the file already exists, show an error message
        if os.path.exists(output_file):
            messagebox.showerror("File Already Downloaded", f"The video '{video_title}' has already been downloaded.")
            return
        
        # If the file does not exist, proceed with the download
        download_video_with_progress(user_input, self.download_directory, output_format, self.update_progress)
        messagebox.showinfo("Download Complete", "The video has been downloaded successfully.")  # Notify user when download completes

    # Function to extract the video title from the YouTube URL (used for file name checking)
    def get_video_title(self, user_input):
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(user_input, download=False)  # Extract video info without downloading
            return info.get('title', 'unknown')  # Return the video title (or 'unknown' if not found)

    # Function to toggle between dark mode and light mode for the UI
    def toggle_dark_mode(self):
        bg_color = "#2E2E2E" if not self.dark_mode else "white"  # Set dark background for dark mode
        fg_color = "white" if not self.dark_mode else "black"  # Set white text for dark mode
        self.root.configure(bg=bg_color)  # Apply background color to the root window
        for widget in self.root.winfo_children():  # Loop through all widgets
            try:
                widget.configure(bg=bg_color, fg=fg_color)  # Apply background and text colors to each widget
            except tk.TclError:  # Handle cases where widgets do not support color change
                pass
        self.dark_mode = not self.dark_mode  # Toggle dark mode state
        save_config(self.download_directory, self.dark_mode)  # Save the new dark mode setting

# Function to load configuration settings (download directory and dark mode)
def load_config():
    config_path = get_config_path()  # Get the full path to the config file
    if os.path.exists(config_path):  # Check if the config file exists
        with open(config_path, 'r') as f:
            config = json.load(f)  # Load the config file into a dictionary
            return config.get("download_directory", os.path.expanduser('~\\Downloads')), config.get("dark_mode", False)
    return os.path.expanduser('~\\Downloads'), False  # Default to Downloads folder and light mode if no config found

# Function to get the path of the config file
def get_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)  # Return the absolute path of the config file

# Function to save the download directory and dark mode settings to the config file
def save_config(download_directory, dark_mode):
    config = {
        'download_directory': download_directory,  # Save the download directory
        'dark_mode': dark_mode  # Save the dark mode setting
    }

    config_path = get_config_path()  # Get the full path to the config file
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)  # Save the config dictionary as JSON with indents

# Create the main Tkinter window and run the application
root = tk.Tk()
app = DownloadManagerApp(root)  # Initialize the app with the root window
root.mainloop()  # Start the Tkinter event loop to show the window and wait for user interaction
