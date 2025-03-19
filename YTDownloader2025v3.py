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
"""

# Import required libraries
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import yt_dlp
import os
import shutil
import logging
import re
import threading
import unicodedata
import json
from functools import partial

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('download_manager.log')
    ]
)

# Filter out verbose messages from yt-dlp and ffmpeg
for logger_name in ['yt_dlp', 'ffmpeg']:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.ERROR)

# Set default download directory based on OS
DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

class CustomFormatter(logging.Formatter):
    """Custom formatter to color logs based on their level"""
    
    def format(self, record):
        # Create a clean message without ANSI color codes
        message = super().format(record)
        return message

# Utility Functions
def safe_json_dumps(data):
    """Safely serialize data to JSON format, excluding non-serializable types."""
    try:
        # Attempt to convert the entire data dictionary to JSON
        return json.dumps(data, indent=4)
    except TypeError:
        # Handle non-serializable types
        clean_data = {}
        for k, v in data.items():
            try:
                json.dumps({k: v})
                clean_data[k] = v
            except TypeError:
                clean_data[k] = str(v)
        return json.dumps(clean_data, indent=4)

def is_ffmpeg_installed():
    """Check if FFmpeg is installed by verifying if it's in the system path."""
    return shutil.which("ffmpeg") is not None

def validate_directory(directory):
    """Check if the given directory exists and is writable."""
    return os.path.isdir(directory) and os.access(directory, os.W_OK)

def is_valid_youtube_url(url):
    """Validate if a given URL is a valid YouTube link."""
    youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'
    return bool(re.match(youtube_regex, url))

def sanitize_filename(filename):
    """Sanitize a filename by removing invalid characters and normalizing."""
    # Normalize unicode characters
    filename = unicodedata.normalize('NFKD', filename)
    # Replace spaces with underscores
    filename = filename.replace(' ', '_')
    # Remove any characters that aren't word chars, hyphens, underscores, or periods
    filename = re.sub(r'[^\w\-_\.]', '', filename)
    return filename

