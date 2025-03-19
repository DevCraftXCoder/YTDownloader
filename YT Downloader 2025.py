import tkinter as tk  # Import tkinter for GUI
from tkinter import filedialog, messagebox, ttk  # Import extra GUI functionalities
import yt_dlp  # Import yt_dlp for downloading YouTube videos
import os  # Import os for file and directory handling
import shutil  # Import shutil to check for external dependencies like FFmpeg
import logging  # Import logging for logging errors and messages
import json  # Import json for storing and loading configuration settings

CONFIG_FILE = "config.json"  # Define the configuration file name
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')  # Set up logging format

def is_ffmpeg_installed():
    """Checks if FFmpeg is installed by verifying if it's in system path."""
    return shutil.which("ffmpeg") is not None  # Returns True if FFmpeg is found, otherwise False

def validate_directory(directory):
    """Checks if the given directory exists and is writable."""
    return os.path.isdir(directory) and os.access(directory, os.W_OK)  # Returns True if directory is valid

def download_video_with_progress(user_input, download_dir, output_format, progress_callback):
    """Downloads a YouTube video with progress tracking."""
    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            if total_bytes and downloaded_bytes:
                progress = int((downloaded_bytes / total_bytes) * 100)
                progress_callback(progress)

    ydl_opts = {
        'format': 'best',  # Choose best available format
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),  # Set output file template
        'noplaylist': True,  # Prevent downloading entire playlists
        'progress_hooks': [progress_hook],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # Initialize yt_dlp downloader
            ydl.download([user_input])  # Start downloading video
    except Exception as e:
        logging.error(f"Download error: {e}")  # Log any errors

class DownloadManagerApp:
    """GUI Application for downloading YouTube videos."""
    def __init__(self, root):
        self.root = root  # Set root window
        self.root.title("YouTube Video Downloader")  # Set window title
        self.root.geometry("500x400")  # Set window size
        self.download_directory = load_config()  # Load saved download directory
        self.dark_mode = False  # Initialize dark mode state
        
        # Create a label for the download directory
        self.dir_label = tk.Label(root, text="Download Directory:")
        self.dir_label.pack(pady=5)  # Add padding for spacing
        
        # Create an entry field for directory
        self.dir_entry = tk.Entry(root, width=50)
        self.dir_entry.insert(0, self.download_directory)  # Insert default directory
        self.dir_entry.pack(pady=5)
        
        # Create a button to change directory
        self.change_dir_button = tk.Button(root, text="Change Directory", command=self.change_directory)
        self.change_dir_button.pack(pady=5)
        
        # Create a label for input field
        self.input_label = tk.Label(root, text="Enter YouTube URL or Search Term:")
        self.input_label.pack(pady=5)
        
        # Create an entry field for user input
        self.input_entry = tk.Entry(root, width=50)
        self.input_entry.pack(pady=5)
        
        # Create a label for video title preview
        self.title_label = tk.Label(root, text="Video Title: Not yet loaded")
        self.title_label.pack(pady=5)
        
        # Create a label for format selection
        self.format_label = tk.Label(root, text="Choose Output Format:")
        self.format_label.pack(pady=5)
        
        # Create a variable to store selected format
        self.format_var = tk.StringVar(value="mp4")
        
        # Create a frame for format selection
        self.format_frame = tk.Frame(root)
        self.format_frame.pack()
        
        # Create radio buttons for format selection
        self.mp4_button = tk.Radiobutton(self.format_frame, text="MP4", variable=self.format_var, value="mp4")
        self.mp4_button.pack(side="left")
        self.mov_button = tk.Radiobutton(self.format_frame, text="MOV", variable=self.format_var, value="mov")
        self.mov_button.pack(side="left")
        self.mp3_button = tk.Radiobutton(self.format_frame, text="MP3", variable=self.format_var, value="mp3")
        self.mp3_button.pack(side="left")
        
        # Create a progress bar
        self.progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=10)
        
        # Create a button to start download
        self.download_button = tk.Button(root, text="Download", command=self.download_video)
        self.download_button.pack(pady=10)
        
        # Create a button to toggle dark mode
        self.dark_mode_button = tk.Button(root, text="Toggle Dark Mode", command=self.toggle_dark_mode)
        self.dark_mode_button.pack(pady=10)
        
    def change_directory(self):
        """Change the download directory."""
        new_dir = filedialog.askdirectory(initialdir=self.download_directory, title="Select Download Directory")
        if new_dir:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, new_dir)
            save_config(new_dir)  # Save new directory to config
            self.download_directory = new_dir

    def update_progress(self, value):
        """Updates the progress bar."""
        self.progress['value'] = value
        self.root.update_idletasks()

    def download_video(self):
        """Starts video download with progress tracking."""
        user_input = self.input_entry.get()
        download_dir = self.dir_entry.get()
        output_format = self.format_var.get()
        
        if not user_input:
            messagebox.showerror("Input Error", "Please enter a YouTube URL or search term.")
            return
        if not validate_directory(download_dir):
            messagebox.showerror("Directory Error", "Invalid download directory.")
            return
        
        self.progress['value'] = 0  # Reset progress bar
        download_video_with_progress(user_input, download_dir, output_format, self.update_progress)
        messagebox.showinfo("Download Complete", "The video has been downloaded successfully.")
        
    def toggle_dark_mode(self):
        """Toggles dark mode on and off."""
        bg_color = "#2E2E2E" if not self.dark_mode else "white"
        fg_color = "white" if not self.dark_mode else "black"
        
        self.root.configure(bg=bg_color)
        for widget in self.root.winfo_children():
            try:
                widget.configure(bg=bg_color, fg=fg_color)
            except tk.TclError:
                pass  # Some widgets (like progress bars) do not support fg/bg changes
        
        self.dark_mode = not self.dark_mode  # Toggle the state

def load_config():
    """Loads the download directory from config file."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as file:
                config = json.load(file)
                return config.get("download_directory", "D:\\Downloads 4")
        except (json.JSONDecodeError, IOError):
            logging.error("Error reading configuration. Using default directory.")
            return "D:\\Downloads 4"
    return "D:\\Downloads 4"

if __name__ == "__main__":
    root = tk.Tk()
    app = DownloadManagerApp(root)
    root.mainloop()
