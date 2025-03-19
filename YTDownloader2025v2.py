# Import the tkinter library for creating the GUI
import tkinter as tk
# Import specific modules from tkinter for file dialogs, message boxes, and themed widgets
from tkinter import filedialog, messagebox, ttk
# Import yt_dlp library which is used for downloading YouTube videos
import yt_dlp
# Import os module for file and directory operations
import os
# Import shutil for high-level file operations and finding executables
import shutil
# Import logging for application logging and debugging
import logging
# Import json for handling JSON data
import json
# Import re for regular expression operations
import re
# Import threading to run downloads in background threads
import threading
# Import unicodedata for normalizing unicode characters in filenames
import unicodedata

# Configure logging with INFO level and format that includes timestamp, level, and message
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set the default download directory to the user's Downloads folder
DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# Define a helper function to safely convert data to JSON format
def safe_json_dumps(data):
    """Safely serialize the data to JSON format, excluding non-serializable types."""
    try:
        # Try to convert the data to JSON with indentation
        return json.dumps(data, indent=4)
    except TypeError:
        # If TypeError occurs (non-serializable types), handle them
        clean_data = {}
        # Iterate through each key-value pair
        for k, v in data.items():
            try:
                # Try to serialize this specific key-value pair
                json.dumps({k: v})
                # If successful, add to clean_data
                clean_data[k] = v
            except TypeError:
                # If this item can't be serialized, convert it to string
                clean_data[k] = str(v)
        # Return the cleaned data as JSON
        return json.dumps(clean_data, indent=4)

# Define a function to check if FFmpeg is installed
def is_ffmpeg_installed():
    """Checks if FFmpeg is installed by verifying if it's in the system path."""
    # shutil.which returns the path to the executable if found, None otherwise
    return shutil.which("ffmpeg") is not None

# Define a function to validate if a directory exists and is writable
def validate_directory(directory):
    """Checks if the given directory exists and is writable."""
    # Check if path is a directory AND has write permissions
    return os.path.isdir(directory) and os.access(directory, os.W_OK)

# Define a function to validate YouTube URLs using regex
def is_valid_youtube_url(url):
    """Validates if a given URL is a valid YouTube link."""
    # Define a regular expression pattern for YouTube URLs
    youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'
    # Return True if the URL matches the pattern, False otherwise
    return re.match(youtube_regex, url)

# Define a function to sanitize filenames by removing invalid characters
def sanitize_filename(filename):
    """Sanitizes a filename by removing invalid characters and normalizing."""
    # Normalize unicode characters to their closest ASCII representation
    filename = unicodedata.normalize('NFKD', filename)
    # Replace spaces with underscores for better compatibility
    filename = filename.replace(' ', '_')
    # Remove any characters that aren't alphanumeric, underscore, hyphen, or period
    filename = re.sub(r'[^\w\-_\.]', '', filename)
    # Return the sanitized filename
    return filename

# Define the main download function with progress tracking
def download_video_with_progress(user_input, download_dir, output_format, progress_callback):
    """Downloads a YouTube video with progress tracking."""
    # Define a nested function to handle progress updates
    def progress_hook(d):
        # Check if the current status is 'downloading'
        if d['status'] == 'downloading':
            # Get total bytes (use estimate if exact value not available)
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            # Get downloaded bytes (defaulting to 0 if not available)
            downloaded_bytes = d.get('downloaded_bytes', 0)
            # Calculate progress percentage if both values are available
            if total_bytes and downloaded_bytes:
                progress = int((downloaded_bytes / total_bytes) * 100)
            else:
                # Default to 0 if we can't calculate
                progress = 0
            # Call the progress callback with the percentage
            progress_callback(progress)
        # Check if download is finished
        elif d['status'] == 'finished':
            # Set progress to 95% (saving some progress for conversion)
            progress_callback(95)

    # Create a filename template that includes the format type
    filename_template = os.path.join(download_dir, f'%(title).100s-{output_format}.%(ext)s')
    
    # Set up the basic options for yt-dlp
    ydl_opts = {
        'noplaylist': True,          # Don't download playlists, just single videos
        'progress_hooks': [progress_hook],  # Set the progress hook function
        'outtmpl': filename_template,  # Set the output filename template
        'restrictfilenames': True,    # Restrict filenames to ASCII characters
        'quiet': True,                # Reduce terminal output
        'no_warnings': True,          # Suppress warnings
        'logger': None,               # Disable yt-dlp's logger
    }
    
    # Try to find FFmpeg executable path
    ffmpeg_path = shutil.which("ffmpeg")
    # If FFmpeg is found, add its location to the options
    if ffmpeg_path:
        ydl_opts['ffmpeg_location'] = ffmpeg_path
    
    # Configure format-specific options based on the selected output format
    if output_format == 'mp3':
        # Update options for MP3 audio format
        ydl_opts.update({
            'format': 'bestaudio',  # Get the best audio quality
            'postprocessors': [{     # Set up post-processing for audio extraction
                'key': 'FFmpegExtractAudio',  # Use FFmpeg to extract audio
                'preferredcodec': 'mp3',      # Convert to MP3
                'preferredquality': '192',    # Set bitrate to 192kbps
            }],
        })
    elif output_format == 'mp4':
        # Update options for MP4 video format
        ydl_opts.update({
            'format': 'best[ext=mp4]/best',  # Try to get MP4, otherwise get best quality
            # Add FFmpeg parameters to help with codec detection
            'postprocessor_args': {
                'ffmpeg': ['-analyzeduration', '100M', '-probesize', '100M']
            },
        })
    elif output_format == 'mov':
        # Update options for MOV video format
        ydl_opts.update({
            'format': 'best[ext=mp4]/best',  # First get the best mp4/video format
            'merge_output_format': 'mov',    # Set the output format to MOV
        })

    try:
        # Log the start of the download
        logging.info(f"Starting download for {output_format} format")
        # Create a YoutubeDL object with the configured options
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract video info without downloading
            info = ydl.extract_info(user_input, download=False)
            # Get the video title (or use 'Unknown title' if not available)
            video_title = info.get('title', 'Unknown title')
            # Log the video title
            logging.info(f"Downloading: {video_title}")
            # Start the actual download
            ydl.download([user_input])
        # Log completion of download
        logging.info(f"Download completed: {video_title}")
        # Set progress to 100% when done
        progress_callback(100)
    except Exception as e:
        # Log any errors that occur during download
        logging.error(f"Download error: {e}", exc_info=True)
        # Re-raise the exception so it can be caught by the calling function
        raise

