import tkinter as tk
from tkinter import filedialog, messagebox
import yt_dlp
import os
import subprocess
import shutil
import logging
import json
from tqdm import tqdm
import sys
import re

# File to store the download directory configuration
CONFIG_FILE = "config.json"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Function to load the configuration from a file
def load_config():
    """Load configuration from the file. Returns the download directory."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as file:
                config = json.load(file)
                return config.get("download_directory", "D:\\Downloads 4")
        except (json.JSONDecodeError, IOError):
            logging.error("Error reading configuration. Using default directory.")
            return "D:\\Downloads 4"
    else:
        return "D:\\Downloads 4"  # Default directory if no config file exists

# Function to save the configuration to a file
def save_config(download_directory):
    """Save the download directory to the configuration file."""
    config = {"download_directory": download_directory}
    with open(CONFIG_FILE, 'w') as file:
        json.dump(config, file)

# Function to check if FFmpeg is installed
def is_ffmpeg_installed():
    """Checks if FFmpeg is installed and accessible in the system PATH."""
    return shutil.which("ffmpeg") is not None

# Function to validate if user input is a URL
def is_url(string):
    """Checks if the given string is a valid YouTube URL."""
    return re.match(r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$', string) is not None

# Function to validate download directory (checks if the directory exists and is writable)
def validate_directory(directory):
    """Check if the given directory exists and is writable."""
    if not os.path.isdir(directory):
        logging.error(f"Directory does not exist: {directory}")
        return False
    if not os.access(directory, os.W_OK):
        logging.error(f"Directory is not writable: {directory}")
        return False
    return True

# Function to handle the progress bar updates
def download_progress_hook(d):
    """Progress hook for yt-dlp to show a longer progress bar using tqdm"""
    if d['status'] == 'downloading':
        total_size = d.get('total_bytes') or d.get('total_bytes_estimate')
        if total_size:
            current = d['downloaded_bytes']
            percent = current / total_size * 100
            bar_length = 80  # Length of the progress bar, you can adjust this as needed
            if 'progress_bar' not in globals():
                global progress_bar
                progress_bar = tqdm(total=total_size, unit='B', unit_scale=True, bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]")
            progress_bar.update(current - progress_bar.n)
            progress_bar.set_description(f'{percent:.2f}%')
    elif d['status'] == 'finished':
        if 'progress_bar' in globals():
            progress_bar.n = progress_bar.total
            progress_bar.last_print_n = progress_bar.n
            progress_bar.update(0)
            progress_bar.close()
        print(f"\nDownload finished: {d['filename']}")

# Function to download a video and show a progress bar
def download_video_with_progress(user_input, download_dir, output_format="mp4"):
    """Downloads a YouTube video and converts it to MP4, MOV, or MP3 with a progress bar."""
    
    # Validate download directory before proceeding
    if not validate_directory(download_dir):
        logging.error(f"Download directory '{download_dir}' is invalid. Exiting.")
        sys.exit(1)
    os.makedirs(download_dir, exist_ok=True)  # Ensure the download directory exists

    # yt-dlp options (with progress hooks)
    ydl_opts = {
        'format': 'best',  # Get the best available quality
        'noplaylist': True,  # Prevent downloading entire playlists
        'quiet': False,  # Set to True to suppress output
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),  # Save file in specified folder
        'progress_hooks': [download_progress_hook],  # Hook to track progress
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if is_url(user_input):  # If input is a URL, download directly
                logging.info(f"Downloading video from URL: {user_input}")
                ydl.download([user_input])
            else:  # If input is a search term, find and download the first video
                logging.info(f"Searching for: {user_input}")
                info = ydl.extract_info(f"ytsearch:{user_input}", download=False)
                if info.get('entries'):
                    video = info['entries'][0]  # Get the first search result
                    logging.info(f"Downloading: {video['title']}")
                    ydl.download([video['webpage_url']])
                else:
                    logging.warning("No videos found.")
                    return
    except yt_dlp.DownloadError as e:
        logging.error(f"Download error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
    finally:
        cleanup_partial_downloads(download_dir)  # Always clean up partial downloads

# GUI for the download manager
class DownloadManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("500x300")

        # Load the existing configuration for the download directory
        self.download_directory = load_config()

        # Download directory label and entry field
        self.dir_label = tk.Label(root, text="Download Directory:")
        self.dir_label.pack(pady=10)

        self.dir_entry = tk.Entry(root, width=50)
        self.dir_entry.insert(0, self.download_directory)
        self.dir_entry.pack(pady=5)

        # Change directory button
        self.change_dir_button = tk.Button(root, text="Change Directory", command=self.change_directory)
        self.change_dir_button.pack(pady=5)

        # URL/Keyword input
        self.input_label = tk.Label(root, text="Enter YouTube URL or Search Term:")
        self.input_label.pack(pady=10)

        self.input_entry = tk.Entry(root, width=50)
        self.input_entry.pack(pady=5)

        # Output format selection
        self.format_label = tk.Label(root, text="Choose Output Format:")
        self.format_label.pack(pady=10)

        self.format_var = tk.StringVar(value="mp4")
        self.mp4_button = tk.Radiobutton(root, text="MP4", variable=self.format_var, value="mp4")
        self.mp4_button.pack()
        self.mov_button = tk.Radiobutton(root, text="MOV", variable=self.format_var, value="mov")
        self.mov_button.pack()
        self.mp3_button = tk.Radiobutton(root, text="MP3", variable=self.format_var, value="mp3")
        self.mp3_button.pack()

        # Download button
        self.download_button = tk.Button(root, text="Download", command=self.download_video)
        self.download_button.pack(pady=20)

    def change_directory(self):
        new_dir = filedialog.askdirectory(initialdir=self.download_directory, title="Select Download Directory")
        if new_dir:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, new_dir)
            save_config(new_dir)
            self.download_directory = new_dir

    def download_video(self):
        user_input = self.input_entry.get()
        download_dir = self.dir_entry.get()
        output_format = self.format_var.get()

        if not user_input:
            messagebox.showerror("Input Error", "Please enter a YouTube URL or search term.")
            return

        if not validate_directory(download_dir):
            messagebox.showerror("Directory Error", "The selected download directory is invalid.")
            return

        download_video_with_progress(user_input, download_dir, output_format)
        messagebox.showinfo("Download Complete", "The video has been downloaded successfully.")

if __name__ == "__main__":
    # Check if FFmpeg is installed
    if not is_ffmpeg_installed():
        logging.error("FFmpeg is not installed. Please install it.")
        sys.exit(1)  # Exit the script if FFmpeg is not found

    # Create the main application window
    root = tk.Tk()
    app = DownloadManagerApp(root)

    # Run the Tkinter main loop
    root.mainloop()
