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

# Import required libraries for GUI and functionality
import tkinter as tk  # Main GUI library
from tkinter import filedialog, messagebox, ttk  # GUI components for file dialogs, message boxes, and themed widgets
import yt_dlp  # Library for downloading YouTube videos
import os  # Operating system interface for file operations
import shutil  # High-level file operations
import logging  # Logging system for tracking application events
import re  # Regular expressions for text processing
import threading  # Threading support for concurrent operations
import unicodedata  # Unicode character handling
import json  # JSON data handling
from functools import partial  # Function partial application
import requests  # HTTP requests library
from PIL import Image, ImageTk  # Image processing and display
from io import BytesIO  # Byte stream handling
import time  # Time-related functions
import sys  # System-specific parameters and functions
import signal  # Signal handling

# Set up logging configuration to track application events and errors
logging.basicConfig(
    level=logging.INFO,  # Set logging level to INFO
    format='%(asctime)s - %(levelname)s - %(message)s',  # Define log message format
    handlers=[
        logging.StreamHandler(),  # Output logs to console
        logging.FileHandler('download_manager.log')  # Save logs to file
    ]
)

# Reduce noise in logs by setting higher log levels for external libraries
for logger_name in ['yt_dlp', 'ffmpeg']:  # Loop through external loggers
    logger = logging.getLogger(logger_name)  # Get logger instance
    logger.setLevel(logging.ERROR)  # Set to ERROR level to reduce noise

# Define default download directory based on user's home directory
DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# Initialize global variables for application state
active_downloads = []  # List to track active download threads
thumbnail_cache = {}   # Dictionary to cache downloaded thumbnails
info_cache = {}        # Dictionary to cache video information

class CustomFormatter(logging.Formatter):
    """Custom formatter to color logs based on their level"""
    
    def format(self, record):
        # Create a clean message without ANSI color codes
        message = super().format(record)  # Get formatted message from parent class
        return message  # Return the clean message

# Utility Functions
def safe_json_dumps(data):
    """Safely serialize data to JSON format, excluding non-serializable types."""
    try:
        # Try to convert data to JSON with indentation
        return json.dumps(data, indent=4)
    except TypeError:
        # Handle non-serializable types by converting them to strings
        clean_data = {}  # Create empty dictionary for cleaned data
        for k, v in data.items():  # Iterate through data items
            try:
                json.dumps({k: v})  # Test if item can be serialized
                clean_data[k] = v  # Keep original value if serializable
            except TypeError:
                clean_data[k] = str(v)  # Convert to string if not serializable
        return json.dumps(clean_data, indent=4)  # Return cleaned JSON

def is_ffmpeg_installed():
    """Check if FFmpeg is installed by verifying if it's in the system path."""
    return shutil.which("ffmpeg") is not None  # Return True if ffmpeg is found in PATH

def validate_directory(directory):
    """Check if the given directory exists and is writable."""
    return os.path.isdir(directory) and os.access(directory, os.W_OK)  # Check directory exists and is writable

def is_valid_youtube_url(url):
    """Validate if a given URL is a valid YouTube link."""
    youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'  # YouTube URL pattern
    return bool(re.match(youtube_regex, url))  # Return True if URL matches pattern

def sanitize_filename(filename):
    """Sanitize a filename by removing invalid characters and normalizing."""
    filename = unicodedata.normalize('NFKD', filename)  # Normalize unicode characters
    filename = filename.replace(' ', '_')  # Replace spaces with underscores
    filename = re.sub(r'[^\w\-_\.]', '', filename)  # Remove invalid characters
    if len(filename) > 200:  # Check filename length
        filename = filename[:197] + "..."  # Truncate long filenames
    return filename  # Return sanitized filename

def format_filesize(bytes_size):
    """Format file size in bytes to human-readable format."""
    if not bytes_size or bytes_size <= 0:  # Check for invalid size
        return "Unknown"  # Return unknown for invalid sizes
        
    units = ['B', 'KB', 'MB', 'GB', 'TB']  # Define size units
    size = float(bytes_size)  # Convert to float for calculations
    unit_index = 0  # Initialize unit index
    
    while size >= 1024.0 and unit_index < len(units) - 1:  # Convert to appropriate unit
        size /= 1024.0  # Divide by 1024 for next unit
        unit_index += 1  # Move to next unit
        
    return f"{size:.2f} {units[unit_index]}"  # Return formatted size with unit

def format_duration(duration_seconds):
    """Format duration in seconds to MM:SS or HH:MM:SS format."""
    if not duration_seconds:  # Check for invalid duration
        return "Unknown"  # Return unknown for invalid durations
        
    minutes, seconds = divmod(int(duration_seconds), 60)  # Convert to minutes and seconds
    hours, minutes = divmod(minutes, 60)  # Convert to hours and minutes
    
    if hours > 0:  # Check if hours are present
        return f"{hours}:{minutes:02d}:{seconds:02d}"  # Return HH:MM:SS format
    else:
        return f"{minutes}:{seconds:02d}"  # Return MM:SS format

def create_tooltip(widget, text):
    """Create a tooltip for a widget."""
    def enter(event):
        # Create tooltip window
        x, y, _, _ = widget.bbox("insert")  # Get widget position
        x += widget.winfo_rootx() + 25  # Calculate tooltip x position
        y += widget.winfo_rooty() + 25  # Calculate tooltip y position
        
        # Create tooltip window
        tooltip = tk.Toplevel(widget)  # Create new window for tooltip
        tooltip.wm_overrideredirect(True)  # Remove window decorations
        tooltip.wm_geometry(f"+{x}+{y}")  # Position tooltip
        
        # Create label with tooltip text
        label = tk.Label(tooltip, text=text, justify=tk.LEFT,
                         background="#ffffff", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))  # Create styled label
        label.pack(ipadx=1)  # Pack label with padding
        
        # Store tooltip reference
        widget.tooltip = tooltip  # Store tooltip window reference
    
    def leave(_):
        # Destroy tooltip if it exists
        if hasattr(widget, "tooltip"):  # Check if tooltip exists
            widget.tooltip.destroy()  # Destroy tooltip window
            del widget.tooltip  # Remove tooltip reference
    
    # Bind mouse events to widget
    widget.bind("<Enter>", enter)  # Bind mouse enter event
    widget.bind("<Leave>", leave)  # Bind mouse leave event

def estimate_filesize(fmt, duration_sec):
    """Estimate file size based on bitrate and duration."""
    if not duration_sec or duration_sec <= 0:  # Check for invalid duration
        return None  # Return None for invalid durations
        
    # Get total bitrate (video + audio)
    tbr = fmt.get('tbr') or fmt.get('abr') or 0  # Get total bitrate
    
    if not tbr:  # If no bitrate found
        # Try to calculate from height-based heuristic
        height = fmt.get('height', 0)  # Get video height
        if not height:  # If no height found
            return None  # Return None if no height
            
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
    return (tbr * duration_sec * 1000) / 8  # Return estimated size in bytes