def format_filesize(bytes_size):
    """Format file size in bytes to human-readable format."""
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
    """Create a tooltip for a widget."""
    def enter(event):
        # Create tooltip window
        x, y, _, _ = widget.bbox("insert")
        x += widget.winfo_rootx() + 25
        y += widget.winfo_rooty() + 25
        
        # Create a toplevel window
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
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
    """Core functionality for downloading YouTube videos with yt-dlp."""
    
    def __init__(self, progress_callback=None, format_callback=None):
        """Initialize the downloader with callbacks for progress updates."""
        self.progress_callback = progress_callback
        self.format_callback = format_callback
        self.downloading = False
        self.current_info = None
    
    def progress_hook(self, d):
        """Process download progress updates from yt-dlp."""
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
            # Post-processing stage
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
        """Fetch available formats for the given YouTube URL."""
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
                }
                
                # Get formats
                formats = []
                
                # Add audio formats
                formats.append({
                    'id': 'mp3',
                    'ext': 'mp3',
                    'format_note': 'Best Audio (MP3)',
                    'filesize': None,
                    'resolution': 'Audio only',
                    'is_audio': True
                })
                
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
                    
                    # Format the filesize
                    filesize = fmt.get('filesize')
                    filesize_str = format_filesize(filesize) if filesize else "Unknown"
                    
                    # Add this format to our list
                    video_formats.append({
                        'id': fmt['format_id'],
                        'ext': ext,
                        'height': height,
                        'width': width,
                        'format_note': fmt.get('format_note', ''),
                        'filesize': filesize_str,
                        'resolution': f"{width}x{height}",
                        'quality_name': quality_id,
                        'is_audio': False
                    })
                
                # Sort video formats by height (resolution)
                video_formats.sort(key=lambda x: x['height'], reverse=True)
                
                # Add video formats to main format list
                formats.extend(video_formats)
                
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
        video_title = "Unknown"
        
        try:
            # Default filename template if not provided
            if not filename_template:
                filename_template = os.path.join(download_dir, '%(title)s.%(ext)s')
            
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
    
    def __init__(self, root):
        """Initialize the application GUI."""
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("700x550")
        self.root.minsize(600, 450)
        
        # Fix for Windows button styling
        if os.name == 'nt':
            self.root.tk_setPalette(background='#f0f0f0')
        
        # Initialize variables
        self.download_directory = DEFAULT_DOWNLOAD_DIR
        self.dark_mode = False
        self.downloader = YoutubeDownloader(self.update_progress, self.update_format_list)
        self.available_formats = []
        self.video_info = None
        
        # Configure styles before creating UI elements
        self._configure_styles()
        
        # Create main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create UI elements
        self._create_directory_section()
        self._create_url_section()
        self._create_format_section()
        self._create_quality_section()
        self._create_progress_section()
        self._create_control_section()
        
        # Check for FFmpeg on startup
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
        dir_frame = ttk.LabelFrame(self.main_frame, text="Download Location", padding="5")
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.dir_entry = ttk.Entry(dir_frame)
        self.dir_entry.insert(0, self.download_directory)
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        
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
            text="Fetch Info", 
            command=self.fetch_video_info,
            style="Accent.TButton"
        )
        self.fetch_button.pack(side=tk.RIGHT, padx=(0, 5))
        
        # Tooltip for URL entry
        create_tooltip(self.url_entry, "Enter a YouTube video URL (youtube.com or youtu.be)")
    
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
    
    def _create_quality_section(self):
        """Create the quality selection section of the UI."""
        quality_frame = ttk.LabelFrame(self.main_frame, text="Quality Options", padding="5")
        quality_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create scrollable format list
        self.format_list = ttk.Treeview(
            quality_frame,
            columns=("resolution", "ext", "filesize", "note"),
            show="headings",
            height=6
        )
        
        # Configure columns
        self.format_list.heading("resolution", text="Resolution")
        self.format_list.heading("ext", text="Format")
        self.format_list.heading("filesize", text="File Size")
        self.format_list.heading("note", text="Notes")
        
        self.format_list.column("resolution", width=100)
        self.format_list.column("ext", width=60)
        self.format_list.column("filesize", width=100)
        self.format_list.column("note", width=200)
        
        # Add scrollbar
        quality_scrollbar = ttk.Scrollbar(
            quality_frame, 
            orient=tk.VERTICAL, 
            command=self.format_list.yview
        )
        self.format_list.configure(yscrollcommand=quality_scrollbar.set)
        
        # Pack widgets
        self.format_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        quality_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind selection event
        self.format_list.bind("<<TreeviewSelect>>", self.on_format_select)
        
        # Initialize with empty message
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
        
        # Download button (using regular tk.Button instead of ttk for better styling control)
        self.download_button = tk.Button(
            control_frame, 
            text="Download", 
            command=self.download_video,
            bg="#00aa00",  # Brighter green
            fg="white",
            activebackground="#00cc00",  # Even brighter on hover
            activeforeground="white",
            padx=10,
            pady=5,
            font=("", 10, "bold"),
            relief=tk.RAISED,
            bd=3  # Thicker border
        )
        self.download_button.pack(side=tk.LEFT, padx=(5, 0))
        
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
    
    def change_directory(self):
        """Open a directory selection dialog to change the download location."""
        new_dir = filedialog.askdirectory(initialdir=self.download_directory)
        if new_dir:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, new_dir)
            self.download_directory = new_dir
    
    def fetch_video_info(self):
        """Fetch information about the video including available formats."""
        url = self.url_entry.get().strip()
        
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL.")
            return
        
        if not is_valid_youtube_url(url):
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
            return
        
        # Update UI to show fetching state
        self.fetch_button.config(state=tk.DISABLED)
        self.status_label.config(text="Fetching video information...")
        self.root.update_idletasks()
        
        # Clear current format list
        for item in self.format_list.get_children():
            self.format_list.delete(item)
        
        # Insert loading message
        self.format_list.insert("", tk.END, values=("Loading...", "", "", ""))
        
        # Define the thread function to keep it in scope
        def fetch_thread_func():
            """Thread function to fetch video info without blocking the UI."""
            try:
                # Get available formats
                formats, video_info = self.downloader.get_available_formats(url)
                
                # Store results
                self.available_formats = formats
                self.video_info = video_info
                
                # Update UI from main thread
                self.root.after(0, lambda: self.update_format_list(formats, video_info))
                self.root.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.status_label.config(text="Ready to download"))
                
            except Exception as e:
                # Handle errors
                error_msg = str(e)
                self.root.after(0, lambda: self.status_label.config(text=f"Error: {error_msg[:50]}..."))
                self.root.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))
                self.root.after(0, lambda: messagebox.showerror("Error", f"Could not fetch video info: {error_msg}"))
                
                # Clear format list and show error
                self.root.after(0, lambda: self._clear_format_list())
                self.root.after(0, lambda: self.format_list.insert("", tk.END, 
                                                                  values=("Error", "", "", error_msg[:50])))
        
        # Start the fetch thread
        fetch_thread = threading.Thread(target=fetch_thread_func)
        fetch_thread.daemon = True
        fetch_thread.start()
    
    def update_format_list(self, formats=None, video_info=None):
        """Update the format selection list with available options."""
        # If no formats provided, use the stored ones
        formats = formats or self.available_formats
        video_info = video_info or self.video_info
        
        # Clear current items
        self._clear_format_list()
        
        # If we have video info, update the info label
        if video_info:
            title = video_info.get('title', 'Unknown')
            duration = video_info.get('duration', 0)
            
            # Format duration as minutes:seconds
            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"
            
            # Update info label
            self.info_label.config(text=f"{title[:40]}... ({duration_str})" if len(title) > 40 
                                        else f"{title} ({duration_str})")
        
        # Handle case with no formats
        if not formats:
            self.format_list.insert("", tk.END, values=("No formats available", "", "", ""))
            return
        
        # Filter formats based on selected format type (mp3/mp4)
        selected_format = self.format_var.get()
        
        # For MP3, only show audio option
        if selected_format == "mp3":
            for fmt in formats:
                if fmt.get('is_audio', False):
                    self.format_list.insert("", tk.END, 
                                          values=(fmt['resolution'], fmt['ext'], 
                                                 fmt.get('filesize', 'Unknown'), 
                                                 fmt['format_note']),
                                          tags=('audio',))
            return
        
        # For MP4, show video options
        for fmt in formats:
            # Skip audio formats for video selection
            if fmt.get('is_audio', False):
                continue
                
            # Insert this format into the list
            self.format_list.insert("", tk.END, 
                                  values=(fmt.get('quality_name', fmt.get('resolution', 'Unknown')), 
                                         fmt['ext'], 
                                         fmt.get('filesize', 'Unknown'), 
                                         fmt.get('format_note', '')),
                                  tags=('format',))
        
        # Select the first item if available
        if self.format_list.get_children():
            self.format_list.selection_set(self.format_list.get_children()[0])
    
    def _clear_format_list(self):
        """Clear all items from the format list."""
        for item in self.format_list.get_children():
            self.format_list.delete(item)
    
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
        
        # Reset progress display
        self.progress['value'] = 0
        self.status_label.config(text="Starting download...")
        self.speed_label.config(text="")
        self.eta_label.config(text="")
        self.download_button.config(state=tk.DISABLED)
        self.fetch_button.config(state=tk.DISABLED)
        
        # Define the thread function to keep it in scope
        def download_thread_func():
            """Thread function to handle download without blocking the UI."""
            try:
                # Start the download
                video_title, success = self.downloader.download_video(
                    url, download_dir, selected_format
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
            self.download_button.config(bg="#00cc00", fg="white", activebackground="#00ee00", activeforeground="white")
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
            self.download_button.config(bg="#00aa00", fg="white", activebackground="#00cc00", activeforeground="white")
            self.dark_mode_button.config(bg="#0078d7", fg="white", activebackground="#1e90ff", activeforeground="white", text="Toggle Dark Mode")
        
        # Toggle the dark mode flag
        self.dark_mode = not self.dark_mode
        
        # Apply background color to main window
        self.root.configure(background=bg_color)

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
