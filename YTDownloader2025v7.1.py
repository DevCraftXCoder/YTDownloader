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
import time
import sys
import signal
import tempfile
import glob

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

# Global variables for application state
active_downloads = []  # Track active download threads
thumbnail_cache = {}   # Cache for downloaded thumbnails
info_cache = {}        # Cache for video information

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
    # Limit filename length (common filesystem limitations)
    if len(filename) > 200:
        filename = filename[:197] + "..."
    return filename

def format_filesize(bytes_size):
    """Format file size in bytes to human-readable format.
    
    Converts bytes to appropriate units (B, KB, MB, GB, TB).
    """
    if not bytes_size or bytes_size <= 0:
        return "Unknown"
        
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

def format_duration(duration_seconds):
    """Format duration in seconds to MM:SS or HH:MM:SS format."""
    if not duration_seconds:
        return "Unknown"
        
    minutes, seconds = divmod(int(duration_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"

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

def estimate_filesize(fmt, duration_sec):
    """Estimate file size based on bitrate and duration when exact size is unknown.
    
    Args:
        fmt: Format information from yt-dlp
        duration_sec: Duration of the video in seconds
        
    Returns:
        Estimated file size in bytes or None if estimation not possible
    """
    if not duration_sec or duration_sec <= 0:
        return None
        
    # Get total bitrate (video + audio)
    tbr = fmt.get('tbr') or fmt.get('abr') or 0
    
    if not tbr:
        # Try to calculate from height-based heuristic
        height = fmt.get('height', 0)
        if not height:
            return None
            
        # Approximate bitrates for different resolutions
        if height >= 2160:    # 4K
            tbr = 45000
        elif height >= 1440:  # 2K
            tbr = 25000
        elif height >= 1080:  # Full HD
            tbr = 8000
        elif height >= 720:   # HD
            tbr = 5000
        elif height >= 480:   # SD
            tbr = 2500
        else:                 # Low quality
            tbr = 1500
    
    # Calculate size: bitrate (Kbps) * duration (s) * 1000 / 8 = bytes
    return (tbr * duration_sec * 1000) / 8

class DownloadCancelledError(Exception):
    """Custom exception for cancelled downloads."""
    pass

def get_ffmpeg_path():
    """Get the FFmpeg path, considering both development and PyInstaller environments."""
    if getattr(sys, 'frozen', False):
        # If running as compiled executable
        base_path = sys._MEIPASS
    else:
        # If running in development
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    # Try to find ffmpeg in various locations
    possible_paths = [
        os.path.join(base_path, 'ffmpeg.exe'),
        os.path.join(os.path.dirname(base_path), 'ffmpeg.exe'),
        shutil.which('ffmpeg'),
    ]
    
    for path in possible_paths:
        if path and os.path.exists(path):
            return path
            
    return None

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
        self.cancel_requested = False
        self.ydl_instance = None
        self.download_complete_callback = None
        self.download_error_callback = None
        
        # Initialize FFmpeg path
        self.ffmpeg_path = get_ffmpeg_path()
        if not self.ffmpeg_path:
            logging.warning("FFmpeg not found. Some features may not work properly.")
    
    def progress_hook(self, d):
        logging.info(f"Progress: {d}")
        if not self.downloading or self.cancel_requested:
            if self.cancel_requested and d['status'] == 'downloading':
                raise DownloadCancelledError("Download cancelled by user")
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
                'filename': filename,
                'status': 'downloading'
            }
            
            # Calculate percentage if we have total size
            if total_bytes and downloaded_bytes:
                progress_info['percent'] = int((downloaded_bytes / total_bytes) * 100)
            elif d.get('downloaded_bytes'):
                # If we have downloaded bytes but no total, estimate progress
                progress_info['percent'] = 50  # Show 50% when we can't determine total
            
            # Call progress callback with info
            if self.progress_callback:
                self.progress_callback(progress_info)
                
        elif d['status'] == 'finished':
            # Post-processing stage (e.g., merging video and audio)
            if self.progress_callback:
                self.progress_callback({
                    'percent': 95,
                    'status': 'converting',
                    'filename': d.get('filename', '').split('/')[-1].split('\\')[-1]
                })
        
        elif d['status'] == 'error':
            # Handle download errors
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': 'error',
                    'error': d.get('error', 'Unknown error'),
                    'filename': d.get('filename', '')
                })
    
    def cancel_download(self):
        """Cancel any ongoing download."""
        if self.downloading:
            self.cancel_requested = True
            # Attempt to terminate ydl instance if it exists
            if self.ydl_instance:
                try:
                    self.ydl_instance.interrupt_download()
                except:
                    pass  # Ignore errors in interruption
            return True
        return False
    
    def get_available_formats(self, url):
        """Get available formats for the given YouTube URL.
        
        Args:
            url: YouTube video URL
            
        Returns:
            tuple: (formats, video_info)
        """
        # Check cache first
        if url in info_cache:
            logging.info(f"Using cached info for {url}")
            return info_cache[url]
            
        try:
            # Basic options for format extraction
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'logger': None,
                'ignoreerrors': False,
                'noplaylist': True,
            }
            
            # Extract video information
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                self.current_info = info
                
                if not info:
                    return [], None
                
                # Basic video information
                video_info = {
                    'title': info.get('title', 'Unknown title'),
                    'duration': info.get('duration', 0),
                    'channel': info.get('channel', 'Unknown channel'),
                    'thumbnail': info.get('thumbnail', None),
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', 'Unknown'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'description': info.get('description', ''),
                    'webpage_url': info.get('webpage_url', url),
                    'id': info.get('id', ''),
                }
                
                # Get formats
                formats = []
                
                # Calculate total video duration in seconds (for bitrate-based size estimation)
                duration_sec = info.get('duration', 0)
                
                # Add audio formats
                audio_format = {
                    'id': 'mp3',
                    'ext': 'mp3',
                    'format_note': 'Best Audio (MP3)',
                    'filesize': None,
                    'resolution': 'Audio only',
                    'is_audio': True,
                    'acodec': 'mp3',
                    'abr': 192,  # Typical MP3 bitrate
                }
                
                # Estimate filesize for audio
                audio_size = estimate_filesize({'abr': 192}, duration_sec)
                if audio_size:
                    audio_format['filesize'] = audio_size
                    
                formats.append(audio_format)
                
                # Filter and organize video formats
                video_formats = []
                seen_qualities = set()
                
                # Process available formats
                for fmt in info.get('formats', []):
                    # Skip audio-only formats for video list
                    if fmt.get('vcodec', '') == 'none':
                        continue
                    
                    # Extract format information
                    height = fmt.get('height', 0)
                    width = fmt.get('width', 0)
                    ext = fmt.get('ext', '')
                    
                    # Skip if no resolution info
                    if not height or not width:
                        continue
                    
                    # Create a quality identifier
                    quality_id = f"{height}p"
                    
                    # Skip duplicates of same resolution
                    if quality_id in seen_qualities:
                        continue
                    
                    seen_qualities.add(quality_id)
                    
                    # Try to get file size, with fallbacks
                    filesize = fmt.get('filesize')
                    if not filesize:
                        filesize = fmt.get('filesize_approx')
                    if not filesize:
                        filesize = estimate_filesize(fmt, duration_sec)
                    
                    # Format note and codec info
                    vcodec = fmt.get('vcodec', 'unknown')
                    acodec = fmt.get('acodec', 'unknown')
                    format_note = fmt.get('format_note', '')
                    if not format_note:
                        format_note = f"{vcodec}/{acodec}"
                    
                    # Add this format to our list
                    video_formats.append({
                        'id': fmt['format_id'],
                        'ext': ext,
                        'height': height,
                        'width': width,
                        'format_note': format_note,
                        'filesize': filesize,
                        'resolution': f"{width}x{height}",
                        'quality_name': quality_id,
                        'is_audio': False,
                        'vcodec': vcodec,
                        'acodec': acodec,
                        'tbr': fmt.get('tbr', 0),
                    })
                
                # Sort video formats by height (resolution)
                video_formats.sort(key=lambda x: x['height'], reverse=True)
                
                # Add video formats to main format list
                formats.extend(video_formats)
                
                # Cache results
                info_cache[url] = (formats, video_info)
                
                return formats, video_info
                
        except Exception as e:
            logging.error(f"Error fetching formats: {e}")
            return [], None
    
    def download_video(self, url, download_dir, selected_format, complete_callback=None, error_callback=None):
        """Download a video from the given URL."""
        self.download_complete_callback = complete_callback
        self.download_error_callback = error_callback
        
        try:
            # Configure yt-dlp options
            ydl_opts = {
                'format': selected_format,
                'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
                'progress_hooks': [self.update_progress],
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'nocheckcertificate': True,
                'ignoreerrors': False,
                'no_color': True,
                'prefer_insecure': False,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            }

            # Set FFmpeg path if available
            if self.ffmpeg_path:
                ydl_opts['ffmpeg_location'] = self.ffmpeg_path
                logging.info(f"Using FFmpeg from: {self.ffmpeg_path}")
            else:
                logging.warning("FFmpeg path not set. Some features may not work properly.")

            # Configure format based on selection
            if selected_format == 'mp3':
                if not self.ffmpeg_path:
                    raise ValueError("FFmpeg is required for MP3 conversion but was not found.")
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'prefer_ffmpeg': True,
                    'keepvideo': False
                })
            else:
                # For video formats, ensure we get both video and audio
                ydl_opts.update({
                    'format': f'{selected_format}+bestaudio/best',
                    'merge_output_format': 'mp4',
                    'prefer_ffmpeg': True
                })

            # Create a temporary directory for downloads
            with tempfile.TemporaryDirectory() as temp_dir:
                # Temporarily download to temp directory
                temp_opts = ydl_opts.copy()
                temp_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')

                # Perform the download
                with yt_dlp.YoutubeDL(temp_opts) as ydl:
                    self.ydl_instance = ydl
                    # Extract info first to get title
                    info = ydl.extract_info(url, download=False)
                    video_title = info.get('title', 'Unknown title')
                    
                    # Log the start of download
                    logging.info(f"Starting download: {video_title}")
                    
                    # Download the video
                    ydl.download([url])
                    
                    # Find the downloaded file in temp directory
                    downloaded_files = os.listdir(temp_dir)
                    if downloaded_files:
                        # Get the main downloaded file
                        main_file = downloaded_files[0]
                        source_path = os.path.join(temp_dir, main_file)
                        
                        # Determine the final extension
                        final_ext = 'mp3' if selected_format == 'mp3' else 'mp4'
                        
                        # Create the final filename with format indicator
                        if final_ext == 'mp3':
                            final_filename = f"{video_title} (Audio).{final_ext}"
                        else:
                            final_filename = f"{video_title} (Video).{final_ext}"
                        
                        # Sanitize filename
                        final_filename = "".join(c for c in final_filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
                        final_path = os.path.join(download_dir, final_filename)
                        
                        # If file already exists, add a number
                        counter = 1
                        base_filename = final_filename[:-len(final_ext)-1]
                        while os.path.exists(final_path):
                            if final_ext == 'mp3':
                                final_filename = f"{base_filename} ({counter}) (Audio).{final_ext}"
                            else:
                                final_filename = f"{base_filename} ({counter}) (Video).{final_ext}"
                            final_path = os.path.join(download_dir, final_filename)
                            counter += 1
                        
                        # Move the file to the final location
                        shutil.move(source_path, final_path)
                        
                        # Clean up temporary files
                        for file in glob.glob(os.path.join(temp_dir, '*')):
                            try:
                                if os.path.exists(file) and file != final_path:
                                    os.remove(file)
                            except Exception as e:
                                logging.warning(f"Could not remove temp file {file}: {e}")

                        # Call the completion callback
                        if self.download_complete_callback:
                            self.download_complete_callback(video_title)

            return video_title, True

        except Exception as e:
            logging.error(f"Download error: {str(e)}")
            if self.download_error_callback:
                self.download_error_callback(str(e))
            return str(e), False

    def update_progress(self, d):
        """Update the progress display with download progress information."""
        if d['status'] == 'downloading':
            # Add debug logging to see what's coming in
            logging.debug(f"Download progress data: {d}")
            
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            
            if total_bytes:
                percent = (downloaded_bytes / total_bytes) * 100
                # Make sure this call happens and includes the correct percent value
            if self.progress_callback:
                    self.progress_callback({'percent': percent, 'status': 'downloading'})

class DownloadManagerApp:
    """Main application class for the YouTube Video Downloader GUI."""
    
    def __init__(self, root):
        """Initialize the application GUI."""
        self.root = root
        self.root.title("YouTube Downloader")
        
        # Set window icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except tk.TclError:
                logging.warning("Could not set window icon")
        
        # Set dark theme
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Set window size to be just bigger than default
        window_width = 850
        window_height = 1000  # Increased from 800 to 1000
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        # Calculate position to center the window
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        # Set the window size and position
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Set minimum window size to prevent too small windows
        self.root.minsize(750, 900)  # Increased minimum height from 700 to 900
        
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
        self.active_download_thread = None              # Currently active download thread
        self.thumbnail_load_thread = None               # Thread for loading thumbnails
        self.download_in_progress = False               # Flag for active downloads
        
        # Configure the application styles
        self._configure_styles()
        
        # Create the main frame with padding
        self.main_frame = ttk.Frame(root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create all UI sections in order
        self._create_directory_section()    # Download location section
        self._create_url_section()          # URL input section
        self._create_thumbnail_section()    # Video preview section
        self._create_format_section()       # Format selection section
        self._create_quality_section()      # Quality options section
        self._create_progress_section()     # Download progress section
        self._create_control_section()      # Control buttons section
        
        # Set welcome message
        self.status_label.config(
            text="Welcome to YouTube Video Downloader!\nEnter a URL and click 'Search' to begin."
        )
        
        # Set up close handler to properly clean up resources
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Check if FFmpeg is installed (required for video processing)
        if not is_ffmpeg_installed():
            messagebox.showwarning(
                "FFmpeg Not Found", 
                "FFmpeg is not found on your system. This application requires FFmpeg for conversion. "
                "Please install FFmpeg and restart the application."
            )
            
        # Set initial text colors for all widgets
        self._set_initial_text_colors()
    
    def _set_initial_text_colors(self):
        """Set initial text colors for all widgets."""
        # Set colors for light mode
        bg_color = "#f0f0f0"
        fg_color = "#000000"  # Pure black for better visibility
        entry_bg = "#FFFFFF"  # White background for entries
        entry_fg = "#000000"  # Black text for entries
        
        # Update ttk styles
        self.style.configure("TLabel", background=bg_color, foreground=fg_color)
        self.style.configure("TButton", background=bg_color, foreground=fg_color)
        self.style.configure("TFrame", background=bg_color)
        self.style.configure("TLabelframe", background=bg_color)
        self.style.configure("TLabelframe.Label", background=bg_color, foreground=fg_color)
        self.style.configure("Treeview", background=entry_bg, foreground=fg_color, fieldbackground=entry_bg)
        self.style.configure("Treeview.Heading", background=bg_color, foreground=fg_color)
        self.style.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg)
        
        # Update all frames and their children
        for widget in self.main_frame.winfo_children():
            if isinstance(widget, ttk.Frame):
                widget.configure(style="Main.TFrame")
                # Update all child widgets
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Label):
                        child.configure(foreground=fg_color)
                    elif isinstance(child, ttk.Entry):
                        child.configure(foreground=entry_fg)
                    elif isinstance(child, ttk.Treeview):
                        child.configure(foreground=fg_color)
    
    def _configure_styles(self):
        """Configure custom styles for the application."""
        style = ttk.Style()
        
        # Configure the main frame style
        style.configure("Main.TFrame", background="#ffffff")
        
        # Configure button styles with better contrast
        style.configure(
            "Accent.TButton",
            background="#4285F4",  # Google Blue
            foreground="white",
            padding=5,
            font=("", 10, "bold")
        )
        
        style.configure(
            "SpeedBoost.TButton",
            background="#ffd700",
            foreground="black",
            padding=5,
            font=("", 10, "bold")
        )
        
        style.configure(
            "SpeedBoostActive.TButton",
            background="#00ff00",
            foreground="black",
            padding=5,
            font=("", 10, "bold")
        )
        
        style.configure(
            "DarkMode.TButton",
            background="#0078d7",
            foreground="white",
            padding=5,
            font=("", 10, "bold")
        )
        
        style.configure(
            "Cancel.TButton",
            background="#555555",
            foreground="white",
            padding=5,
            font=("", 10, "bold")
        )
    
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
        self.change_dir_button = tk.Button(
            dir_frame, 
            text="Browse...", 
            command=self.change_directory,
            bg="#4285F4",  # Google Blue
            fg="white",
            activebackground="#5a95f5",
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3
        )
        self.change_dir_button.pack(side=tk.RIGHT, padx=(0, 5))
    
    def _create_url_section(self):
        """Create the URL input section of the UI."""
        url_frame = ttk.LabelFrame(self.main_frame, text="Video URL", padding="5")
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.url_entry = ttk.Entry(url_frame)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        
        self.fetch_button = tk.Button(
            url_frame, 
            text="Search", 
            command=self.fetch_video_info,
            bg="#4285F4",  # Google Blue
            fg="white",
            activebackground="#5a95f5",
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3
        )
        self.fetch_button.pack(side=tk.RIGHT, padx=(0, 5))
        
        # Tooltip for URL entry
        create_tooltip(self.url_entry, "Enter a YouTube video URL (youtube.com or youtu.be)")
        
        # Add binding to fetch on Enter key
        self.url_entry.bind("<Return>", lambda event: self.fetch_video_info())
    
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
        ttk.Label(filename_frame, text="Output Filename:").pack(anchor=tk.W)
        
        # Create filename entry and reset button in a horizontal layout
        filename_entry_frame = ttk.Frame(filename_frame)
        filename_entry_frame.pack(fill=tk.X, pady=(2, 0))
        
        self.filename_entry = ttk.Entry(filename_entry_frame)
        self.filename_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Create reset filename button
        self.reset_filename_button = tk.Button(
            filename_entry_frame,
            text="Reset",
            command=self.reset_filename,
            bg="#4285F4",  # Google Blue
            fg="white",
            activebackground="#5a95f5",
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3,
            width=10  # Fixed width
        )
        self.reset_filename_button.pack(side=tk.RIGHT, padx=(5, 0))
        self.reset_filename_button.config(state=tk.DISABLED)  # Initially disabled
        
        # Create video info field with additional details
        self.video_info_frame = ttk.Frame(filename_frame)
        self.video_info_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.info_label = ttk.Label(self.video_info_frame, text="")
        self.info_label.pack(anchor=tk.W, fill=tk.X)
        
        self.channel_label = ttk.Label(self.video_info_frame, text="")
        self.channel_label.pack(anchor=tk.W, fill=tk.X)
    
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
    
    def _create_quality_section(self):
        """Create the quality selection section of the UI."""
        # Create a labeled frame to contain the quality options
        quality_frame = ttk.LabelFrame(self.main_frame, text="Quality Options", padding="5")
        quality_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create a Treeview widget for displaying format options
        self.format_list = ttk.Treeview(
            quality_frame,
            columns=("resolution", "ext", "filesize"),  # Removed "note" column
            show="headings",  # Show only the headings, not the first column
            height=6  # Show 6 rows at a time
        )
        
        # Configure the column headings with descriptive text
        self.format_list.heading("resolution", text="Resolution")  # Column for video resolution (e.g., 1080p)
        self.format_list.heading("ext", text="Format")             # Column for file format (MP4/WebM)
        self.format_list.heading("filesize", text="File Size")     # Column for file size (e.g., 1645MB)
        
        # Configure each column's properties
        self.format_list.column("resolution", width=150, anchor=tk.CENTER, stretch=True)
        self.format_list.column("ext", width=100, anchor=tk.CENTER, stretch=True)
        self.format_list.column("filesize", width=150, anchor=tk.CENTER, stretch=True)
        
        # Create a vertical scrollbar for the format list
        quality_scrollbar = ttk.Scrollbar(
            quality_frame, 
            orient=tk.VERTICAL,  # Vertical scrollbar
            command=self.format_list.yview  # Link scrollbar to format list's vertical view
        )
        
        # Configure the format list to use the scrollbar
        self.format_list.configure(yscrollcommand=quality_scrollbar.set)
        
        # Pack the widgets into the frame
        self.format_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        quality_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind the selection event to update the UI when a format is selected
        self.format_list.bind("<<TreeviewSelect>>", self.on_format_select)
        
        # Add a placeholder message when no formats are available
        self.format_list.insert("", tk.END, values=("No formats available", "", ""))
    
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
    
    def _create_control_section(self):
        """Create the control section with download and cancel buttons."""
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # Create a frame for buttons on the left
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Download button (using regular tk.Button for better styling)
        self.download_button = tk.Button(
            button_frame,
            text="Download",
            command=self.download_video,
            bg="#ff0000",
            fg="white",
            activebackground="#ff3333",
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3
        )
        self.download_button.pack(side=tk.LEFT, padx=5)
        create_tooltip(self.download_button, "Start downloading the video")

        # Speed boost button (using regular tk.Button)
        self.speed_boost_button = tk.Button(
            button_frame,
            text="⚡ Speed Boost",
            command=self.toggle_speed_boost,
            bg="#00ff00",  # Bright green color
            fg="black",
            activebackground="#00cc00",  # Darker green for active state
            activeforeground="black",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3
        )
        self.speed_boost_button.pack(side=tk.LEFT, padx=5)
        create_tooltip(self.speed_boost_button, "Toggle speed boost mode for faster downloads")

        # Dark mode toggle button (using regular tk.Button)
        self.dark_mode_button = tk.Button(
            button_frame,
            text="🌙 Dark Mode",
            command=self.toggle_dark_mode,
            bg="#0078d7",
            fg="white",
            activebackground="#1e90ff",
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3
        )
        self.dark_mode_button.pack(side=tk.LEFT, padx=5)
        create_tooltip(self.dark_mode_button, "Toggle dark mode theme")

        # Cancel button (using regular tk.Button)
        self.cancel_button = tk.Button(
            button_frame,
            text="Cancel",
            command=self.cancel_download,
            bg="#555555",
            fg="white",
            activebackground="#777777",
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3,
            state=tk.DISABLED
        )
        self.cancel_button.pack(side=tk.LEFT, padx=5)
        create_tooltip(self.cancel_button, "Cancel the current download")

        # Create a frame for GitHub links on the right
        github_frame = ttk.Frame(control_frame)
        github_frame.pack(side=tk.RIGHT, padx=5)

        # Create GitHub link label
        github_link = tk.Label(
            github_frame,
            text="DevCraftXCoder",
            fg="#0066cc",  # Blue color for link
            cursor="hand2",  # Hand cursor on hover
            font=("", 9, "underline"),
            bg=self.root.cget("bg")  # Match the root window's background
        )
        github_link.pack(side=tk.TOP, pady=(0, 2))  # Add small padding at bottom
        github_link.bind("<Button-1>", lambda e: self.open_github())
        github_link.bind("<Enter>", lambda e: github_link.config(fg="#003366"))  # Darker blue on hover
        github_link.bind("<Leave>", lambda e: github_link.config(fg="#0066cc"))  # Original blue on leave
        create_tooltip(github_link, "Visit DevCraftXCoder on GitHub")

        # Create JDM8102 link label (smaller size)
        jdm_link = tk.Label(
            github_frame,
            text="JDM8102",
            fg="#0066cc",  # Blue color for link
            cursor="hand2",  # Hand cursor on hover
            font=("", 7, "underline"),  # Smaller font size
            bg=self.root.cget("bg")  # Match the root window's background
        )
        jdm_link.pack(side=tk.TOP)  # Place directly under DevCraftXCoder
        jdm_link.bind("<Button-1>", lambda e: self.open_jdm_github())
        jdm_link.bind("<Enter>", lambda e: jdm_link.config(fg="#003366"))  # Darker blue on hover
        jdm_link.bind("<Leave>", lambda e: jdm_link.config(fg="#0066cc"))  # Original blue on leave
        create_tooltip(jdm_link, "Visit JDM8102 on GitHub")

        # Store references to the labels for theme updates
        self.github_link = github_link
        self.jdm_link = jdm_link

        # Initialize speed boost state
        self.speed_boost_active = False
    
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
        
        # Clear current format list
        for item in self.format_list.get_children():
            self.format_list.delete(item)
        
        # Insert loading message
        self.format_list.insert("", tk.END, values=("Loading...", "", ""))
        
        def fetch_thread():
            try:
                # Get available formats and video info
                formats, info = self.downloader.get_available_formats(url)
                
                # Store video info
                self.video_info = info
                self.available_formats = formats
                
                # Update UI with video info
                self.root.after(0, lambda: self._update_video_info(info))
                
                # Update format list
                self.root.after(0, lambda: self.update_format_list(formats))
                
                # Update status
                self.root.after(0, lambda: self.status_label.config(
                    text="Ready to download. Select quality and click Download."
                ))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"Failed to fetch video information: {str(e)}"
                ))
                
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Error: {str(e)[:50]}..."
                ))
                
                # Clear format list and show error
                self.root.after(0, lambda: self._clear_format_list())
                self.root.after(0, lambda: self.format_list.insert(
                    "", tk.END, 
                    values=("Error", "", str(e)[:50])
                ))
            
            finally:
                # Re-enable buttons
                self.root.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
        
        # Start fetch in a separate thread
        threading.Thread(target=fetch_thread, daemon=True).start()

    def _update_video_info(self, info):
        """Update the UI with video information."""
        if not info:
            return
            
        # Update thumbnail
        if 'thumbnail' in info:
            self.load_thumbnail(info['thumbnail'])
        
        # Update filename entry
        if 'title' in info:
            self.filename_entry.delete(0, tk.END)
            self.filename_entry.insert(0, info['title'])
            self.reset_filename_button.config(state=tk.NORMAL)
        
        # Update info labels
        duration = info.get('duration', 0)
        view_count = info.get('view_count', 0)
        channel = info.get('channel', 'Unknown')
        
        # Format duration and view count
        duration_str = format_duration(duration)
        view_count_str = f"{view_count:,}" if view_count else "Unknown"
        
        # Update info labels
        self.info_label.config(
            text=f"Duration: {duration_str} | Views: {view_count_str}"
        )
        
        self.channel_label.config(
            text=f"Channel: {channel}"
        )
    
    def load_thumbnail(self, url):
        """Load thumbnail image with error handling and timeout."""
        def fetch_thumbnail():
            try:
                # Check cache first
                if url in thumbnail_cache:
                    self.thumbnail_image = thumbnail_cache[url]
                    self.root.after(0, self._set_thumbnail_image)
                    return
                
                # Attempt to download the thumbnail with timeout
                response = requests.get(url, timeout=5)
                
                # Verify that response is an image
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    raise ValueError(f"Invalid content type: {content_type}")
                
                # Process the image
                img_data = BytesIO(response.content)
                img = Image.open(img_data)
                
                # Resize image to fit the window (max 320x180)
                img.thumbnail((320, 180), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage
                self.thumbnail_image = ImageTk.PhotoImage(img)
                
                # Cache the thumbnail
                thumbnail_cache[url] = self.thumbnail_image
                
                # Update the label in the main thread
                self.root.after(0, self._set_thumbnail_image)
                
            except requests.Timeout:
                # Handle timeout error
                self.root.after(0, lambda: self.thumbnail_label.config(
                    text="Thumbnail load timed out",
                    image=""
                ))
                
            except (requests.RequestException, IOError, ValueError) as e:
                # Handle network or image errors
                logging.error(f"Error loading thumbnail: {e}")
                self.root.after(0, lambda: self.thumbnail_label.config(
                    text="Error loading thumbnail",
                    image=""
                ))
        
        # Start thumbnail loading in a separate thread
        if self.thumbnail_load_thread and self.thumbnail_load_thread.is_alive():
            # If a thread is already running, do nothing
            return
            
        self.thumbnail_label.config(text="Loading thumbnail...")
        self.thumbnail_load_thread = threading.Thread(target=fetch_thumbnail, daemon=True)
        self.thumbnail_load_thread.start()
    
    def _set_thumbnail_image(self):
        """Set the thumbnail image to the label."""
        if self.thumbnail_image:
            self.thumbnail_label.config(image=self.thumbnail_image, text="")
    
    def update_format_list(self, formats=None):
        """Update the format selection list with available options."""
        # Use provided formats or current available formats
        formats = formats or self.available_formats
        
        # Clear current items
        self._clear_format_list()
        
        # Handle case with no formats
        if not formats:
            self.format_list.insert("", tk.END, values=("No formats available", "", ""))
            return
        
        # Get selected format type (mp3 or mp4)
        format_type = self.format_var.get()
        
        if format_type == "mp3":
            # For MP3, only show audio options
            for fmt in formats:
                if fmt.get('is_audio', False):
                    self.format_list.insert("", tk.END, 
                                          values=(
                                              fmt['resolution'],                # Resolution
                                              fmt['ext'],                       # Format
                                              format_filesize(fmt['filesize'])  # File Size
                                          ),
                                          tags=('audio',))
        else:
            # For video, show all video options
            for fmt in formats:
                # Skip audio formats
                if fmt.get('is_audio', True):
                    continue
                    
                # Get format details
                quality = fmt.get('quality_name', 'Unknown')
                ext = fmt.get('ext', 'mp4')
                size = format_filesize(fmt['filesize']) if fmt.get('filesize') else "Unknown"
                
                # Insert into treeview
                self.format_list.insert("", tk.END, values=(quality, ext, size))
        
        # Select the first item by default
        if self.format_list.get_children():
            self.format_list.selection_set(self.format_list.get_children()[0])
    
    def _clear_format_list(self):
        """Clear all items from the format list."""
        for item in self.format_list.get_children():
            self.format_list.delete(item)
    
    def format_changed(self):
        """Handle change of format type (MP3/MP4)."""
        # Update the format list with the new selection
        self.update_format_list()
    
    def on_format_select(self, _):
        """Handle selection of a format from the list."""
        # No specific action needed when selecting a format
        pass
    
    def download_video(self):
        """Start the video download process."""
        if not self.video_info:
            messagebox.showerror("Error", "Please fetch video information first!")
            return

        # Get selected format
        selected_format = self.get_selected_format()
        if not selected_format:
            messagebox.showerror("Error", "Please select a format to download!")
            return

        # Get the download directory
        download_dir = self.dir_entry.get().strip()
        if not validate_directory(download_dir):
            messagebox.showerror("Error", "Invalid download directory!")
            return

        # Get custom filename if set
        custom_filename = self.filename_entry.get().strip()
        if custom_filename and custom_filename != self.video_info.get('title', ''):
            self.custom_filename = custom_filename

        # Reset progress display
        self.progress['value'] = 0
        self.status_label.config(text="Starting download...")
        self.speed_label.config(text="")
        self.eta_label.config(text="")
        
        # Disable buttons during download
        self.download_button.config(state=tk.DISABLED)
        self.fetch_button.config(state=tk.DISABLED)
        self.speed_boost_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.download_in_progress = True

        def download_thread():
            try:
                url = self.video_info.get('webpage_url')
                if not url:
                    raise ValueError("No valid URL found")
                
                self.downloader.download_video(
                    url=url,
                    download_dir=download_dir,
                    selected_format=selected_format,
                    complete_callback=self._on_download_complete,
                    error_callback=self._on_download_error
                )

            except Exception as e:
                logging.error(f"Download thread error: {str(e)}")
                self.root.after(0, lambda: self._on_download_error(str(e)))

        # Start download in a separate thread
        threading.Thread(target=download_thread, daemon=True).start()

    def _on_download_complete(self, video_title):
        """Handle successful download completion."""
        self.progress.configure(value=100)
        self.status_label.config(text=f"Download completed: {video_title}")
        messagebox.showinfo("Success", f"'{video_title}' has been downloaded successfully!")
        self._reset_ui_state()

    def _on_download_error(self, error_message):
        """Handle download error."""
        self.progress.configure(value=0)
        self.status_label.config(text=f"Error: {error_message[:50]}...")
        messagebox.showerror("Download Failed", f"Download error: {error_message}")
        self._reset_ui_state()

    def _reset_ui_state(self):
        """Reset UI elements to their default state."""
        self.download_button.config(state=tk.NORMAL)
        self.fetch_button.config(state=tk.NORMAL)
        self.speed_boost_button.config(state=tk.NORMAL)
        self.cancel_button.config(state=tk.DISABLED)
        self.download_in_progress = False
    
    def cancel_download(self):
        """Cancel the current download."""
        if not self.download_in_progress:
            return
            
        # Ask for confirmation
        if messagebox.askyesno("Cancel Download", "Are you sure you want to cancel the download?"):
            # Request download cancellation
            if self.downloader.cancel_download():
                self.status_label.config(text="Cancelling download...")
            else:
                self.status_label.config(text="No active download to cancel")
                self.cancel_button.config(state=tk.DISABLED)
    
    def toggle_dark_mode(self):
        """Toggle between light and dark mode for the UI."""
        if not self.dark_mode:
            # Switch to dark mode
            bg_color = "#2E2E2E"
            fg_color = "#FFFFFF"  # Pure white for better visibility
            entry_bg = "#3E3E3E"
            entry_fg = "#FFFFFF"  # White text for entries
            
            # Update ttk styles
            self.style.configure("TLabel", background=bg_color, foreground=fg_color)
            self.style.configure("TButton", background=entry_bg, foreground=fg_color)
            self.style.configure("TFrame", background=bg_color)
            self.style.configure("TLabelframe", background=bg_color)
            self.style.configure("TLabelframe.Label", background=bg_color, foreground=fg_color)
            self.style.configure("Treeview", background=entry_bg, foreground=fg_color, fieldbackground=entry_bg)
            self.style.configure("Treeview.Heading", background="#1E1E1E", foreground=fg_color)
            
            # Update tk buttons
            self.download_button.config(bg="#ff3333", fg="white", activebackground="#ff6666", activeforeground="white")
            self.speed_boost_button.config(bg="#ffd700", fg="black", activebackground="#ffed4a", activeforeground="black")
            self.dark_mode_button.config(bg="#1e90ff", fg="white", activebackground="#00bfff", activeforeground="white", text="☀️ Light Mode")
            self.cancel_button.config(bg="#777777", fg="white", activebackground="#999999", activeforeground="white")
            
            # Configure entry style
            self.style.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg)
            
            # Configure progress bar
            self.style.configure("Horizontal.TProgressbar", background="#4CAF50")
            
        else:
            # Switch to light mode
            bg_color = "#f0f0f0"
            fg_color = "#000000"  # Pure black for better visibility
            entry_bg = "#FFFFFF"  # White background for entries
            entry_fg = "#000000"  # Black text for entries
            
            # Reset to default styles
            self.style.theme_use(self.style.theme_names()[0] if 'clam' not in self.style.theme_names() else 'clam')
            
            # Update ttk styles
            self.style.configure("TLabel", background=bg_color, foreground=fg_color)
            self.style.configure("TButton", background=bg_color, foreground=fg_color)
            self.style.configure("TFrame", background=bg_color)
            self.style.configure("TLabelframe", background=bg_color)
            self.style.configure("TLabelframe.Label", background=bg_color, foreground=fg_color)
            self.style.configure("Treeview", background=entry_bg, foreground=fg_color, fieldbackground=entry_bg)
            self.style.configure("Treeview.Heading", background=bg_color, foreground=fg_color)
            
            # Update tk buttons
            self.download_button.config(bg="#ff0000", fg="white", activebackground="#ff3333", activeforeground="white")
            self.speed_boost_button.config(bg="#ffd700", fg="black", activebackground="#ffed4a", activeforeground="black")
            self.dark_mode_button.config(bg="#0078d7", fg="white", activebackground="#1e90ff", activeforeground="white", text="🌙 Dark Mode")
            self.cancel_button.config(bg="#555555", fg="white", activebackground="#777777", activeforeground="white")
            
            # Configure entry style
            self.style.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg)
        
        # Toggle the dark mode flag
        self.dark_mode = not self.dark_mode
        
        # Apply background color to main window and frames
        self.root.configure(background=bg_color)
        self.main_frame.configure(style="Main.TFrame")
        
        # Update all frames and their children
        for widget in self.main_frame.winfo_children():
            if isinstance(widget, ttk.Frame):
                widget.configure(style="Main.TFrame")
                # Update all child widgets
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Label):
                        child.configure(foreground=fg_color)
                    elif isinstance(child, ttk.Entry):
                        child.configure(foreground=entry_fg)
                    elif isinstance(child, ttk.Treeview):
                        child.configure(foreground=fg_color)
    
    def reset_filename(self):
        """Reset the filename to the original video title."""
        if self.video_info and 'title' in self.video_info:
            self.filename_entry.delete(0, tk.END)
            self.filename_entry.insert(0, self.video_info['title'])
            self.custom_filename = None
    
    def on_closing(self):
        """Handle window closing event."""
        # Cancel any active downloads
        if self.download_in_progress:
            if messagebox.askyesno("Quit", "A download is in progress. Cancel and quit?"):
                self.downloader.cancel_download()
            else:
                return  # Don't close if user says no
        
        # Clean up resources
        self._cleanup_resources()
        
        # Destroy the window and exit
        self.root.destroy()
        sys.exit(0)
    
    def _cleanup_resources(self):
        """Clean up resources before closing."""
        # Cancel any ongoing downloads
        if self.downloader:
            self.downloader.cancel_download()
        
        # Clear cached images to prevent memory leaks
        global thumbnail_cache
        thumbnail_cache.clear()
        
        # Remove references to large objects
        self.thumbnail_image = None
        self.video_info = None
        self.available_formats = []

    def toggle_speed_boost(self):
        """Toggle speed boost mode for faster downloads."""
        self.speed_boost_active = not self.speed_boost_active
        
        # Create a custom popup window
        popup = tk.Toplevel(self.root)
        popup.title("Speed Boost Status")
        popup.geometry("300x200")
        popup.resizable(False, False)
        
        # Center the popup window
        popup.update_idletasks()
        width = popup.winfo_width()
        height = popup.winfo_height()
        x = (popup.winfo_screenwidth() // 2) - (width // 2)
        y = (popup.winfo_screenheight() // 2) - (height // 2)
        popup.geometry(f'{width}x{height}+{x}+{y}')
        
        # Make the popup window modal
        popup.transient(self.root)
        popup.grab_set()
        
        # Configure popup style
        popup.configure(bg="#2E2E2E" if self.dark_mode else "#f0f0f0")
        
        # Create and configure the message frame
        message_frame = ttk.Frame(popup, padding="20")
        message_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create and configure the icon label
        icon_label = ttk.Label(
            message_frame,
            text="⚡" if self.speed_boost_active else "🚀",
            font=("", 40)
        )
        icon_label.pack(pady=(0, 10))
        
        # Create and configure the status label
        status_label = ttk.Label(
            message_frame,
            text="SPEED BOOST ACTIVATED!" if self.speed_boost_active else "Speed Boost Deactivated",
            font=("", 12, "bold"),
            foreground="#00ff00" if self.speed_boost_active else "#ff0000"
        )
        status_label.pack(pady=(0, 5))
        
        # Create and configure the message label
        message_text = (
            "🚀 Download Speed: MAXIMUM\n"
            "⚡ Buffer Size: OPTIMIZED"
        ) if self.speed_boost_active else (
            "Returning to normal download settings.\n"
            "Speed boost features disabled."
        )
        
        message_label = ttk.Label(
            message_frame,
            text=message_text,
            justify=tk.CENTER,
            font=("", 10)
        )
        message_label.pack(pady=(0, 10))
        
        # Create and configure the close button
        close_button = tk.Button(
            message_frame,
            text="Close",
            command=popup.destroy,
            bg="#00ff00" if self.speed_boost_active else "#ff0000",
            fg="black",
            activebackground="#00cc00" if self.speed_boost_active else "#cc0000",
            activeforeground="black",
            padx=20,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3
        )
        close_button.pack(pady=(10, 0))
        
        # Update the speed boost button appearance
        if self.speed_boost_active:
            self.speed_boost_button.configure(
                text="⚡ Speed Boost ON",
                bg="#00ff00",
                activebackground="#00cc00"
            )
        else:
            self.speed_boost_button.configure(
                text="⚡ Speed Boost",
                bg="#00ff00",
                activebackground="#00cc00"
            )
        
        # Auto-close the popup after 3 seconds
        popup.after(3000, popup.destroy)

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
            return "bestvideo+bestaudio/best"
            
        # Get the selected item's values
        selected_item = selected_items[0]
        values = self.format_list.item(selected_item, 'values')
        
        if not values:
            return "bestvideo+bestaudio/best"
            
        # Get resolution/quality from the values
        resolution = values[0]
        
        # Find the corresponding format
        for fmt in self.available_formats:
            if fmt.get('quality_name') == resolution or fmt.get('resolution') == resolution:
                # Return the exact format ID with best audio
                return f"{fmt['id']}+bestaudio/best"
        
        # If we couldn't find a specific ID, use the resolution with best audio
        return f"bestvideo[height={resolution.rstrip('p')}]+bestaudio/best[height={resolution.rstrip('p')}]"

    def update_progress(self, progress_info):
        """Update the progress display with download progress information."""
        try:
            # Update progress bar
            percent = progress_info.get('percent', 0)
            self.progress['value'] = percent
            
            # Update status text based on status type
            status = progress_info.get('status', '')
            filename = progress_info.get('filename', '')
            
            if status == 'downloading':
                # Format the status text with percentage
                status_text = f"Downloading: {percent}% - {filename}"
                # Update speed and ETA
                speed = progress_info.get('speed')
                if speed:
                    self.speed_label.config(text=f"Speed: {speed}")
                else:
                    self.speed_label.config(text="")
                    
                eta = progress_info.get('eta')
                if eta:
                    self.eta_label.config(text=f"ETA: {eta}")
                else:
                    self.eta_label.config(text="")
            elif status == 'converting':
                status_text = f"Converting {filename}..."
                self.speed_label.config(text="")
                self.eta_label.config(text="")
            elif status == 'complete':
                status_text = f"Download completed: {filename}"
                self.speed_label.config(text="")
                self.eta_label.config(text="")
                self.progress['value'] = 100  # Ensure progress bar is full
            elif status == 'cancelled':
                status_text = "Download cancelled"
                self.speed_label.config(text="")
                self.eta_label.config(text="")
                self.progress['value'] = 0
            elif status == 'error':
                error = progress_info.get('error', 'Unknown error')
                status_text = f"Error: {error[:50]}..." if len(error) > 50 else f"Error: {error}"
                self.speed_label.config(text="")
                self.eta_label.config(text="")
                self.progress['value'] = 0
            else:
                status_text = f"Downloading: {percent}%"
                self.speed_label.config(text="")
                self.eta_label.config(text="")
            
            # Update status label
            self.status_label.config(text=status_text)
            
            # Force UI update
            self.root.update_idletasks()
            
            # Update button states based on progress
            if status == 'complete' or status == 'cancelled' or status == 'error':
                self.download_in_progress = False
                self.cancel_button.config(state=tk.DISABLED)
                self.download_button.config(state=tk.NORMAL)
                self.fetch_button.config(state=tk.NORMAL)
                
        except Exception as e:
            logging.error(f"Error updating progress: {e}")

    def open_github(self):
        """Open the GitHub profile in the default browser."""
        import webbrowser
        webbrowser.open("https://github.com/DevCraftXCoder")

    def open_jdm_github(self):
        """Open JDM8102's GitHub profile in the default browser."""
        import webbrowser
        webbrowser.open("https://github.com/JDM8102")

def main():
    """Main entry point for the application."""
    try:
        # Set up signal handling for clean shutdown
        def signal_handler(sig, frame):
            logging.info("Received interrupt signal, shutting down...")
            sys.exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)
        
        # Create and start the GUI
        root = tk.Tk()
        app = DownloadManagerApp(root)
        
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
    
    finally:
        # Final cleanup
        for thread in active_downloads:
            if thread and thread.is_alive():
                try:
                    thread.join(0.1)  # Give threads a chance to exit
                except:
                    pass

if __name__ == "__main__":
    main()

#Coded by DevCraftXCoder & JDM8102