class DownloadCancelledError(Exception):
    """Custom exception for cancelled downloads."""
    pass

class YoutubeDownloader:
    """Core functionality for downloading YouTube videos with yt-dlp."""
    
    def __init__(self, progress_callback=None, format_callback=None):
        """Initialize the downloader with callbacks for progress updates."""
        self.progress_callback = progress_callback  # Store progress callback function
        self.format_callback = format_callback      # Store format callback function
        self.cancelled = False                     # Initialize cancellation flag
        self.current_download = None               # Store current download reference
        self.downloading = False                   # Initialize downloading flag
        self.ydl_opts = {                          # Configure yt-dlp options
            'format': 'best',                      # Default format selection
            'quiet': True,                         # Suppress output
            'no_warnings': True,                   # Suppress warnings
            'extract_flat': False,                 # Extract full metadata
            'force_generic_extractor': False,      # Use specific extractors
            'postprocessors': [{                   # Configure post-processing
                'key': 'FFmpegVideoConvertor',     # Use FFmpeg for conversion
                'preferedformat': 'mp4',           # Convert to MP4 format
            }],
        }
    
    def progress_hook(self, d):
        """Process download progress updates from yt-dlp."""
        if not self.downloading or self.cancelled:  # Check if download is active or cancelled
            if self.cancelled and d['status'] == 'downloading':  # If cancelled during download
                raise DownloadCancelledError("Download cancelled by user")  # Raise cancellation error
            return  # Exit if not downloading or cancelled
            
        if d['status'] == 'downloading':  # If currently downloading
            # Get download progress information
            total_bytes = d.get('total_bytes')  # Total size of the file
            downloaded_bytes = d.get('downloaded_bytes', 0)  # Bytes downloaded so far
            speed = d.get('speed', 0)  # Current download speed
            
            # Create progress info dictionary
            progress_info = {
                'downloaded_bytes': downloaded_bytes,  # Store downloaded bytes
                'total_bytes': total_bytes,  # Store total bytes
                'speed': speed,  # Store current speed
                'status': 'downloading'  # Set status to downloading
            }
            
            # Calculate download percentage
            if total_bytes and downloaded_bytes:  # If we have both total and downloaded bytes
                progress_info['percent'] = int((downloaded_bytes / total_bytes) * 100)  # Calculate exact percentage
            elif d.get('downloaded_bytes'):  # If we only have downloaded bytes
                progress_info['percent'] = 50  # Show 50% as an estimate
            
            # Update progress through callback
            if self.progress_callback:  # If callback function exists
                self.progress_callback(progress_info)  # Call it with progress info
                
        elif d['status'] == 'finished':  # If download is finished
            # Handle post-processing stage
            if self.progress_callback:  # If callback function exists
                self.progress_callback({
                    'percent': 95,  # Show 95% progress
                    'status': 'converting',  # Set status to converting
                    'filename': d.get('filename', '').split('/')[-1].split('\\')[-1]  # Get filename
                })
        
        elif d['status'] == 'error':  # If an error occurred
            # Handle download errors
            if self.progress_callback:  # If callback function exists
                self.progress_callback({
                    'percent': 0,  # Reset progress to 0
                    'status': 'error',  # Set status to error
                    'error': d.get('error', 'Unknown error'),  # Get error message
                    'filename': d.get('filename', '')  # Get filename
                })
    
    def cancel_download(self):
        """Cancel any ongoing download."""
        if self.downloading:  # If download is in progress
            self.cancelled = True  # Set cancellation flag
            # Try to stop the download
            if self.ydl_instance:  # If yt-dlp instance exists
                try:
                    self.ydl_instance.interrupt_download()  # Try to interrupt download
                except:
                    pass  # Ignore any errors during interruption
            return True  # Return success
        return False  # Return failure if not downloading
    
    def get_available_formats(self, url):
        """Get available formats for the given YouTube URL."""
        # Check if URL info is cached
        if url in info_cache:  # If URL is in cache
            logging.info(f"Using cached info for {url}")  # Log cache hit
            return info_cache[url]  # Return cached info
            
        try:
            # Configure basic yt-dlp options for format extraction
            ydl_opts = {
                'quiet': True,  # Suppress output
                'no_warnings': True,  # Suppress warnings
                'logger': None,  # Disable logging
                'ignoreerrors': False,  # Don't ignore errors
                'noplaylist': True,  # Don't download playlists
            }
            
            # Extract video information
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # Create yt-dlp instance
                info = ydl.extract_info(url, download=False)  # Get video info without downloading
                self.current_info = info  # Store current video info
                
                if not info:  # If no info was retrieved
                    return [], None  # Return empty lists
                
                # Create basic video information dictionary
                video_info = {
                    'title': info.get('title', 'Unknown title'),  # Video title
                    'duration': info.get('duration', 0),  # Video duration
                    'channel': info.get('channel', 'Unknown channel'),  # Channel name
                    'thumbnail': info.get('thumbnail', None),  # Thumbnail URL
                    'view_count': info.get('view_count', 0),  # View count
                    'upload_date': info.get('upload_date', 'Unknown'),  # Upload date
                    'uploader': info.get('uploader', 'Unknown'),  # Uploader name
                    'description': info.get('description', ''),  # Video description
                    'webpage_url': info.get('webpage_url', url),  # Video URL
                    'id': info.get('id', ''),  # Video ID
                }
                
                # Initialize formats list
                formats = []
                
                # Get video duration for size estimation
                duration_sec = info.get('duration', 0)
                
                # Create audio format option
                audio_format = {
                    'id': 'mp3',  # Format ID
                    'ext': 'mp3',  # File extension
                    'format_note': 'Best Audio (MP3)',  # Format description
                    'filesize': None,  # File size (to be calculated)
                    'resolution': 'Audio only',  # Resolution info
                    'is_audio': True,  # Audio flag
                    'acodec': 'mp3',  # Audio codec
                    'abr': 192,  # Audio bitrate
                }
                
                # Calculate audio file size
                audio_size = estimate_filesize({'abr': 192}, duration_sec)  # Estimate size
                if audio_size:  # If size was estimated
                    audio_format['filesize'] = audio_size  # Store estimated size
                    
                formats.append(audio_format)  # Add audio format to list
                
                # Initialize video format processing
                video_formats = []  # List for video formats
                seen_qualities = set()  # Set to track unique qualities
                
                # Process each available format
                for fmt in info.get('formats', []):  # Iterate through formats
                    # Skip audio-only formats
                    if fmt.get('vcodec', '') == 'none':  # If no video codec
                        continue  # Skip this format
                    
                    # Extract format details
                    height = fmt.get('height', 0)  # Video height
                    width = fmt.get('width', 0)  # Video width
                    ext = fmt.get('ext', '')  # File extension
                    
                    # Skip formats without resolution info
                    if not height or not width:  # If missing resolution
                        continue  # Skip this format
                    
                    # Create quality identifier
                    quality_id = f"{height}p"  # Format: "720p", "1080p", etc.
                    
                    # Skip duplicate qualities
                    if quality_id in seen_qualities:  # If quality already seen
                        continue  # Skip this format
                    
                    seen_qualities.add(quality_id)  # Add quality to seen set
                    
                    # Get file size with fallbacks
                    filesize = fmt.get('filesize')  # Try direct filesize
                    if not filesize:  # If not available
                        filesize = fmt.get('filesize_approx')  # Try approximate size
                    if not filesize:  # If still not available
                        filesize = estimate_filesize(fmt, duration_sec)  # Estimate size
                    
                    # Get codec information
                    vcodec = fmt.get('vcodec', 'unknown')  # Video codec
                    acodec = fmt.get('acodec', 'unknown')  # Audio codec
                    format_note = fmt.get('format_note', '')  # Format note
                    if not format_note:  # If no format note
                        format_note = f"{vcodec}/{acodec}"  # Use codec info
                    
                    # Add format to video formats list
                    video_formats.append({
                        'id': fmt['format_id'],  # Format ID
                        'ext': ext,  # File extension
                        'height': height,  # Video height
                        'width': width,  # Video width
                        'format_note': format_note,  # Format description
                        'filesize': filesize,  # File size
                        'resolution': f"{width}x{height}",  # Resolution string
                        'quality_name': quality_id,  # Quality name
                        'is_audio': False,  # Not audio-only
                        'vcodec': vcodec,  # Video codec
                        'acodec': acodec,  # Audio codec
                        'tbr': fmt.get('tbr', 0),  # Total bitrate
                    })
                
                # Sort video formats by height (highest quality first)
                video_formats.sort(key=lambda x: x['height'], reverse=True)
                
                # Add video formats to main format list
                formats.extend(video_formats)
                
                # Cache the results
                info_cache[url] = (formats, video_info)
                
                return formats, video_info  # Return format list and video info
                
        except Exception as e:  # Handle any errors
            logging.error(f"Error fetching formats: {e}")  # Log error
            return [], None  # Return empty lists on error
    
    def download_video(self, url, download_dir, selected_format, filename_template=None):
        """Download a YouTube video with the selected format."""
        self.downloading = True  # Set downloading flag
        self.cancelled = False   # Reset cancellation flag
        video_title = "Unknown"  # Default video title
        
        try:
            # Handle filename template
            if not filename_template:  # If no template provided
                filename_template = os.path.join(download_dir, '%(title)s.%(ext)s')  # Use default template
            else:
                # Sanitize custom filename
                filename_template = sanitize_filename(filename_template)  # Clean filename
                # Add appropriate extension
                ext = 'mp3' if selected_format == 'mp3' else 'mp4'  # Determine extension
                filename_template = os.path.join(download_dir, f"{filename_template}.{ext}")  # Create full path
            
            # Configure yt-dlp options
            ydl_opts = {
                'noplaylist': True,  # Don't download playlists
                'progress_hooks': [self.progress_hook],  # Add progress callback
                'outtmpl': filename_template,  # Set output template
                'restrictfilenames': True,  # Restrict filename characters
                'quiet': False,  # Show progress
                'no_warnings': True,  # Suppress warnings
                'nocheckcertificate': True,  # Skip certificate verification
                'http_headers': {  # Set browser-like headers
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                },
                'socket_timeout': 30,  # Set socket timeout
                'retries': 3,  # Number of retries
                'ignoreerrors': False,  # Don't ignore errors
                'verbose': False,  # Don't show verbose output
                'merge_output_format': 'mp4',  # Set output format
                'postprocessors': [{  # Configure post-processing
                    'key': 'FFmpegVideoConvertor',  # Use FFmpeg for conversion
                    'preferedformat': 'mp4',  # Convert to MP4
                }],
                'buffersize': 1024 * 16,  # Set buffer size
                'concurrent_fragment_downloads': 3,  # Number of concurrent downloads
                'progress': True,  # Show progress
                'noprogress': False,  # Ensure progress is shown
                'format': selected_format,  # Use selected format
            }
            
            # Find FFmpeg installation
            ffmpeg_path = shutil.which("ffmpeg")  # Look for FFmpeg in PATH
            if ffmpeg_path:  # If FFmpeg is found
                ydl_opts['ffmpeg_location'] = ffmpeg_path  # Set FFmpeg path
            
            # Configure format-specific options
            if selected_format == 'mp3':  # If audio-only download
                ydl_opts.update({  # Update options for MP3
                    'format': 'bestaudio/best',  # Get best audio
                    'postprocessors': [{  # Configure audio processing
                        'key': 'FFmpegExtractAudio',  # Extract audio
                        'preferredcodec': 'mp3',  # Use MP3 codec
                        'preferredquality': '192',  # Set quality
                    }],
                    'prefer_ffmpeg': True,  # Prefer FFmpeg
                    'keepvideo': False,  # Don't keep video
                })
            elif selected_format == 'best':  # If best quality requested
                ydl_opts.update({  # Update options for best quality
                    'format': 'bestvideo+bestaudio/best',  # Get best video and audio
                    'merge_output_format': 'mp4',  # Merge into MP4
                    'prefer_ffmpeg': True,  # Prefer FFmpeg
                })
            elif selected_format.isdigit() or selected_format in ['mp4', 'webm', 'mov']:  # If specific format
                if selected_format.isdigit():  # If format ID provided
                    ydl_opts.update({  # Update options for format ID
                        'format': selected_format + '+bestaudio/best',  # Use format ID with best audio
                        'merge_output_format': 'mp4',  # Merge into MP4
                        'prefer_ffmpeg': True,  # Prefer FFmpeg
                    })
                else:  # If container format specified
                    ydl_opts.update({  # Update options for container format
                        'format': 'bestvideo+bestaudio/best',  # Get best video and audio
                        'merge_output_format': selected_format,  # Use specified container
                        'prefer_ffmpeg': True,  # Prefer FFmpeg
                    })
            else:  # If quality-based selection (e.g., "1080p")
                try:  # Try to parse resolution
                    height = int(selected_format.rstrip('p'))  # Extract height value
                    ydl_opts.update({  # Update options for resolution
                        'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',  # Limit to height
                        'merge_output_format': 'mp4',  # Merge into MP4
                        'prefer_ffmpeg': True,  # Prefer FFmpeg
                    })
                except ValueError:  # If not a resolution
                    ydl_opts.update({  # Use format directly
                        'format': selected_format,  # Use provided format
                        'merge_output_format': 'mp4',  # Merge into MP4
                        'prefer_ffmpeg': True,  # Prefer FFmpeg
                    })
            
            # Perform the download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # Create yt-dlp instance
                self.ydl_instance = ydl  # Store instance for cancellation
                
                # Get video info if not already available
                info = self.current_info or ydl.extract_info(url, download=False)  # Extract info
                video_title = info.get('title', 'Unknown title')  # Get video title
                
                # Log download start
                logging.info(f"Starting download: {video_title}")  # Log start
                
                # Check for cancellation
                if self.cancel_requested:  # If cancelled
                    raise DownloadCancelledError("Download cancelled by user")  # Raise error
                
                # Start download
                ydl.download([url])  # Download video
                
                # Log completion
                logging.info(f"Download completed: {video_title}")  # Log completion
                
                # Clean up temporary files
                self._cleanup_temp_files(download_dir)  # Clean up
                
                # Update progress to complete
                if self.progress_callback:  # If callback exists
                    self.progress_callback({  # Call with completion info
                        'percent': 100,  # Set to 100%
                        'status': 'complete',  # Set status
                        'filename': video_title  # Set filename
                    })
                
                return video_title, True  # Return success
                
        except DownloadCancelledError as e:  # Handle cancellation
            logging.info(f"Download cancelled: {e}")  # Log cancellation
            
            if self.progress_callback:  # If callback exists
                self.progress_callback({  # Call with cancellation info
                    'percent': 0,  # Reset progress
                    'status': 'cancelled',  # Set status
                    'filename': video_title  # Set filename
                })
            
            # Clean up partial download
            self._cleanup_temp_files(download_dir)  # Clean up
            
            return video_title, False  # Return failure
            
        except yt_dlp.utils.DownloadError as e:  # Handle download errors
            logging.error(f"Download error: {e}")  # Log error
            
            if self.progress_callback:  # If callback exists
                self.progress_callback({  # Call with error info
                    'percent': 0,  # Reset progress
                    'status': 'error',  # Set status
                    'error': str(e),  # Set error message
                    'filename': video_title  # Set filename
                })
            
            return video_title, False  # Return failure
        
        except (IOError, OSError) as e:  # Handle file system errors
            logging.error(f"File system error: {e}")  # Log error
            
            if self.progress_callback:  # If callback exists
                self.progress_callback({  # Call with error info
                    'percent': 0,  # Reset progress
                    'status': 'error',  # Set status
                    'error': f"File error: {str(e)}",  # Set error message
                    'filename': video_title  # Set filename
                })
            
            return video_title, False  # Return failure
            
        except Exception as e:  # Handle other errors
            logging.error(f"Unexpected error: {e}")  # Log error
            
            if self.progress_callback:  # If callback exists
                self.progress_callback({  # Call with error info
                    'percent': 0,  # Reset progress
                    'status': 'error',  # Set status
                    'error': str(e),  # Set error message
                    'filename': video_title  # Set filename
                })
            
            return video_title, False  # Return failure
        
        finally:  # Clean up
            self.downloading = False  # Reset downloading flag
            self.cancel_requested = False  # Reset cancellation flag
            self.ydl_instance = None  # Clear yt-dlp instance
    
    @staticmethod
    def _cleanup_temp_files(directory):  # Clean up temporary files
        """Clean up temporary files created during download."""
        try:  # Try to clean up
            # List of temporary file extensions
            temp_extensions = [  # Define extensions
                '.part', '.temp', '.f140.mp4', '.f137.mp4', 
                '.f401.mp4', '.m4a', '.webm', '.ytdl'
            ]
            
            # Process directory files
            for file in os.listdir(directory):  # List files
                # Check for temporary files
                is_temp = any(file.endswith(ext) for ext in temp_extensions)  # Check extension
                
                # Remove temporary files
                if is_temp:  # If temporary
                    try:  # Try to remove
                        os.remove(os.path.join(directory, file))  # Remove file
                        logging.debug(f"Cleaned up: {file}")  # Log cleanup
                    except (IOError, OSError) as e:  # Handle removal errors
                        logging.warning(f"Could not remove temporary file {file}: {e}")  # Log warning
        
        except Exception as e:  # Handle cleanup errors
            logging.warning(f"Cleanup error: {e}")  # Log warning

