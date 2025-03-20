#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
YouTube Video Downloader
An application that lets users download YouTube videos with quality selection options.

Features:
- Download videos in MP4/WebM format with selectable quality
- Download audio in MP3 format
- Progress tracking with visual feedback
- Dark mode support
- Cross-platform compatibility
- Thumbnail preview
- Custom filename support
- Download cancellation
- Improved format detection
- Proper resource management
- Enhanced error handling
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
import time
import sys
import signal

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
    
    def progress_hook(self, d):
        """Process download progress updates from yt-dlp.
        
        This method is called by yt-dlp during the download process to report
        progress, speed, and estimated time remaining.
        """
        if not self.downloading or self.cancel_requested:
            # If cancellation was requested, signal to stop the download
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
        self.cancel_requested = False
        video_title = "Unknown"
        
        try:
            # Default filename template if not provided
            if not filename_template:
                filename_template = os.path.join(download_dir, '%(title)s.%(ext)s')
            else:
                # If custom filename provided, sanitize it first
                filename_template = sanitize_filename(filename_template)
                # Use it with appropriate extension
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
                # Optimize download speed
                'buffersize': 1024 * 16,  # Increase buffer size
                'concurrent_fragment_downloads': 3,  # Download fragments in parallel
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
            elif selected_format.isdigit() or selected_format in ['mp4', 'webm', 'mov']:
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
                try:
                    height = int(selected_format.rstrip('p'))
                    ydl_opts.update({
                        'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                        'merge_output_format': 'mp4',
                        'prefer_ffmpeg': True,
                    })
                except ValueError:
                    # If we can't parse the format as a resolution, use it directly
                    ydl_opts.update({
                        'format': selected_format,
                        'merge_output_format': 'mp4',
                        'prefer_ffmpeg': True,
                    })
            
            # Perform the download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Store reference for potential cancellation
                self.ydl_instance = ydl
                
                # Extract info first to get title
                info = self.current_info or ydl.extract_info(url, download=False)
                video_title = info.get('title', 'Unknown title')
                
                # Log the start of download
                logging.info(f"Starting download: {video_title}")
                
                # Check if download was cancelled before starting
                if self.cancel_requested:
                    raise DownloadCancelledError("Download cancelled by user")
                
                # Perform the actual download
                ydl.download([url])
                
                # If we got here without cancellation, download completed successfully
                logging.info(f"Download completed: {video_title}")
                
                # Clean up temporary files
                self._cleanup_temp_files(download_dir)
                
                # Set progress to 100%
                if self.progress_callback:
                    self.progress_callback({
                        'percent': 100,
                        'status': 'complete',
                        'filename': video_title
                    })
                
                return video_title, True
                
        except DownloadCancelledError as e:
            # Handle cancellation specifically
            logging.info(f"Download cancelled: {e}")
            
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': 'cancelled',
                    'filename': video_title
                })
            
            # Clean up any partial downloads
            self._cleanup_temp_files(download_dir)
            
            return video_title, False
            
        except yt_dlp.utils.DownloadError as e:
            # Handle yt-dlp specific download errors
            logging.error(f"Download error: {e}")
            
            # Update progress with error
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': 'error',
                    'error': str(e),
                    'filename': video_title
                })
            
            # Return failure
            return video_title, False
        
        except (IOError, OSError) as e:
            # Handle file system errors
            logging.error(f"File system error: {e}")
            
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': 'error',
                    'error': f"File error: {str(e)}",
                    'filename': video_title
                })
            
            # Return failure
            return video_title, False
            
        except Exception as e:
            # Handle other unexpected errors
            logging.error(f"Unexpected error: {e}")
            
            if self.progress_callback:
                self.progress_callback({
                    'percent': 0,
                    'status': 'error',
                    'error': str(e),
                    'filename': video_title
                })
            
            # Return failure
            return video_title, False
        
        finally:
            # Reset state flags
            self.downloading = False
            self.cancel_requested = False
            self.ydl_instance = None
    
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
    
    def __init__(self, root):
        """Initialize the application GUI."""
        # Set the window title and main reference
        self.root = root
        self.root.title("YouTube Video Downloader")
        
        # Set window size to be just bigger than default
        window_width = 850
        window_height = 800
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        # Calculate position to center the window
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        # Set the window size and position
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Set minimum window size to prevent too small windows
        self.root.minsize(750, 700)
        
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
        self.reset_filename_button = ttk.Button(
            filename_entry_frame,
            text="Reset",
            command=self.reset_filename,
            style="Accent.TButton",
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
            text="Video", 
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
            columns=("resolution", "ext", "filesize", "note"),  # Define columns
            show="headings",  # Show only the headings, not the first column
            height=6  # Show 6 rows at a time
        )
        
        # Configure the column headings with descriptive text
        self.format_list.heading("resolution", text="Resolution")  # Column for video resolution (e.g., 1080p)
        self.format_list.heading("ext", text="Format")             # Column for file format (MP4/WebM)
        self.format_list.heading("filesize", text="File Size")     # Column for file size (e.g., 1645MB)
        self.format_list.heading("note", text="Codec/Notes")       # Column for additional info
        
        # Configure each column's properties
        self.format_list.column("resolution", width=150, anchor=tk.CENTER, stretch=True)
        self.format_list.column("ext", width=100, anchor=tk.CENTER, stretch=True)
        self.format_list.column("filesize", width=150, anchor=tk.CENTER, stretch=True)
        self.format_list.column("note", width=200, stretch=True)
        
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
        self.format_list.insert("", tk.END, values=("No formats available", "", "", "Fetch video info first"))
    
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
        """Create the control buttons section of the UI."""
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Left side buttons: Download and Cancel
        left_buttons_frame = ttk.Frame(control_frame)
        left_buttons_frame.pack(side=tk.LEFT)
        
        # Download button (using regular tk.Button instead of ttk for better styling control)
        self.download_button = tk.Button(
            left_buttons_frame, 
            text="Download", 
            command=self.download_video,
            bg="#ff0000",  # Red color (YouTube)
            fg="white",
            activebackground="#ff3333",  # Lighter red on hover
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3  # Thicker border
        )
        self.download_button.pack(side=tk.LEFT, padx=(5, 5))
        
        # Cancel button (initially disabled)
        self.cancel_button = tk.Button(
            left_buttons_frame,
            text="Cancel",
            command=self.cancel_download,
            bg="#555555",  # Gray color
            fg="white",
            activebackground="#777777",  # Lighter gray on hover
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3,
            state=tk.DISABLED  # Initially disabled
        )
        self.cancel_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # Right side buttons: Dark mode toggle
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
        self.format_list.insert("", tk.END, values=("Loading...", "", "", ""))
        
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
                    values=("Error", "", "", str(e)[:50])
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
            self.format_list.insert("", tk.END, values=("No formats available", "", "", ""))
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
                                              format_filesize(fmt['filesize']), # File Size
                                              fmt['format_note']                # Notes
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
                
                # Get codec info for notes
                vcodec = fmt.get('vcodec', 'unknown')
                acodec = fmt.get('acodec', 'unknown')
                format_note = fmt.get('format_note', '')
                
                # Create note text
                if format_note:
                    note = format_note
                else:
                    note = f"Video: {vcodec}, Audio: {acodec}"
                
                # Insert into treeview
                self.format_list.insert("", tk.END, values=(quality, ext, size, note))
        
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
    
    def update_progress(self, progress_info):
        """Update the progress display with download progress information."""
        # Update progress bar
        percent = progress_info.get('percent', 0)
        self.progress['value'] = percent
        
        # Update status text based on status type
        status = progress_info.get('status', '')
        filename = progress_info.get('filename', '')
        
        if status == 'downloading':
            status_text = f"Downloading: {percent}% of {filename}"
        elif status == 'converting':
            status_text = f"Converting {filename}..."
        elif status == 'complete':
            status_text = f"Download completed: {filename}"
        elif status == 'cancelled':
            status_text = "Download cancelled"
        elif status == 'error':
            error = progress_info.get('error', 'Unknown error')
            status_text = f"Error: {error[:50]}..." if len(error) > 50 else f"Error: {error}"
        else:
            status_text = f"Downloading: {percent}%"
        
        self.status_label.config(text=status_text)
        
        # Update speed and ETA if available
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
            
        # Force UI update
        self.root.update_idletasks()
        
        # Update button states based on progress
        if status == 'complete' or status == 'cancelled' or status == 'error':
            self.download_in_progress = False
            self.cancel_button.config(state=tk.DISABLED)
            self.download_button.config(state=tk.NORMAL)
            self.fetch_button.config(state=tk.NORMAL)
    
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
            
        # If we don't have video info yet, fetch it first
        if not self.video_info:
            self.fetch_video_info()
            # We'll need to wait for the fetch to complete before downloading
            messagebox.showinfo("Info", "Please wait for video information to load, then try downloading again.")
            return
        
        # Get selected format
        selected_format = self.get_selected_format()
        
        # Get custom filename if set
        custom_filename = self.filename_entry.get().strip()
        if custom_filename and custom_filename != self.video_info.get('title', ''):
            self.custom_filename = custom_filename
        else:
            self.custom_filename = None
        
        # Reset progress display
        self.progress['value'] = 0
        self.status_label.config(text="Starting download...")
        self.speed_label.config(text="")
        self.eta_label.config(text="")
        
        # Disable/enable relevant buttons
        self.download_button.config(state=tk.DISABLED)
        self.fetch_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        
        # Set download in progress flag
        self.download_in_progress = True
        
        # Define the thread function for the download
        def download_thread_func():
            try:
                # Start the download
                video_title, success = self.downloader.download_video(
                    url, download_dir, selected_format, self.custom_filename
                )
                
                # Update UI based on success or failure
                if success:
                    self.root.after(0, lambda: self.status_label.config(text=f"Download completed: {video_title}"))
                    
                    # Only show a popup for successful downloads
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Success", 
                        f"'{video_title}' has been downloaded successfully."
                    ))
                
            except Exception as e:
                # Handle unexpected errors
                error_msg = str(e)
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Error: {error_msg[:50]}..."
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"An unexpected error occurred: {error_msg}"
                ))
            
            finally:
                # Reset download state and re-enable buttons
                self.download_in_progress = False
                self.active_download_thread = None
                self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.cancel_button.config(state=tk.DISABLED))
        
        # Start download thread
        self.active_download_thread = threading.Thread(target=download_thread_func, daemon=True)
        self.active_download_thread.start()
        
        # Add to active downloads list
        active_downloads.append(self.active_download_thread)
    
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
            self.cancel_button.config(bg="#777777", fg="white", activebackground="#999999", activeforeground="white")
            self.dark_mode_button.config(bg="#1e90ff", fg="white", activebackground="#00bfff", activeforeground="white", text="Toggle Light Mode")
            
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
            self.cancel_button.config(bg="#555555", fg="white", activebackground="#777777", activeforeground="white")
            self.dark_mode_button.config(bg="#0078d7", fg="white", activebackground="#1e90ff", activeforeground="white", text="Toggle Dark Mode")
        
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
