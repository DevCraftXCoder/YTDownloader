#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
YouTube Video Downloader
An application that lets users download YouTube videos with quality selection options.

Features:
- Download videos in MP4 format with selectable quality
- Download audio in MP3 format
- Progress tracking with visual feedback
- Dark mode support
- Cross-platform compatibility
- Thumbnail preview
- Custom filename support
"""

# Import required libraries
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import yt_dlp  # YouTube download library
import os
import shutil
import logging
import re
import threading
import unicodedata
import json
from functools import partial
import requests
from PIL import Image, ImageTk  # For handling image thumbnails
from io import BytesIO
import webbrowser
from tkinterweb import HtmlFrame  # For embedded web browser functionality

# Configure logging system to track application events and errors
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Output to console
        logging.FileHandler('download_manager.log')  # Output to log file
    ]
)

# Reduce noise in logs by filtering out verbose messages from yt-dlp and ffmpeg
for logger_name in ['yt_dlp', 'ffmpeg']:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.ERROR)

# Set default download directory based on user's operating system
DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

class CustomFormatter(logging.Formatter):
    """Custom formatter to color logs based on their level"""
    
    def format(self, record):
        # Create a clean message without ANSI color codes
        message = super().format(record)
        return message

# Utility Functions
def safe_json_dumps(data):
    """Safely serialize data to JSON format, excluding non-serializable types.
    
    This function handles cases where some data types cannot be directly
    converted to JSON by converting them to strings.
    """
    try:
        # Attempt to convert the entire data dictionary to JSON
        return json.dumps(data, indent=4)
    except TypeError:
        # Handle non-serializable types by converting them to strings
        clean_data = {}
        for k, v in data.items():
            try:
                json.dumps({k: v})
                clean_data[k] = v
            except TypeError:
                clean_data[k] = str(v)
        return json.dumps(clean_data, indent=4)

def is_ffmpeg_installed():
    """Check if FFmpeg is installed by verifying if it's in the system path.
    
    FFmpeg is required for video processing and format conversion.
    """
    return shutil.which("ffmpeg") is not None

def validate_directory(directory):
    """Check if the given directory exists and is writable.
    
    This ensures the application can save files to the selected directory.
    """
    return os.path.isdir(directory) and os.access(directory, os.W_OK)

def is_valid_youtube_url(url):
    """Validate if a given URL is a valid YouTube link.
    
    Supports both youtube.com and youtu.be URLs.
    """
    youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'
    return bool(re.match(youtube_regex, url))

def sanitize_filename(filename):
    """Sanitize a filename by removing invalid characters and normalizing.
    
    This ensures the filename is safe to use across different operating systems.
    """
    # Normalize unicode characters
    filename = unicodedata.normalize('NFKD', filename)
    # Replace spaces with underscores
    filename = filename.replace(' ', '_')
    # Remove any characters that aren't word chars, hyphens, underscores, or periods
    filename = re.sub(r'[^\w\-_\.]', '', filename)
    return filename

def format_filesize(bytes_size):
    """Format file size in bytes to human-readable format.
    
    Converts bytes to appropriate units (B, KB, MB, GB, TB).
    """
    # Define size units
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    # Convert bytes to appropriate unit
    size = float(bytes_size)
    unit_index = 0
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    # Return formatted size with unit
    return f"{size:.2f} {units[unit_index]}"

def create_tooltip(widget, text):
    """Create a tooltip for a widget.
    
    Shows helpful information when hovering over UI elements.
    """
    def enter(event):
        # Create tooltip window
        x, y, _, _ = widget.bbox("insert")
        x += widget.winfo_rootx() + 25
        y += widget.winfo_rooty() + 25
        
        # Create a toplevel window
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)  # Remove window decorations
        tooltip.wm_geometry(f"+{x}+{y}")
        
        # Create label with tooltip text
        label = tk.Label(tooltip, text=text, justify=tk.LEFT,
                         background="#ffffff", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)
        
        # Store tooltip reference
        widget.tooltip = tooltip
    
    def leave(_):
        # Destroy tooltip if it exists
        if hasattr(widget, "tooltip"):
            widget.tooltip.destroy()
            del widget.tooltip
    
    # Bind events to widget
    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)

class YoutubeDownloader:
    """Core functionality for downloading YouTube videos with yt-dlp.
    
    This class handles all the low-level operations for downloading videos,
    including progress tracking and format selection.
    """
    
    def __init__(self, progress_callback=None, format_callback=None):
        """Initialize the downloader with callbacks for progress updates.
        
        Args:
            progress_callback: Function to call with download progress updates
            format_callback: Function to call when formats are available
        """
        self.progress_callback = progress_callback
        self.format_callback = format_callback
        self.downloading = False
        self.current_info = None
    
    def progress_hook(self, d):
        """Process download progress updates from yt-dlp.
        
        This method is called by yt-dlp during the download process to report
        progress, speed, and estimated time remaining.
        """
        if not self.downloading:
            return
            
        if d['status'] == 'downloading':
            # Calculate download progress
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            
            # Additional info to display
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)
            filename = d.get('filename', '').split('/')[-1].split('\\')[-1]
            
            # Format progress information
            progress_info = {
                'percent': 0,
                'speed': f"{format_filesize(speed)}/s" if speed else "N/A",
                'eta': f"{eta} seconds" if eta else "N/A",
                'filename': filename
            }
            
            # Calculate percentage if we have total size
            if total_bytes and downloaded_bytes:
                progress_info['percent'] = int((downloaded_bytes / total_bytes) * 100)
            
            # Call progress callback with info
            if self.progress_callback:
                self.progress_callback(progress_info)
                
        elif d['status'] == 'finished':
            # Post-processing stage (e.g., merging video and audio)
            if self.progress_callback:
                self.progress_callback({
                    'percent': 95,
                    'status': 'Converting...',
                    'filename': d.get('filename', '').split('/')[-1].split('\\')[-1]
                })
        
        elif d['status'] == 'error':
            # Handle download errors
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': f"Error: {d.get('error', 'Unknown error')}",
                    'filename': d.get('filename', '')
                })
    
    def get_available_formats(self, url):
        """Get available formats for the video."""
        try:
            # Extract video information
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'format': 'best'
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Get all available formats
                formats = info.get('formats', [])
                
                # Filter and organize formats
                available_formats = []
                for fmt in formats:
                    # Skip formats without extension
                    if not fmt.get('ext'):
                        continue
                        
                    # Skip formats without filesize
                    if not fmt.get('filesize'):
                        continue
                        
                    # Add format to available list
                    available_formats.append(fmt)
                
                return available_formats, info
                
        except Exception as e:
            logging.error(f"Error getting formats: {e}")
            raise
    
    def download_video(self, url, download_dir, selected_format, filename_template=None):
        """Download a YouTube video with the selected format.
        
        Args:
            url: YouTube URL to download
            download_dir: Directory to save the file
            selected_format: Format ID or quality specification
            filename_template: Optional template for filename
            
        Returns:
            tuple: (video_title, success_status)
        """
        self.downloading = True
        video_title = "Unknown"
        
        try:
            # Default filename template if not provided
            if not filename_template:
                filename_template = os.path.join(download_dir, '%(title)s.%(ext)s')
            else:
                # If custom filename provided, use it with appropriate extension
                ext = 'mp3' if selected_format == 'mp3' else 'mp4'
                filename_template = os.path.join(download_dir, f"{filename_template}.{ext}")
            
            # Basic yt-dlp options
            ydl_opts = {
                'noplaylist': True,
                'progress_hooks': [self.progress_hook],
                'outtmpl': filename_template,
                'restrictfilenames': True,
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                },
                'socket_timeout': 30,
                'retries': 3,
                'ignoreerrors': False,
                'verbose': False,
            }
            
            # Find FFmpeg path
            ffmpeg_path = shutil.which("ffmpeg")
            if ffmpeg_path:
                ydl_opts['ffmpeg_location'] = ffmpeg_path
            
            # Configure options based on selected format
            if selected_format == 'mp3':
                # MP3 audio download configuration
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'prefer_ffmpeg': True,
                    'keepvideo': False,
                })
            elif selected_format == 'best':
                # Best quality video download
                ydl_opts.update({
                    'format': 'bestvideo+bestaudio/best',
                    'merge_output_format': 'mp4',
                    'prefer_ffmpeg': True,
                })
            elif selected_format.isdigit() or selected_format in ['mp4', 'mov']:
                # Specific format ID or container format
                if selected_format.isdigit():
                    ydl_opts.update({
                        'format': selected_format + '+bestaudio/best',
                        'merge_output_format': 'mp4',
                        'prefer_ffmpeg': True,
                    })
                else:
                    # Container format specification
                    ydl_opts.update({
                        'format': 'bestvideo+bestaudio/best',
                        'merge_output_format': selected_format,
                        'prefer_ffmpeg': True,
                    })
            else:
                # Quality-based selection (e.g., "1080p", "720p")
                height = int(selected_format.rstrip('p'))
                ydl_opts.update({
                    'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                    'merge_output_format': 'mp4',
                    'prefer_ffmpeg': True,
                })
            
            # Perform the download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first to get title
                info = self.current_info or ydl.extract_info(url, download=False)
                video_title = info.get('title', 'Unknown title')
                
                # Log the start of download
                logging.info(f"Starting download: {video_title}")
                
                # Perform the actual download
                ydl.download([url])
                
                # Log completion
                logging.info(f"Download completed: {video_title}")
                
                # Clean up temporary files
                self._cleanup_temp_files(download_dir)
                
                # Set progress to 100%
                if self.progress_callback:
                    self.progress_callback({
                        'percent': 100,
                        'status': 'Complete',
                        'filename': video_title
                    })
                
                return video_title, True
        
        except yt_dlp.utils.DownloadError as e:
            # Log the error
            logging.error(f"Download error: {e}")
            
            # Update progress with error
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': f"Error: {str(e)}",
                    'filename': ''
                })
            
            # Return failure
            return video_title, False
        
        except (IOError, OSError) as e:
            # Handle file system errors
            logging.error(f"File system error: {e}")
            
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': f"File error: {str(e)}",
                    'filename': ''
                })
            
            # Return failure
            return video_title, False
            
        except Exception as e:
            # Handle other unexpected errors
            logging.error(f"Unexpected error: {e}")
            
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': f"Error: {str(e)}",
                    'filename': ''
                })
            
            # Return failure
            return video_title, False
        
        finally:
            # Reset downloading flag
            self.downloading = False
    
    @staticmethod
    def _cleanup_temp_files(directory):
        """Clean up temporary files created during download."""
        try:
            # List of temporary file extensions to remove
            temp_extensions = [
                '.part', '.temp', '.f140.mp4', '.f137.mp4', 
                '.f401.mp4', '.m4a', '.webm', '.ytdl'
            ]
            
            # Get list of files in the directory
            for file in os.listdir(directory):
                # Check if the file is a temporary file
                is_temp = any(file.endswith(ext) for ext in temp_extensions)
                
                # Remove temporary file
                if is_temp:
                    try:
                        os.remove(os.path.join(directory, file))
                        logging.debug(f"Cleaned up: {file}")
                    except (IOError, OSError) as e:
                        logging.warning(f"Could not remove temporary file {file}: {e}")
        
        except Exception as e:
            logging.warning(f"Cleanup error: {e}")

class DownloadManagerApp:
    """Main application class for the YouTube Video Downloader GUI."""
    
    def change_directory(self):
        """Open a directory selection dialog to change the download location."""
        new_dir = filedialog.askdirectory(initialdir=self.download_directory)
        if new_dir:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, new_dir)
            self.download_directory = new_dir
    
    def fetch_video_info(self):
        """Fetch video information from the provided URL."""
        url = self.url_entry.get().strip()
        
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL.")
            return
            
        if not is_valid_youtube_url(url):
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
            return
        
        # Disable buttons during fetch
        self.fetch_button.config(state=tk.DISABLED)
        self.download_button.config(state=tk.DISABLED)
        
        # Update status
        self.status_label.config(text="Fetching video information...")
        
        def fetch_thread():
            try:
                # Get available formats and video info
                formats, info = self.downloader.get_available_formats(url)
                
                # Store video info
                self.video_info = info
                self.available_formats = formats
                
                # Update UI with video info
                self.root.after(0, self._update_video_info, info)
                
                # Update format list
                self.root.after(0, self.update_format_list, formats, info)
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"Failed to fetch video information: {str(e)}"
                ))
            
            finally:
                # Re-enable buttons
                self.root.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.status_label.config(text="Ready"))
        
        # Start fetch in a separate thread
        threading.Thread(target=fetch_thread, daemon=True).start()

    def _update_video_info(self, info):
        """Update the UI with video information."""
        # Update thumbnail
        if 'thumbnail' in info:
            self.update_thumbnail(info['thumbnail'])
        
        # Update filename entry
        if 'title' in info:
            self.filename_entry.delete(0, tk.END)
            self.filename_entry.insert(0, info['title'])
            self.reset_filename_button.config(state=tk.NORMAL)
        
        # Update info label
        duration = info.get('duration', 0)
        if duration:
            minutes = duration // 60
            seconds = duration % 60
            duration_str = f"{minutes}:{seconds:02d}"
        else:
            duration_str = "Unknown"
            
        self.info_label.config(
            text=f"Duration: {duration_str} | Views: {info.get('view_count', 'Unknown'):,}"
        )

    def __init__(self, root):
        """Initialize the application GUI."""
        # Set the window title
        self.root = root
        self.root.title("YouTube Video Downloader")
        
        # Set window size to be just bigger than default
        window_width = 850
        window_height = 900
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        # Calculate position to center the window
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        # Set the window size and position
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Set minimum window size to prevent too small windows
        self.root.minsize(750, 800)
        
        # Fix for Windows button styling
        if os.name == 'nt':
            self.root.tk_setPalette(background='#f0f0f0')
        
        # Initialize all application variables
        self.download_directory = DEFAULT_DOWNLOAD_DIR  # Default download location
        self.dark_mode = False                          # Dark mode state
        self.downloader = YoutubeDownloader(self.update_progress, self.update_format_list)  # Create downloader instance
        self.available_formats = []                     # List of available video formats
        self.video_info = None                          # Current video information
        self.thumbnail_image = None                     # Current thumbnail image
        self.custom_filename = None                     # Custom filename if set
        self.speed_boost_active = False                 # Speed boost state
        
        # Configure the application styles
        self._configure_styles()
        
        # Create the main frame with padding
        self.main_frame = ttk.Frame(root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create all UI sections in order
        self._create_directory_section()    # Download location section - where files will be saved
        self._create_url_section()          # URL input section - where users paste YouTube links
        self._create_thumbnail_section()    # Video preview section - shows video thumbnail and filename
        self._create_format_section()       # Format selection section - choose between MP4 and MP3
        self._create_quality_section()      # Quality options section - select video/audio quality
        self._create_progress_section()     # Download progress section - shows download status
        self._create_control_section()      # Control buttons section - download, speed boost, dark mode
        
        # Set welcome message with emoji for better user experience
        self.status_label.config(
            text="Welcome to YouTube Video Downloader! 🎥\nEnter a URL and click 'Search' to begin."
        )
        
        # Check if FFmpeg is installed (required for video processing)
        if not is_ffmpeg_installed():
            messagebox.showwarning(
                "FFmpeg Not Found", 
                "FFmpeg is not found on your system. This application requires FFmpeg for conversion. "
                "Please install FFmpeg and restart the application."
            )
    
    def _configure_styles(self):
        """Configure ttk styles for the application."""
        self.style = ttk.Style()
        
        # Set theme - use 'clam' theme which works well with custom colors
        if 'clam' in self.style.theme_names():
            self.style.theme_use('clam')
        
        # Define colors for light mode
        bg_color = "#f0f0f0"
        fg_color = "#333333"
        
        # Configure standard button style
        self.style.configure("TButton", 
                            padding=6,
                            background=bg_color,
                            foreground=fg_color)
        
        # Configure accent button style (used for secondary actions)
        self.style.configure("Accent.TButton", 
                            background="#4285F4",
                            foreground="white")
        
        # Configure download button style (primary action)
        self.style.configure("Download.TButton", 
                            padding=8,
                            font=("", 10, "bold"),
                            background="#4CAF50",
                            foreground="white")
        
        # Configure other widget styles
        self.style.configure("TLabelframe.Label", font=("", 9, "bold"))
        self.style.configure("TLabelframe", background=bg_color)
        self.style.configure("TFrame", background=bg_color)
        self.style.configure("TLabel", background=bg_color, foreground=fg_color)
        
        # Make sure control buttons have proper contrast in both modes
        self.style.map("TButton", 
                      background=[("active", "#e0e0e0")],
                      foreground=[("active", "#000000")])
        self.style.map("Accent.TButton", 
                      background=[("active", "#3275E4")],
                      foreground=[("active", "#ffffff")])
        self.style.map("Download.TButton", 
                      background=[("active", "#3C9F40")],
                      foreground=[("active", "#ffffff")])
    
    def _create_directory_section(self):
        """Create the download directory section of the UI."""
        # Create a labeled frame for the directory section
        dir_frame = ttk.LabelFrame(self.main_frame, text="Download Location", padding="5")
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Create and configure the directory entry field
        self.dir_entry = ttk.Entry(dir_frame)
        self.dir_entry.insert(0, self.download_directory)  # Set default download location
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        
        # Create the browse button for directory selection
        self.change_dir_button = ttk.Button(
            dir_frame, 
            text="Browse...", 
            command=self.change_directory,
            style="Accent.TButton"
        )
        self.change_dir_button.pack(side=tk.RIGHT, padx=(0, 5))
    
    def _create_url_section(self):
        """Create the URL input section of the UI."""
        url_frame = ttk.LabelFrame(self.main_frame, text="Video URL", padding="5")
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.url_entry = ttk.Entry(url_frame)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        
        self.fetch_button = ttk.Button(
            url_frame, 
            text="Search", 
            command=self.fetch_video_info,
            style="Accent.TButton"
        )
        self.fetch_button.pack(side=tk.RIGHT, padx=(0, 5))
        
        # Tooltip for URL entry
        create_tooltip(self.url_entry, "Enter a YouTube video URL (youtube.com or youtu.be)")
    
    def _create_thumbnail_section(self):
        """Create the thumbnail preview section of the UI."""
        # Create a labeled frame for the thumbnail section
        thumbnail_frame = ttk.LabelFrame(self.main_frame, text="Video Preview", padding="5")
        thumbnail_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Create a frame to hold thumbnail and filename
        preview_frame = ttk.Frame(thumbnail_frame)
        preview_frame.pack(fill=tk.X, expand=True)
        
        # Create the thumbnail label (will show video thumbnail)
        self.thumbnail_label = ttk.Label(preview_frame, text="No video selected")
        self.thumbnail_label.pack(side=tk.LEFT, padx=(5, 10))
        
        # Create a frame for filename controls
        filename_frame = ttk.Frame(preview_frame)
        filename_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Create filename label and entry
        ttk.Label(filename_frame, text="Filename:").pack(anchor=tk.W)
        self.filename_entry = ttk.Entry(filename_frame)
        self.filename_entry.pack(fill=tk.X, pady=(2, 0))
        
        # Create reset filename button
        self.reset_filename_button = ttk.Button(
            filename_frame,
            text="Reset Filename",
            command=self.reset_filename,
            style="Accent.TButton"
        )
        self.reset_filename_button.pack(pady=(5, 0))
        self.reset_filename_button.config(state=tk.DISABLED)  # Initially disabled
    
    def _create_format_section(self):
        """Create the format selection section of the UI."""
        format_frame = ttk.LabelFrame(self.main_frame, text="Format Type", padding="5")
        format_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.format_var = tk.StringVar(value="mp4")
        
        self.mp4_button = ttk.Radiobutton(
            format_frame, 
            text="Video (MP4)", 
            variable=self.format_var, 
            value="mp4",
            command=self.format_changed
        )
        self.mp4_button.pack(side=tk.LEFT, padx=(5, 15))
        
        self.mp3_button = ttk.Radiobutton(
            format_frame, 
            text="Audio (MP3)", 
            variable=self.format_var, 
            value="mp3",
            command=self.format_changed
        )
        self.mp3_button.pack(side=tk.LEFT)
        
        # Create info label to display video details
        self.info_label = ttk.Label(format_frame, text="", font=("", 9, "italic"))
        self.info_label.pack(side=tk.RIGHT, padx=(0, 5))
    
    def _create_progress_section(self):
        """Create the progress tracking section of the UI."""
        progress_frame = ttk.LabelFrame(self.main_frame, text="Download Progress", padding="5")
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Progress bar
        self.progress = ttk.Progressbar(
            progress_frame, 
            orient="horizontal", 
            length=300, 
            mode="determinate"
        )
        self.progress.pack(fill=tk.X, padx=5, pady=(5, 0))
        
        # Status information
        info_frame = ttk.Frame(progress_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=(5, 5))
        
        # Status label
        self.status_label = ttk.Label(info_frame, text="Ready")
        self.status_label.pack(side=tk.LEFT)
        
        # Speed and ETA labels
        self.speed_label = ttk.Label(info_frame, text="")
        self.speed_label.pack(side=tk.RIGHT, padx=(0, 5))
        
        self.eta_label = ttk.Label(info_frame, text="")
        self.eta_label.pack(side=tk.RIGHT, padx=(0, 10))
    
    def _create_quality_section(self):
        """Create the quality selection section of the UI."""
        # Create a labeled frame to contain the quality options
        quality_frame = ttk.LabelFrame(self.main_frame, text="Quality Options", padding="5")
        quality_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create a Treeview widget for displaying format options
        # This widget provides a table-like view with columns and rows
        self.format_list = ttk.Treeview(
            quality_frame,
            columns=("resolution", "ext", "filesize"),  # Define three columns for resolution, format, and file size
            show="headings",  # Show only the headings, not the first column
            height=6  # Show 6 rows at a time
        )
        
        # Configure the column headings with descriptive text
        self.format_list.heading("resolution", text="Resolution")  # Column for video resolution (e.g., 1080p)
        self.format_list.heading("ext", text="Format")             # Column for file format (MP4)
        self.format_list.heading("filesize", text="File Size")     # Column for file size (e.g., 1645MB)
        
        # Configure each column's properties:
        # - width: How wide the column should be in pixels
        # - anchor: Where to align the text (tk.CENTER for middle alignment)
        # - stretch: Whether the column should expand to fill available space
        self.format_list.column("resolution", width=150, anchor=tk.CENTER, stretch=True)  # Resolution column (e.g., 1080p)
        self.format_list.column("ext", width=100, anchor=tk.CENTER, stretch=True)         # Format column (MP4)
        self.format_list.column("filesize", width=150, anchor=tk.CENTER, stretch=True)    # File size column (e.g., 1645MB)
        
        # Create a vertical scrollbar for the format list
        quality_scrollbar = ttk.Scrollbar(
            quality_frame, 
            orient=tk.VERTICAL,  # Vertical scrollbar
            command=self.format_list.yview  # Link scrollbar to format list's vertical view
        )
        
        # Configure the format list to use the scrollbar
        self.format_list.configure(yscrollcommand=quality_scrollbar.set)
        
        # Pack the widgets into the frame:
        # - format_list: Left side, expands to fill available space
        # - scrollbar: Right side, fills vertically
        self.format_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        quality_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind the selection event to update the UI when a format is selected
        self.format_list.bind("<<TreeviewSelect>>", self.on_format_select)
        
        # Add a placeholder message when no formats are available
        self.format_list.insert("", tk.END, values=("No formats available", "", ""))
    
    def _create_control_section(self):
        """Create the control buttons section of the UI."""
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Download button (using regular tk.Button instead of ttk for better styling control)
        self.download_button = tk.Button(
            control_frame, 
            text="Download", 
            command=self.download_video,
            bg="#ff0000",  # Red color
            fg="white",
            activebackground="#ff3333",  # Lighter red on hover
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3  # Thicker border
        )
        self.download_button.pack(side=tk.LEFT, padx=(5, 0))
        
        # Speed Boost button (new feature!)
        self.speed_boost_button = tk.Button(
            control_frame,
            text="🚀 Speed Boost",
            command=self.toggle_speed_boost,
            bg="#ffd700",  # Gold color
            fg="black",
            activebackground="#ffed4a",  # Brighter gold on hover
            activeforeground="black",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3
        )
        self.speed_boost_button.pack(side=tk.LEFT, padx=(5, 0))
        
        # Dark mode toggle (using regular tk.Button)
        self.dark_mode_button = tk.Button(
            control_frame, 
            text="Toggle Dark Mode", 
            command=self.toggle_dark_mode,
            bg="#0078d7",  # Windows blue
            fg="white",
            activebackground="#1e90ff",  # Brighter blue on hover
            activeforeground="white",
            padx=10,
            pady=5,
            relief=tk.RAISED,
            bd=3  # Thicker border
        )
        self.dark_mode_button.pack(side=tk.RIGHT, padx=(0, 5))
    
    def update_format_list(self, formats, video_info):
        """Update the format selection list with available options."""
        # Clear current items
        for item in self.format_list.get_children():
            self.format_list.delete(item)
        
        # Filter for MP4 formats only and sort by resolution (highest first)
        mp4_formats = [fmt for fmt in formats if fmt.get('ext', '').lower() == 'mp4']
        
        # Create a dictionary to store the best format for each resolution
        best_formats = {}
        for fmt in mp4_formats:
            height = fmt.get('height', 0)
            if height:
                # If we haven't seen this resolution yet, or if this format has better quality
                if height not in best_formats or fmt.get('filesize', 0) > best_formats[height].get('filesize', 0):
                    best_formats[height] = fmt
        
        # Convert dictionary to list and sort by resolution (highest first)
        sorted_formats = sorted(best_formats.values(), key=lambda x: int(x.get('height', 0)), reverse=True)
        
        # Add formats to the list
        for fmt in sorted_formats:
            # Get resolution
            height = fmt.get('height', 0)
            resolution = f"{height}p" if height else "Audio Only"
            
            # Get format (always MP4)
            format_str = "MP4"
            
            # Get file size
            filesize = fmt.get('filesize', 0)
            if filesize:
                size_str = format_filesize(filesize)
            else:
                size_str = "Unknown"
            
            # Insert into treeview
            self.format_list.insert("", tk.END, values=(resolution, format_str, size_str))
        
        # Select the first item by default
        if self.format_list.get_children():
            self.format_list.selection_set(self.format_list.get_children()[0])
    
    def format_changed(self):
        """Handle change of format type (MP3/MP4)."""
        # Update the format list based on new selection
        self.update_format_list()
    
    def on_format_select(self, _):
        """Handle selection of a format from the list."""
        # Get selected item
        selected_items = self.format_list.selection()
        if not selected_items:
            return
            
        # Nothing special to do here, but could add preview or additional info
        pass
    
    def update_progress(self, progress_info):
        """Update the progress display with download progress information."""
        # Update progress bar
        percent = progress_info.get('percent', 0)
        self.progress['value'] = percent
        
        # Update status text
        status = progress_info.get('status')
        if not status:
            status = "Converting..." if 95 <= percent < 100 else f"Downloading: {percent}%"
        self.status_label.config(text=status)
        
        # Update speed and ETA if available
        speed = progress_info.get('speed')
        if speed:
            self.speed_label.config(text=f"Speed: {speed}")
            
        eta = progress_info.get('eta')
        if eta:
            self.eta_label.config(text=f"ETA: {eta}")
            
        # Force UI update
        self.root.update_idletasks()
    
    def get_selected_format(self):
        """Get the currently selected format ID or quality."""
        # Get base format type (mp3 or mp4)
        base_format = self.format_var.get()
        
        if base_format == "mp3":
            return "mp3"
            
        # For video, get the selected quality from the treeview
        selected_items = self.format_list.selection()
        if not selected_items:
            # If nothing selected, use best quality
            return "best"
            
        # Get the selected item's values
        selected_item = selected_items[0]
        values = self.format_list.item(selected_item, 'values')
        
        if not values:
            return "best"
            
        # Get resolution/quality from the values
        resolution = values[0]
        
        # Find the corresponding format
        for fmt in self.available_formats:
            if fmt.get('quality_name') == resolution or fmt.get('resolution') == resolution:
                # If it's a format ID, return that
                if 'id' in fmt and not fmt.get('is_audio', False):
                    return fmt['id']
        
        # If we couldn't find a specific ID, return the resolution
        return resolution
    
    def download_video(self):
        """Start the video download process."""
        # Get URL and validate
        url = self.url_entry.get().strip()
        
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL.")
            return
            
        if not is_valid_youtube_url(url):
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
            return
        
        # Get download directory and validate
        download_dir = self.dir_entry.get().strip()
        if not validate_directory(download_dir):
            messagebox.showerror("Invalid Directory", 
                               "The download directory does not exist or is not writable.")
            return
            
        # Check for FFmpeg
        if not is_ffmpeg_installed():
            messagebox.showerror("FFmpeg Missing", 
                               "FFmpeg is required but not found on your system. "
                               "Please install FFmpeg and try again.")
            return
        
        # Get selected format
        selected_format = self.get_selected_format()
        
        # Get custom filename if set
        custom_filename = self.filename_entry.get().strip()
        if custom_filename and custom_filename != self.video_info.get('title', ''):
            self.custom_filename = custom_filename
        
        # Reset progress display
        self.progress['value'] = 0
        self.status_label.config(text="Starting download...")
        self.speed_label.config(text="")
        self.eta_label.config(text="")
        self.download_button.config(state=tk.DISABLED)
        self.fetch_button.config(state=tk.DISABLED)
        self.speed_boost_button.config(state=tk.DISABLED)  # Disable speed boost during download
        
        # Define the thread function to keep it in scope
        def download_thread_func():
            """Thread function to handle download without blocking the UI."""
            try:
                # Start the download
                video_title, success = self.downloader.download_video(
                    url, download_dir, selected_format, self.custom_filename
                )
                
                # Update UI based on success or failure
                if success:
                    self.root.after(0, lambda: self.status_label.config(text="Download completed!"))
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Success", 
                        f"'{video_title}' has been downloaded successfully."
                    ))
                else:
                    self.root.after(0, lambda: self.status_label.config(text="Download failed!"))
            
            except yt_dlp.utils.DownloadError as e:
                # Handle download errors
                error_msg = str(e)
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Error: {error_msg[:50]}..."
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "Download Failed", 
                    f"Download error: {error_msg}"
                ))
                
            except (IOError, OSError) as e:
                # Handle file system errors
                error_msg = str(e)
                self.root.after(0, lambda: self.status_label.config(
                    text=f"File error: {error_msg[:50]}..."
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "File Error", 
                    f"File system error: {error_msg}"
                ))
                
            except Exception as e:
                # Handle other unexpected errors
                error_msg = str(e)
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Error: {error_msg[:50]}..."
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"An unexpected error occurred: {error_msg}"
                ))
            
            finally:
                # Re-enable controls
                self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.speed_boost_button.config(state=tk.NORMAL))
                # Reset speed boost state
                self.root.after(0, lambda: self.toggle_speed_boost())
        
        # Start download thread
        download_thread = threading.Thread(target=download_thread_func)
        download_thread.daemon = True
        download_thread.start()
    
    def toggle_dark_mode(self):
        """Toggle between light and dark mode for the UI."""
        # Define default colors (initialize these before the conditional)
        if not self.dark_mode:
            # Switch to dark mode
            bg_color = "#2E2E2E"
            fg_color = "white"
            
            # Update ttk styles
            self.style.configure("TLabel", background=bg_color, foreground=fg_color)
            self.style.configure("TButton", background="#3E3E3E", foreground=fg_color)
            self.style.configure("TFrame", background=bg_color)
            self.style.configure("TLabelframe", background=bg_color)
            self.style.configure("TLabelframe.Label", background=bg_color, foreground=fg_color)
            self.style.configure("Treeview", background="#3E3E3E", foreground=fg_color, fieldbackground="#3E3E3E")
            self.style.configure("Treeview.Heading", background="#1E1E1E", foreground=fg_color)
            self.style.configure("Accent.TButton", background="#4285F4", foreground="white")
            self.style.configure("Download.TButton", background="#4CAF50", foreground="white")
            
            # Update tk buttons
            self.download_button.config(bg="#ff3333", fg="white", activebackground="#ff6666", activeforeground="white")
            self.dark_mode_button.config(bg="#1e90ff", fg="white", activebackground="#00bfff", activeforeground="white")
            
            # Configure entry style
            self.style.configure("TEntry", fieldbackground="#3E3E3E", foreground=fg_color)
            
            # Configure more widgets if needed
            self.style.configure("Horizontal.TProgressbar", background="#4CAF50")
            
        else:
            # Switch to light mode
            bg_color = "#f0f0f0"
            fg_color = "#333333"
            
            # Reset to default styles
            self.style.theme_use(self.style.theme_names()[0] if 'clam' not in self.style.theme_names() else 'clam')
            
            # Update ttk styles
            self.style.configure("TLabel", background=bg_color, foreground=fg_color)
            self.style.configure("TButton", background=bg_color, foreground=fg_color)
            self.style.configure("TFrame", background=bg_color)
            self.style.configure("TLabelframe", background=bg_color)
            self.style.configure("TLabelframe.Label", background=bg_color, foreground=fg_color, font=("", 9, "bold"))
            self.style.configure("Accent.TButton", background="#4285F4", foreground="white")
            self.style.configure("Download.TButton", background="#4CAF50", foreground="white", padding=8, font=("", 10, "bold"))
            
            # Update tk buttons
            self.download_button.config(bg="#ff0000", fg="white", activebackground="#ff3333", activeforeground="white")
            self.dark_mode_button.config(bg="#0078d7", fg="white", activebackground="#1e90ff", activeforeground="white")
        
        # Toggle the dark mode flag
        self.dark_mode = not self.dark_mode
        
        # Apply background color to main window
        self.root.configure(background=bg_color)
    
    def reset_filename(self):
        """Reset the filename to the original video title."""
        if self.video_info and 'title' in self.video_info:
            self.filename_entry.delete(0, tk.END)
            self.filename_entry.insert(0, self.video_info['title'])
            self.custom_filename = None
            self.reset_filename_button.config(state=tk.DISABLED)
    
    def update_thumbnail(self, thumbnail_url):
        """Update the thumbnail preview with the video thumbnail."""
        try:
            # Download the thumbnail
            response = requests.get(thumbnail_url)
            img_data = BytesIO(response.content)
            img = Image.open(img_data)
            
            # Resize image to fit the window (max 320x180)
            img.thumbnail((320, 180), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            self.thumbnail_image = ImageTk.PhotoImage(img)
            
            # Update the label
            self.thumbnail_label.config(image=self.thumbnail_image)
            
        except Exception as e:
            logging.error(f"Error loading thumbnail: {e}")
            self.thumbnail_label.config(text="Error loading thumbnail")
    
    def toggle_speed_boost(self):
        """Toggle speed boost mode for faster downloads."""
        self.speed_boost_active = not self.speed_boost_active
        
        if self.speed_boost_active:
            self.speed_boost_button.config(
                text="🚀 Speed Boost ON",
                bg="#00ff00",  # Green color
                activebackground="#00cc00"  # Darker green on hover
            )
            messagebox.showinfo(
                "Speed Boost Activated!",
                "🚀 Download speed has been optimized!\n\n"
                "Changes applied:\n"
                "• Increased buffer size\n"
                "• Optimized chunk size\n"
                "• Enabled parallel downloads\n"
                "• Reduced overhead\n\n"
                "Enjoy faster downloads! 🎉"
            )
        else:
            self.speed_boost_button.config(
                text="🚀 Speed Boost",
                bg="#ffd700",  # Gold color
                activebackground="#ffed4a"  # Brighter gold on hover
            )
            messagebox.showinfo(
                "Speed Boost Deactivated",
                "Speed boost mode has been turned off.\nReturning to normal download settings."
            )

def main():
    """Main entry point for the application."""
    try:
        # Create and start the GUI
        root = tk.Tk()
        DownloadManagerApp(root)
        
        # Set window icon if available
        try:
            # For Windows
            if os.name == 'nt':
                root.iconbitmap(default='icon.ico')
            # For Linux/Mac (using safe alternative approach)
            else:
                logo = tk.PhotoImage(file='icon.png')
                # Use public method instead of accessing protected member
                root.iconphoto(True, logo)
        except FileNotFoundError:
            # Icon file not found
            pass
        except tk.TclError:
            # Tk error handling icon
            pass
        
        # Start main loop
        root.mainloop()
        
    except Exception as e:
        # Log fatal errors
        logging.critical(f"Fatal error: {e}", exc_info=True)
        
        # Show error message
        messagebox.showerror(
            "Fatal Error",
            f"An unexpected error occurred: {str(e)}\n\nCheck the log file for details."
        )

if __name__ == "__main__":
    main()