class DownloadManagerApp:
    """Main application class for the YouTube Video Downloader GUI."""
    
    def __init__(self, root):  # Initialize the application
        """Initialize the application GUI."""
        # Set the window title and main reference
        self.root = root  # Store root window reference
        self.root.title("YouTube Video Downloader")  # Set window title
        
        # Initialize style variable
        self.style = ttk.Style()  # Create style object
        
        # Configure window size and position
        window_width = 850  # Set window width
        window_height = 800  # Set window height
        screen_width = root.winfo_screenwidth()  # Get screen width
        screen_height = root.winfo_screenheight()  # Get screen height
        # Calculate center position
        x = (screen_width - window_width) // 2  # Calculate x position
        y = (screen_height - window_height) // 2  # Calculate y position
        # Set window geometry
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")  # Set size and position
        
        # Set minimum window size
        self.root.minsize(750, 700)  # Prevent too small windows
        
        # Fix Windows button styling
        if os.name == 'nt':  # If on Windows
            self.root.tk_setPalette(background='#f0f0f0')  # Set background color
        
        # Initialize application variables
        self.download_directory = DEFAULT_DOWNLOAD_DIR  # Set default download directory
        self.dark_mode = False  # Initialize dark mode state
        self.downloader = YoutubeDownloader(self.update_progress, self.update_format_list)  # Create downloader
        self.available_formats = []  # List for available formats
        self.video_info = None  # Store video information
        self.thumbnail_image = None  # Store thumbnail image
        self.custom_filename = None  # Store custom filename
        self.active_download_thread = None  # Store download thread
        self.thumbnail_load_thread = None  # Store thumbnail thread
        self.speed_boost_active = False  # Speed boost state
        self.download_cancelled = False  # Download cancellation state
        
        # Configure window closing behavior
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)  # Set close handler
        
        # Create main container
        self.main_container = ttk.Frame(self.root)  # Create main frame
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)  # Pack main frame
        
        # Configure grid weights
        self.main_container.grid_columnconfigure(0, weight=1)  # Configure column weight
        self.main_container.grid_rowconfigure(1, weight=1)  # Configure row weight
        
        # Create UI sections
        self._create_directory_section()  # Create directory section
        self._create_url_section()  # Create URL section
        self._create_thumbnail_section()  # Create thumbnail section
        self._create_format_section()  # Create format section
        self._create_quality_section()  # Create quality section
        self._create_progress_section()  # Create progress section
        self._create_control_section()  # Create control section
        
        # Configure styles
        self._configure_styles()  # Set up styles
        
        # Load saved settings
        self._load_settings()  # Load user settings
        
        # Set up periodic updates
        self._setup_periodic_updates()  # Configure update schedule
    
    def _set_initial_text_colors(self):
        """Set initial text colors for all widgets."""
        # Define color scheme
        bg_color = "#f0f0f0"  # Background color
        fg_color = "#000000"  # Foreground color
        entry_bg = "#FFFFFF"  # Entry background
        entry_fg = "#000000"  # Entry foreground
        
        # Configure ttk styles
        self.style.configure("TLabel", background=bg_color, foreground=fg_color)  # Label style
        self.style.configure("TButton", background=bg_color, foreground=fg_color)  # Button style
        self.style.configure("TFrame", background=bg_color)  # Frame style
        self.style.configure("TLabelframe", background=bg_color)  # Label frame style
        self.style.configure("TLabelframe.Label", background=bg_color, foreground=fg_color)  # Label frame label style
        self.style.configure("Treeview", background=entry_bg, foreground=fg_color, fieldbackground=entry_bg)  # Tree view style
        self.style.configure("Treeview.Heading", background=bg_color, foreground=fg_color)  # Tree view heading style
    
    def _configure_styles(self):
        """Configure the application's visual styles."""
        style = self.style  # Get ttk style object
        
        # Configure default button style
        style.configure(
            "TButton",  # Style name
            background="#4285F4",  # Google Blue color
            foreground="white",  # White text
            padding=5,  # Button padding
            font=("", 10, "bold")  # Font settings
        )
        
        # Configure download button style
        style.configure(
            "Download.TButton",  # Style name
            background="#ffd700",  # Gold color
            foreground="black",  # Black text
            padding=5,  # Button padding
            font=("", 10, "bold")  # Font settings
        )
        
        # Configure speed boost button style
        style.configure(
            "SpeedBoostActive.TButton",  # Style name
            background="#00ff00",  # Green color
            foreground="black",  # Black text
            padding=5,  # Button padding
            font=("", 10, "bold")  # Font settings
        )
        
        # Configure dark mode button style
        style.configure(
            "DarkMode.TButton",  # Style name
            background="#0078d7",  # Blue color
            foreground="white",  # White text
            padding=5,  # Button padding
            font=("", 10, "bold")  # Font settings
        )
        
        # Configure cancel button style
        style.configure(
            "Cancel.TButton",  # Style name
            background="#555555",  # Gray color
            foreground="white",  # White text
            padding=5,  # Button padding
            font=("", 10, "bold")  # Font settings
        )
    
    def _create_directory_section(self):
        """Create the download directory section of the UI."""
        # Create labeled frame for directory section
        dir_frame = ttk.LabelFrame(self.main_container, text="Download Location", padding="5")  # Create frame
        dir_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")  # Pack frame with padding
        
        # Create directory entry field
        self.dir_entry = ttk.Entry(dir_frame)  # Create entry widget
        self.dir_entry.insert(0, self.download_directory)  # Set default directory
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))  # Pack entry
        
        # Create browse button
        self.change_dir_button = tk.Button(
            dir_frame,  # Parent widget
            text="Browse...",  # Button text
            command=self.change_directory,  # Click handler
            bg="#4285F4",  # Google Blue background
            fg="white",  # White text
            activebackground="#5a95f5",  # Active state color
            activeforeground="white",  # Active text color
            padx=10,  # Horizontal padding
            pady=5,  # Vertical padding
            font=("", 10, "bold"),  # Font settings
            relief=tk.RAISED,  # 3D effect
            bd=3  # Border width
        )
        self.change_dir_button.pack(side=tk.RIGHT, padx=(0, 5))  # Pack button
    
    def _create_url_section(self):
        """Create the URL input section of the UI."""
        # Create labeled frame for URL section
        url_frame = ttk.LabelFrame(self.main_container, text="Video URL", padding="5")  # Create frame
        url_frame.grid(row=1, column=0, padx=5, pady=5, sticky="ew")  # Pack frame with padding
        
        # Create URL entry field
        self.url_entry = ttk.Entry(url_frame)  # Create entry widget
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))  # Pack entry
        
        # Create search button
        self.fetch_button = tk.Button(
            url_frame,  # Parent widget
            text="Search",  # Button text
            command=self.fetch_video_info,  # Click handler
            bg="#4285F4",  # Google Blue background
            fg="white",  # White text
            activebackground="#5a95f5",  # Active state color
            activeforeground="white",  # Active text color
            padx=10,  # Horizontal padding
            pady=5,  # Vertical padding
            font=("", 10, "bold"),  # Font settings
            relief=tk.RAISED,  # 3D effect
            bd=3  # Border width
        )
        self.fetch_button.pack(side=tk.RIGHT, padx=(0, 5))  # Pack button
        
        # Add tooltip to URL entry
        create_tooltip(self.url_entry, "Enter a YouTube video URL (youtube.com or youtu.be)")  # Create tooltip
        
        # Bind Enter key to fetch video info
        self.url_entry.bind("<Return>", lambda event: self.fetch_video_info())  # Add key binding
    
    def _create_thumbnail_section(self):
        """Create the thumbnail preview section of the UI."""
        # Create labeled frame for thumbnail section
        thumbnail_frame = ttk.LabelFrame(self.main_container, text="Video Preview", padding="5")  # Create frame
        thumbnail_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")  # Pack frame with padding
        
        # Create frame for thumbnail and filename
        preview_frame = ttk.Frame(thumbnail_frame)  # Create container frame
        preview_frame.pack(fill=tk.X, expand=True)  # Pack frame
        
        # Create thumbnail label
        self.thumbnail_label = ttk.Label(preview_frame, text="No video selected")  # Create label
        self.thumbnail_label.pack(side=tk.LEFT, padx=(5, 10))  # Pack label
        
        # Create frame for filename controls
        filename_frame = ttk.Frame(preview_frame)  # Create filename frame
        filename_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)  # Pack frame
        
        # Create filename label
        ttk.Label(filename_frame, text="Output Filename:").pack(anchor=tk.W)  # Create and pack label
        
        # Create frame for filename entry and reset button
        filename_entry_frame = ttk.Frame(filename_frame)  # Create entry frame
        filename_entry_frame.pack(fill=tk.X, pady=(2, 0))  # Pack frame
        
        # Create filename entry field
        self.filename_entry = ttk.Entry(filename_entry_frame)  # Create entry widget
        self.filename_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)  # Pack entry
        
        # Create reset filename button
        self.reset_filename_button = tk.Button(
            filename_entry_frame,  # Parent widget
            text="Reset",  # Button text
            command=self.reset_filename,  # Click handler
            bg="#4285F4",  # Google Blue background
            fg="white",  # White text
            activebackground="#5a95f5",  # Active state color
            activeforeground="white",  # Active text color
            padx=10,  # Horizontal padding
            pady=5,  # Vertical padding
            font=("", 10, "bold"),  # Font settings
            relief=tk.RAISED,  # 3D effect
            bd=3,  # Border width
            width=10  # Fixed width
        )
        self.reset_filename_button.pack(side=tk.RIGHT, padx=(5, 0))  # Pack button
        self.reset_filename_button.config(state=tk.DISABLED)  # Initially disabled
        
        # Create frame for video info
        self.video_info_frame = ttk.Frame(filename_frame)  # Create info frame
        self.video_info_frame.pack(fill=tk.X, pady=(5, 0))  # Pack frame
        
        # Create info labels
        self.info_label = ttk.Label(self.video_info_frame, text="")  # Create info label
        self.info_label.pack(anchor=tk.W, fill=tk.X)  # Pack label
        
        self.channel_label = ttk.Label(self.video_info_frame, text="")  # Create channel label
        self.channel_label.pack(anchor=tk.W, fill=tk.X)  # Pack label
    
    def _create_format_section(self):
        """Create the format selection section of the UI."""
        # Create labeled frame for format section
        format_frame = ttk.LabelFrame(self.main_container, text="Format Type", padding="5")  # Create frame
        format_frame.grid(row=3, column=0, padx=5, pady=5, sticky="ew")  # Pack frame with padding
        
        # Create format selection variable
        self.format_var = tk.StringVar(value="mp4")  # Default to MP4
        
        # Create MP4 radio button
        self.mp4_button = ttk.Radiobutton(
            format_frame,  # Parent widget
            text="Video (MP4)",  # Button text
            variable=self.format_var,  # Selection variable
            value="mp4",  # Button value
            command=self.format_changed  # Change handler
        )
        self.mp4_button.pack(side=tk.LEFT, padx=(5, 15))  # Pack button
        
        # Create MP3 radio button
        self.mp3_button = ttk.Radiobutton(
            format_frame,  # Parent widget
            text="Audio (MP3)",  # Button text
            variable=self.format_var,  # Selection variable
            value="mp3",  # Button value
            command=self.format_changed  # Change handler
        )
        self.mp3_button.pack(side=tk.LEFT)  # Pack button
    
    def _create_quality_section(self):
        """Create the quality selection section of the UI."""
        # Create labeled frame for quality section
        quality_frame = ttk.LabelFrame(self.main_container, text="Quality Options", padding="5")  # Create frame
        quality_frame.grid(row=4, column=0, padx=5, pady=5, sticky="ew")  # Pack frame with padding
        
        # Create format list widget
        self.format_list = ttk.Treeview(
            quality_frame,  # Parent widget
            columns=("resolution", "ext", "filesize"),  # Define columns
            show="headings",  # Show column headings
            height=6  # Show 6 rows
        )
        
        # Configure column headings
        self.format_list.heading("resolution", text="Resolution")  # Resolution column
        self.format_list.heading("ext", text="Format")  # Format column
        self.format_list.heading("filesize", text="File Size")  # Size column
        
        # Configure column properties
        self.format_list.column("resolution", width=150, anchor=tk.CENTER, stretch=True)  # Resolution column
        self.format_list.column("ext", width=100, anchor=tk.CENTER, stretch=True)  # Format column
        self.format_list.column("filesize", width=150, anchor=tk.CENTER, stretch=True)  # Size column
        
        # Create scrollbar
        quality_scrollbar = ttk.Scrollbar(
            quality_frame,  # Parent widget
            orient=tk.VERTICAL,  # Vertical orientation
            command=self.format_list.yview  # Link to list view
        )
        
        # Configure list to use scrollbar
        self.format_list.configure(yscrollcommand=quality_scrollbar.set)  # Link scrollbar
        
        # Pack widgets
        self.format_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)  # Pack list
        quality_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)  # Pack scrollbar
        
        # Bind selection event
        self.format_list.bind("<<TreeviewSelect>>", self.on_format_select)  # Add selection handler
        
        # Add placeholder message
        self.format_list.insert("", tk.END, values=("No formats available", "", ""))  # Add placeholder
    
    def _create_progress_section(self):
        """Create the progress tracking section of the UI."""
        # Create labeled frame for progress section
        progress_frame = ttk.LabelFrame(self.main_container, text="Download Progress", padding="5")  # Create frame
        progress_frame.grid(row=5, column=0, padx=5, pady=5, sticky="ew")  # Pack frame with padding
        
        # Create progress bar
        self.progress = ttk.Progressbar(
            progress_frame,  # Parent widget
            orient="horizontal",  # Horizontal orientation
            length=300,  # Bar length
            mode="determinate"  # Determinate mode
        )
        self.progress.pack(fill=tk.X, padx=5, pady=(5, 0))  # Pack progress bar
        
        # Create frame for status information
        info_frame = ttk.Frame(progress_frame)  # Create info frame
        info_frame.pack(fill=tk.X, padx=5, pady=(5, 5))  # Pack frame
        
        # Create status label
        self.status_label = ttk.Label(info_frame, text="Ready")  # Create label
        self.status_label.pack(side=tk.LEFT)  # Pack label
        
        # Create speed label
        self.speed_label = ttk.Label(info_frame, text="")  # Create label
        self.speed_label.pack(side=tk.RIGHT, padx=(0, 5))  # Pack label
        
        # Create ETA label
        self.eta_label = ttk.Label(info_frame, text="")  # Create label
        self.eta_label.pack(side=tk.RIGHT, padx=(0, 10))  # Pack label
    
    def _create_control_section(self):
        """Create the control section with download and cancel buttons."""
        # Create control frame
        control_frame = ttk.Frame(self.main_container)  # Create frame
        control_frame.grid(row=6, column=0, padx=5, pady=5, sticky="ew")  # Pack frame

        # Download button (using regular tk.Button for better styling)
        self.download_button = tk.Button(
            control_frame,
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
            control_frame,
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
            control_frame,
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
            control_frame,
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
                self.download_cancelled = False
                self.cancel_button.config(state=tk.DISABLED)
                self.download_button.config(state=tk.NORMAL)
                self.fetch_button.config(state=tk.NORMAL)
                
        except Exception as e:
            logging.error(f"Error updating progress: {e}")
    
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
        self.download_cancelled = True

        # Configure yt-dlp options
        ydl_opts = {
            'format': selected_format,
            'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
            'progress_hooks': [self.update_progress],
            'quiet': False,  # Changed to False to show progress
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'no_color': True,
            'prefer_insecure': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            'merge_output_format': 'mp4',  # Force MP4 output
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            # Optimize download speed
            'buffersize': 1024 * 16,  # Increase buffer size
            'concurrent_fragment_downloads': 3,  # Download fragments in parallel
        }

        # Apply speed boost optimizations if enabled
        if self.speed_boost_active:
            ydl_opts.update({
                'buffer_size': 32768,  # Increased buffer size
                'concurrent_fragments': 3,  # Parallel downloads
                'chunk_size': 10485760,  # 10MB chunks
                'retries': 10,  # More retries
                'fragment_retries': 10,
                'file_access_retries': 10,
                'extractor_retries': 10,
                'socket_timeout': 30,  # Longer timeout
                'noprogress': False,
                'progress': True
            })

        # Start download in a separate thread
        self.download_thread = threading.Thread(
            target=self._download_thread_func,
            args=(self.video_info['webpage_url'], download_dir, selected_format, ydl_opts)
        )
        self.download_thread.daemon = True
        self.download_thread.start()

    def _download_thread_func(self, url, download_dir, selected_format, ydl_opts):
        """Thread function for downloading the video."""
        try:
            # Configure format based on selection
            if selected_format == 'mp3':
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
            else:
                # For video formats, ensure we get both video and audio
                ydl_opts.update({
                    'format': selected_format,  # This now includes bestaudio
                    'merge_output_format': 'mp4',
                    'prefer_ffmpeg': True,
                    'postprocessors': [{
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    }],
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                    'subtitleslangs': [],
                    'keepvideo': False,
                })

            # Find FFmpeg path
            ffmpeg_path = shutil.which("ffmpeg")
            if ffmpeg_path:
                ydl_opts['ffmpeg_location'] = ffmpeg_path

            # Perform the download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first to get title
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'Unknown title')

                # Log the start of download
                logging.info(f"Starting download: {video_title}")

                # Perform the actual download
                ydl.download([url])

                # Log completion
                logging.info(f"Download completed: {video_title}")

                # Update UI with success
                self.root.after(0, lambda: self.status_label.config(text=f"Download completed: {video_title}"))
                self.root.after(0, lambda: messagebox.showinfo("Success", f"'{video_title}' has been downloaded successfully!"))

        except yt_dlp.utils.DownloadError as e:
            # Handle download errors
            error_msg = str(e)
            self.root.after(0, lambda: self.status_label.config(text=f"Error: {error_msg[:50]}..."))
            self.root.after(0, lambda: messagebox.showerror("Download Failed", f"Download error: {error_msg}"))

        except Exception as e:
            # Handle other errors
            error_msg = str(e)
            self.root.after(0, lambda: self.status_label.config(text=f"Error: {error_msg[:50]}..."))
            self.root.after(0, lambda: messagebox.showerror("Error", f"An unexpected error occurred: {error_msg}"))

        finally:
            # Re-enable buttons
            self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.speed_boost_button.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.cancel_button.config(state=tk.DISABLED))
            self.download_cancelled = False
    
    def cancel_download(self):
        """Cancel the current download."""
        if not self.download_cancelled:
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
        self.main_container.configure(style="Main.TFrame")
        
        # Update all frames and their children
        for widget in self.main_container.winfo_children():
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
        if self.download_cancelled:
            if messagebox.askyesno("Quit", "A download is in progress. Cancel and quit?"):
                self.downloader.cancel_download()
        
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
        # Toggle the speed boost state between True and False
        self.speed_boost_active = not self.speed_boost_active
        
        # Create a new window for displaying speed boost status
        popup = tk.Toplevel(self.root)  # Create new window as child of main window
        popup.title("Speed Boost Status")  # Set window title
        popup.geometry("300x200")  # Set window size to 300x200 pixels
        popup.resizable(False, False)  # Prevent window resizing
        
        # Center the popup window on the screen
        popup.update_idletasks()  # Update window geometry
        width = popup.winfo_width()  # Get current window width
        height = popup.winfo_height()  # Get current window height
        x = (popup.winfo_screenwidth() // 2) - (width // 2)  # Calculate x position for center
        y = (popup.winfo_screenheight() // 2) - (height // 2)  # Calculate y position for center
        popup.geometry(f'{width}x{height}+{x}+{y}')  # Set window position to center
        
        # Make the popup window modal (user must interact with it)
        popup.transient(self.root)  # Make window transient (temporary)
        popup.grab_set()  # Grab focus (make window modal)
        
        # Set popup background color based on current theme
        popup.configure(bg="#2E2E2E" if self.dark_mode else "#f0f0f0")
        
        # Create a frame to hold the popup content
        message_frame = ttk.Frame(popup, padding="20")  # Create frame with 20px padding
        message_frame.pack(fill=tk.BOTH, expand=True)  # Pack frame to fill window
        
        # Create a large icon label showing speed boost status
        icon_label = ttk.Label(
            message_frame,  # Parent widget
            text="⚡" if self.speed_boost_active else "🚀",  # Show lightning or rocket emoji
            font=("", 40)  # Set large font size
        )
        icon_label.pack(pady=(0, 10))  # Pack label with bottom padding
        
        # Create a status label showing speed boost state
        status_label = ttk.Label(
            message_frame,  # Parent widget
            text="SPEED BOOST ACTIVATED!" if self.speed_boost_active else "Speed Boost Deactivated",  # Dynamic status text
            font=("", 12, "bold"),  # Set bold font
            foreground="#00ff00" if self.speed_boost_active else "#ff0000"  # Green if active, red if inactive
        )
        status_label.pack(pady=(0, 5))  # Pack label with bottom padding
        
        # Create dynamic message text based on speed boost state
        message_text = (
            "🚀 Download Speed: MAXIMUM\n"  # Speed boost active message
            "⚡ Buffer Size: OPTIMIZED"
        ) if self.speed_boost_active else (
            "Returning to normal download settings.\n"  # Speed boost inactive message
            "Speed boost features disabled."
        )
        
        # Create a label to display the message text
        message_label = ttk.Label(
            message_frame,  # Parent widget
            text=message_text,  # Dynamic message text
            justify=tk.CENTER,  # Center-align text
            font=("", 10)  # Set font size
        )
        message_label.pack(pady=(0, 10))  # Pack label with bottom padding
        
        # Create a close button for the popup
        close_button = tk.Button(
            message_frame,  # Parent widget
            text="Close",  # Button text
            command=popup.destroy,  # Close window when clicked
            bg="#00ff00" if self.speed_boost_active else "#ff0000",  # Green if active, red if inactive
            fg="black",  # Black text color
            activebackground="#00cc00" if self.speed_boost_active else "#cc0000",  # Darker shade for active state
            activeforeground="black",  # Black text when active
            padx=20,  # Horizontal padding
            pady=5,  # Vertical padding
            font=("", 10, "bold"),  # Bold font
            relief=tk.RAISED,  # 3D button effect
            bd=3  # Border width
        )
        close_button.pack(pady=(10, 0))  # Pack button with top padding
        
        # Update the main speed boost button appearance
        if self.speed_boost_active:
            # Configure button for active state
            self.speed_boost_button.configure(
                text="⚡ Speed Boost ON",  # Active state text
                bg="#00ff00",  # Green background
                activebackground="#00cc00"  # Darker green for active state
            )
        else:
            # Configure button for inactive state
            self.speed_boost_button.configure(
                text="⚡ Speed Boost",  # Inactive state text
                bg="#00ff00",  # Green background
                activebackground="#00cc00"  # Darker green for active state
            )
        
        # Automatically close the popup after 3 seconds
        popup.after(3000, popup.destroy)  # Schedule window destruction
    
    def _load_settings(self):  # Load saved settings
        """Load saved application settings."""
        try:  # Try to load settings
            # Check if settings file exists
            if os.path.exists('settings.json'):  # If file exists
                with open('settings.json', 'r') as f:  # Open file
                    settings = json.load(f)  # Load settings
                    
                    # Load download directory
                    if 'download_directory' in settings:  # If directory saved
                        saved_dir = settings['download_directory']  # Get saved directory
                        if os.path.exists(saved_dir):  # If directory exists
                            self.download_directory = saved_dir  # Use saved directory
                            self.dir_entry.delete(0, tk.END)  # Clear entry
                            self.dir_entry.insert(0, saved_dir)  # Set saved directory
                    
                    # Load dark mode setting
                    if 'dark_mode' in settings:  # If dark mode saved
                        self.dark_mode = settings['dark_mode']  # Get dark mode setting
                        self.toggle_dark_mode()  # Apply dark mode
                    
                    # Load speed boost setting
                    if 'speed_boost' in settings:  # If speed boost saved
                        self.speed_boost_active = settings['speed_boost']  # Get speed boost setting
                        self.toggle_speed_boost()  # Apply speed boost
                        
        except Exception as e:  # Handle any errors
            logging.error(f"Error loading settings: {e}")  # Log error
    
    def _save_settings(self):  # Save current settings
        """Save current application settings."""
        try:  # Try to save settings
            settings = {  # Create settings dictionary
                'download_directory': self.download_directory,  # Save download directory
                'dark_mode': self.dark_mode,  # Save dark mode setting
                'speed_boost': self.speed_boost_active,  # Save speed boost setting
            }
            
            with open('settings.json', 'w') as f:  # Open file for writing
                json.dump(settings, f)  # Save settings
                
        except Exception as e:  # Handle any errors
            logging.error(f"Error saving settings: {e}")  # Log error
    
    def _setup_periodic_updates(self):  # Set up periodic updates
        """Set up periodic UI updates."""
        def update_ui():  # Define update function
            try:  # Try to update UI
                # Update download speed if active
                if self.downloader.downloading:  # If downloading
                    self._update_speed_display()  # Update speed display
                
                # Update ETA if available
                if hasattr(self.downloader, 'current_eta'):  # If ETA available
                    self._update_eta_display()  # Update ETA display
                
                # Schedule next update
                self.root.after(1000, update_ui)  # Schedule next update
                
            except Exception as e:  # Handle any errors
                logging.error(f"Error in UI update: {e}")  # Log error
        
        # Start periodic updates
        self.root.after(1000, update_ui)  # Start update cycle
    
    def _update_speed_display(self):  # Update speed display
        """Update the download speed display."""
        try:  # Try to update speed
            if hasattr(self.downloader, 'current_speed'):  # If speed available
                speed = self.downloader.current_speed  # Get current speed
                if speed:  # If speed is not None
                    self.speed_label.config(  # Update speed label
                        text=f"Speed: {format_filesize(speed)}/s"  # Format speed
                    )
                    
        except Exception as e:  # Handle any errors
            logging.error(f"Error updating speed: {e}")  # Log error
    
    def _update_eta_display(self):  # Update ETA display
        """Update the estimated time remaining display."""
        try:  # Try to update ETA
            if hasattr(self.downloader, 'current_eta'):  # If ETA available
                eta = self.downloader.current_eta  # Get current ETA
                if eta:  # If ETA is not None
                    self.eta_label.config(  # Update ETA label
                        text=f"ETA: {format_duration(eta)}"  # Format ETA
                    )
                    
        except Exception as e:  # Handle any errors
            logging.error(f"Error updating ETA: {e}")  # Log error
    
    def on_closing(self):  # Handle window closing
        """Handle application window closing."""
        try:  # Try to handle closing
            # Check for active downloads
            if self.downloader.downloading:  # If download in progress
                # Ask user for confirmation
                if messagebox.askyesno("Quit", "A download is in progress. Cancel and quit?"):
                    self.downloader.cancel_download()  # Cancel download
                    self._save_settings()  # Save settings
                    self.root.destroy()  # Destroy window
            else:  # If no download in progress
                self._save_settings()  # Save settings
                self.root.destroy()  # Destroy window
                
        except Exception as e:  # Handle any errors
            logging.error(f"Error during closing: {e}")  # Log error
            self.root.destroy()  # Force close window

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
            if os.name == 'nt':
                root.iconbitmap(default='icon.ico')
            else:
                logo = tk.PhotoImage(file='icon.png')
                root.iconphoto(True, logo)
        except FileNotFoundError:
            pass
        except tk.TclError:
            pass
        
        # Start main event loop
        root.mainloop()
        
    except Exception as e:
        logging.critical(f"Fatal error: {e}", exc_info=True)
        messagebox.showerror(
            "Fatal Error",
            f"An unexpected error occurred: {str(e)}\n\nCheck the log file for details."
        )
    
    finally:
        # Clean up resources before exit
        for thread in active_downloads:
            if thread and thread.is_alive():
                try:
                    thread.join(0.1)
                except:
                    pass

if __name__ == "__main__":
    main()