# Define the main application class
class DownloadManagerApp:
    """GUI Application for downloading YouTube videos."""
    def __init__(self, root):
        # Store the root window
        self.root = root
        # Set the window title
        self.root.title("YouTube Video Downloader")
        # Set the window size
        self.root.geometry("500x500")
        # Set the initial download directory
        self.download_directory = DEFAULT_DOWNLOAD_DIR
        # Set dark mode flag to False initially
        self.dark_mode = False
        
        # Create a label for the download directory
        self.dir_label = tk.Label(root, text="Download Directory:")
        # Position the label with padding
        self.dir_label.pack(pady=5)
        
        # Create an entry field for the directory
        self.dir_entry = tk.Entry(root, width=50)
        # Set the initial value to the default download directory
        self.dir_entry.insert(0, self.download_directory)
        # Position the entry field
        self.dir_entry.pack(pady=5)
        
        # Create a button to change the directory
        self.change_dir_button = tk.Button(root, text="Change Directory", command=self.change_directory)
        # Position the button
        self.change_dir_button.pack(pady=5)
        
        # Create a label for the URL input field
        self.input_label = tk.Label(root, text="Enter YouTube URL:")
        # Position the label
        self.input_label.pack(pady=5)
        
        # Create an entry field for the YouTube URL
        self.input_entry = tk.Entry(root, width=50)
        # Position the entry field
        self.input_entry.pack(pady=5)
        
        # Create a label for the output format selection
        self.format_label = tk.Label(root, text="Choose Output Format:")
        # Position the label
        self.format_label.pack(pady=5)
        # Create a variable to store the selected format, with "mp4" as default
        self.format_var = tk.StringVar(value="mp4")
        # Create a frame to hold the format radio buttons
        self.format_frame = tk.Frame(root)
        # Position the frame
        self.format_frame.pack()
        # Create a radio button for MP4 format
        self.mp4_button = tk.Radiobutton(self.format_frame, text="MP4", variable=self.format_var, value="mp4")
        # Position the MP4 radio button to the left
        self.mp4_button.pack(side="left")
        # Create a radio button for MP3 format
        self.mp3_button = tk.Radiobutton(self.format_frame, text="MP3", variable=self.format_var, value="mp3")
        # Position the MP3 radio button to the left
        self.mp3_button.pack(side="left")
        # Create a radio button for MOV format
        self.mov_button = tk.Radiobutton(self.format_frame, text="MOV", variable=self.format_var, value="mov")
        # Position the MOV radio button to the left
        self.mov_button.pack(side="left")
        
        # Create a progress bar
        self.progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
        # Position the progress bar
        self.progress.pack(pady=10)
        
        # Create a button to start the download
        self.download_button = tk.Button(root, text="Download", command=self.download_video)
        # Position the download button
        self.download_button.pack(pady=10)
        
        # Create a button to toggle dark mode
        self.dark_mode_button = tk.Button(root, text="Toggle Dark Mode", command=self.toggle_dark_mode)
        # Position the dark mode button
        self.dark_mode_button.pack(pady=10)
        
        # Create a label for status messages
        self.status_label = tk.Label(root, text="Ready")
        # Position the status label
        self.status_label.pack(pady=5)
        
        # Check if FFmpeg is installed when the app starts
        if not is_ffmpeg_installed():
            # Show a warning message if FFmpeg is not found
            messagebox.showwarning("FFmpeg Not Found", 
                                  "FFmpeg is not found on your system. This application requires FFmpeg for conversion. "
                                  "Please install FFmpeg and restart the application.")

    # Define a method to change the download directory
    def change_directory(self):
        """Change the download directory."""
        # Open a directory selection dialog
        new_dir = filedialog.askdirectory(initialdir=self.download_directory, title="Select Download Directory")
        # If a directory was selected (not canceled)
        if new_dir:
            # Clear the current directory entry
            self.dir_entry.delete(0, tk.END)
            # Insert the new directory
            self.dir_entry.insert(0, new_dir)
            # Update the download_directory variable
            self.download_directory = new_dir

    # Define a method to update the progress bar
    def update_progress(self, value):
        """Updates the progress bar."""
        # Set the progress bar value
        self.progress['value'] = value
        # Update status text based on progress value
        status_text = "Converting..." if value >= 95 and value < 100 else f"Downloading: {value}%"
        # Update the status label text
        self.status_label.config(text=status_text)
        # Force an update of the GUI
        self.root.update_idletasks()

    # Define the main download method
    def download_video(self):
        """Starts video download with progress tracking."""
        # Get the URL from the input field and remove whitespace
        user_input = self.input_entry.get().strip()
        # Check if the URL is empty
        if not user_input:
            # Show an error message if no URL is provided
            messagebox.showerror("Error", "Please enter a YouTube URL.")
            return
            
        # Check if the URL is a valid YouTube URL
        if not is_valid_youtube_url(user_input):
            # Show an error message if the URL is invalid
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
            return
        
        # Get the download directory from the entry field
        download_dir = self.dir_entry.get()
        # Check if the directory exists and is writable
        if not validate_directory(download_dir):
            # Show an error message if the directory is invalid
            messagebox.showerror("Invalid Directory", "The download directory does not exist or is not writable.")
            return
            
        # Check if FFmpeg is installed
        if not is_ffmpeg_installed():
            # Show an error message if FFmpeg is not found
            messagebox.showerror("FFmpeg Missing", "FFmpeg is required but not found on your system. Please install FFmpeg and try again.")
            return
        
        # Get the selected output format
        output_format = self.format_var.get()
        
        # Reset the progress bar to 0
        self.progress['value'] = 0
        # Update the status label
        self.status_label.config(text="Starting download...")
        
        # Disable the download button during download
        self.download_button.config(state=tk.DISABLED)
        
        # Define a function to run the download in a separate thread
        def download_thread_func():
            try:
                # Start the download with progress tracking
                download_video_with_progress(user_input, download_dir, output_format, self.update_progress)
                # Schedule updating the status label on the main thread
                # lambda: is an anonymous function that calls status_label.config()
                self.root.after(0, lambda: self.status_label.config(text="Download completed!"))
                # Schedule showing a success message on the main thread
                self.root.after(0, lambda: messagebox.showinfo("Success", "The video has been downloaded successfully."))
            except Exception as e:
                # Get the error message as a string
                error_msg = str(e)
                # Schedule updating the status label with the error on the main thread
                # The lambda here creates a function that truncates long error messages
                self.root.after(0, lambda: self.status_label.config(text=f"Error: {error_msg[:50]}..." if len(error_msg) > 50 else f"Error: {error_msg}"))
                # Schedule showing an error message on the main thread
                self.root.after(0, lambda: messagebox.showerror("Download Failed", f"An error occurred: {error_msg}"))
            finally:
                # Schedule re-enabling the download button on the main thread
                self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
        
        # Create a new thread for the download
        download_thread = threading.Thread(target=download_thread_func)
        # Set the thread as a daemon (will terminate when main program exits)
        download_thread.daemon = True
        # Start the download thread
        download_thread.start()

    # Define a method to toggle dark mode
    def toggle_dark_mode(self):
        """Toggles dark mode on and off."""
        # Set background color based on current mode
        bg_color = "#2E2E2E" if not self.dark_mode else "white"
        # Set foreground (text) color based on current mode
        fg_color = "white" if not self.dark_mode else "black"
        # Set entry field background color
        entry_bg = "#3E3E3E" if not self.dark_mode else "white"
        # Set entry field text color
        entry_fg = "white" if not self.dark_mode else "black"
        
        # Configure the root window background
        self.root.configure(bg=bg_color)
        
        # Update all widgets with new colors
        for widget in self.root.winfo_children():
            # Get the widget type
            widget_type = widget.winfo_class()
            # Check if it's a widget type that needs color update
            if widget_type in ("Label", "Button", "Frame", "Radiobutton"):
                try:
                    # Try to configure background and foreground colors
                    widget.configure(bg=bg_color, fg=fg_color)
                except tk.TclError:
                    # Skip if configuration fails (some widgets might not support these options)
                    pass
            elif widget_type == "Entry":
                try:
                    # Configure entry fields with their specific colors
                    widget.configure(bg=entry_bg, fg=entry_fg)
                except tk.TclError:
                    # Skip if configuration fails
                    pass
        
        # Toggle the dark mode flag
        self.dark_mode = not self.dark_mode

# Check if this script is being run directly (not imported)
if __name__ == "__main__":
    # Create the main Tkinter window
    root = tk.Tk()
    # Create an instance of the DownloadManagerApp
    app = DownloadManagerApp(root)
    # Start the Tkinter event loop
    root.mainloop()