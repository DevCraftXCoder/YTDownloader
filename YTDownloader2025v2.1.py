# Import required libraries
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import yt_dlp
import os
import shutil
import logging
import json
import re
import threading
import unicodedata
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('download.log')
    ]
)

# Filter out verbose messages
logging.getLogger('yt_dlp').setLevel(logging.WARNING)
for logger_name in ['yt_dlp', 'ffmpeg']:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.ERROR)

# Set default download directory
DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

def download_video_with_progress(user_input, download_dir, output_format, progress_callback):
    """Downloads a YouTube video with progress tracking."""
    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            if total_bytes and downloaded_bytes:
                progress = int((downloaded_bytes / total_bytes) * 100)
            else:
                progress = 0
            progress_callback(progress)
        elif d['status'] == 'finished':
            progress_callback(95)

    filename_template = os.path.join(download_dir, '%(title)s.%(ext)s')
    
    ydl_opts = {
        'noplaylist': True,
        'progress_hooks': [progress_hook],
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
        'writethumbnail': False,
        'verbose': False,
    }
    
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        ydl_opts['ffmpeg_location'] = ffmpeg_path
    
    if output_format == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'final_ext': 'mp3',
        })
    elif output_format == 'mp4':
        ydl_opts.update({
            # Updated format selection to force highest quality MP4
            'format': '(bestvideo[ext=mp4][height>=1080]+bestaudio[ext=m4a])/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'recode-video': 'mp4',
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(user_input, download=False)
            video_title = info.get('title', 'Unknown title')
            logging.info(f"Starting download: {video_title}")
            
            try:
                ydl.download([user_input])
            except Exception as e:
                if output_format == 'mp4':
                    logging.warning("First attempt failed, trying fallback format...")
                    # Updated fallback format
                    ydl_opts.update({
                        'format': 'best[ext=mp4]/best',
                        'merge_output_format': 'mp4',
                        'recode-video': 'mp4',
                    })
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_fallback:
                        ydl_fallback.download([user_input])
                else:
                    raise e
            
        logging.info(f"Download completed: {video_title}")
        progress_callback(100)
        
        # Clean up any temporary files
        try:
            for file in os.listdir(download_dir):
                if file.endswith(('.part', '.temp', '.f140.mp4', '.f137.mp4', '.f401.mp4', '.m4a', '.webm')):
                    try:
                        os.remove(os.path.join(download_dir, file))
                    except:
                        pass
        except Exception as e:
            logging.warning(f"Cleanup error: {e}")
            
    except Exception as e:
        logging.error(f"Download error: {e}")
        raise
    
    """Downloads a YouTube video with progress tracking."""
    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            if total_bytes and downloaded_bytes:
                progress = int((downloaded_bytes / total_bytes) * 100)
            else:
                progress = 0
            progress_callback(progress)
        elif d['status'] == 'finished':
            progress_callback(95)

    filename_template = os.path.join(download_dir, '%(title)s.%(ext)s')
    
    ydl_opts = {
        'noplaylist': True,
        'progress_hooks': [progress_hook],
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
        'writethumbnail': False,
        'verbose': False,
    }
    
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        ydl_opts['ffmpeg_location'] = ffmpeg_path
    
    if output_format == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'final_ext': 'mp3',
        })
    elif output_format == 'mp4':
        ydl_opts.update({
            # Updated format selection to force highest quality
            'format': 'bestvideo*+bestaudio/best',
            'merge_output_format': 'mp4',
            'prefer_ffmpeg': True,
            'keepvideo': False,
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(user_input, download=False)
            video_title = info.get('title', 'Unknown title')
            logging.info(f"Starting download: {video_title}")
            
            try:
                ydl.download([user_input])
            except Exception as e:
                if output_format == 'mp4':
                    logging.warning("First attempt failed, trying fallback format...")
                    # Updated fallback format
                    ydl_opts.update({
                        'format': 'best',
                        'merge_output_format': 'mp4',
                    })
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_fallback:
                        ydl_fallback.download([user_input])
                else:
                    raise e
            
        logging.info(f"Download completed: {video_title}")
        progress_callback(100)
        
        # Clean up any temporary files
        try:
            for file in os.listdir(download_dir):
                if file.endswith(('.part', '.temp', '.f140.mp4', '.f137.mp4', '.f401.mp4', '.m4a')):
                    try:
                        os.remove(os.path.join(download_dir, file))
                    except:
                        pass
        except Exception as e:
            logging.warning(f"Cleanup error: {e}")
            
    except Exception as e:
        logging.error(f"Download error: {e}")
        raise

    """Downloads a YouTube video with progress tracking."""
    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            if total_bytes and downloaded_bytes:
                progress = int((downloaded_bytes / total_bytes) * 100)
            else:
                progress = 0
            progress_callback(progress)
        elif d['status'] == 'finished':
            progress_callback(95)

    filename_template = os.path.join(download_dir, '%(title)s.%(ext)s')
    
    ydl_opts = {
        'noplaylist': True,
        'progress_hooks': [progress_hook],
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
        'writethumbnail': False,
        'verbose': False,
        'postprocessor_args': [
            '-loglevel', 'quiet',
            '-hide_banner',
            '-nostats'
        ],
        'external_downloader_args': ['-loglevel', 'quiet'],
    }
    
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        ydl_opts['ffmpeg_location'] = ffmpeg_path
    
    if output_format == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'final_ext': 'mp3',
        })
    elif output_format == 'mp4':
        ydl_opts.update({
            # Updated format selection for highest quality MP4
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[height>=1080][ext=mp4]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'final_ext': 'mp4',
            'postprocessor_args': [
                '-loglevel', 'quiet',
                '-hide_banner',
                '-nostats'
            ],
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(user_input, download=False)
            video_title = info.get('title', 'Unknown title')
            logging.info(f"Starting download: {video_title}")
            
            try:
                ydl.download([user_input])
            except Exception as e:
                if output_format == 'mp4':
                    logging.warning("First attempt failed, trying fallback format...")
                    # Updated fallback format to still try for high quality
                    ydl_opts.update({
                        'format': 'best[height>=720][ext=mp4]/best[ext=mp4]/best',
                        'merge_output_format': 'mp4',
                    })
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_fallback:
                        ydl_fallback.download([user_input])
                else:
                    raise e
            
        logging.info(f"Download completed: {video_title}")
        progress_callback(100)
        
        # Clean up any temporary files
        try:
            for file in os.listdir(download_dir):
                if file.endswith(('.part', '.temp', '.f140.mp4', '.f137.mp4', '.f401.mp4', '.m4a')):
                    try:
                        os.remove(os.path.join(download_dir, file))
                    except:
                        pass
        except Exception as e:
            logging.warning(f"Cleanup error: {e}")
            
    except Exception as e:
        logging.error(f"Download error: {e}")
        raise

def is_ffmpeg_installed():
    """Check if FFmpeg is installed."""
    return shutil.which("ffmpeg") is not None

def validate_directory(directory):
    """Validate if directory exists and is writable."""
    return os.path.isdir(directory) and os.access(directory, os.W_OK)

def is_valid_youtube_url(url):
    """Validate YouTube URL."""
    youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'
    return bool(re.match(youtube_regex, url))

class DownloadManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("500x500")
        self.download_directory = DEFAULT_DOWNLOAD_DIR
        self.dark_mode = False
        
        self.dir_label = tk.Label(root, text="Download Directory:")
        self.dir_label.pack(pady=5)
        
        self.dir_entry = tk.Entry(root, width=50)
        self.dir_entry.insert(0, self.download_directory)
        self.dir_entry.pack(pady=5)
        
        self.change_dir_button = tk.Button(root, text="Change Directory", command=self.change_directory)
        self.change_dir_button.pack(pady=5)
        
        self.input_label = tk.Label(root, text="Enter YouTube URL:")
        self.input_label.pack(pady=5)
        
        self.input_entry = tk.Entry(root, width=50)
        self.input_entry.pack(pady=5)
        
        self.format_label = tk.Label(root, text="Choose Output Format:")
        self.format_label.pack(pady=5)
        
        self.format_var = tk.StringVar(value="mp4")
        
        self.format_frame = tk.Frame(root)
        self.format_frame.pack()
        
        self.mp4_button = tk.Radiobutton(self.format_frame, text="MP4", variable=self.format_var, value="mp4")
        self.mp4_button.pack(side="left")
        
        self.mp3_button = tk.Radiobutton(self.format_frame, text="MP3", variable=self.format_var, value="mp3")
        self.mp3_button.pack(side="left")
        
        self.progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=10)
        
        self.download_button = tk.Button(root, text="Download", command=self.download_video)
        self.download_button.pack(pady=10)
        
        self.dark_mode_button = tk.Button(root, text="Toggle Dark Mode", command=self.toggle_dark_mode)
        self.dark_mode_button.pack(pady=10)
        
        self.status_label = tk.Label(root, text="Ready")
        self.status_label.pack(pady=5)
        
        if not is_ffmpeg_installed():
            messagebox.showwarning("FFmpeg Not Found", 
                                 "FFmpeg is not found on your system. This application requires FFmpeg for conversion. "
                                 "Please install FFmpeg and restart the application.")

    def change_directory(self):
        new_dir = filedialog.askdirectory(initialdir=self.download_directory)
        if new_dir:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, new_dir)
            self.download_directory = new_dir

    def update_progress(self, value):
        self.progress['value'] = value
        status_text = "Converting..." if value >= 95 and value < 100 else f"Downloading: {value}%"
        self.status_label.config(text=status_text)
        self.root.update_idletasks()

    def download_video(self):
        user_input = self.input_entry.get().strip()
        
        if not user_input:
            messagebox.showerror("Error", "Please enter a YouTube URL.")
            return
            
        if not is_valid_youtube_url(user_input):
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
            return
        
        download_dir = self.dir_entry.get()
        if not validate_directory(download_dir):
            messagebox.showerror("Invalid Directory", "The download directory does not exist or is not writable.")
            return
            
        if not is_ffmpeg_installed():
            messagebox.showerror("FFmpeg Missing", "FFmpeg is required but not found on your system. Please install FFmpeg and try again.")
            return
        
        output_format = self.format_var.get()
        
        self.progress['value'] = 0
        self.status_label.config(text="Starting download...")
        self.download_button.config(state=tk.DISABLED)
        
        def download_thread_func():
            try:
                download_video_with_progress(user_input, download_dir, output_format, self.update_progress)
                self.root.after(0, lambda: self.status_label.config(text="Download completed!"))
                self.root.after(0, lambda: messagebox.showinfo("Success", "The video has been downloaded successfully."))
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda: self.status_label.config(text=f"Error: {error_msg[:50]}..."))
                self.root.after(0, lambda: messagebox.showerror("Download Failed", f"An error occurred: {error_msg}"))
            finally:
                self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
        
        download_thread = threading.Thread(target=download_thread_func)
        download_thread.daemon = True
        download_thread.start()

    def toggle_dark_mode(self):
        bg_color = "#2E2E2E" if not self.dark_mode else "white"
        fg_color = "white" if not self.dark_mode else "black"
        entry_bg = "#3E3E3E" if not self.dark_mode else "white"
        entry_fg = "white" if not self.dark_mode else "black"
        
        self.root.configure(bg=bg_color)
        
        for widget in self.root.winfo_children():
            widget_type = widget.winfo_class()
            if widget_type in ("Label", "Button", "Frame", "Radiobutton"):
                try:
                    widget.configure(bg=bg_color, fg=fg_color)
                except tk.TclError:
                    pass
            elif widget_type == "Entry":
                try:
                    widget.configure(bg=entry_bg, fg=entry_fg)
                except tk.TclError:
                    pass
        
        self.dark_mode = not self.dark_mode

if __name__ == "__main__":
    root = tk.Tk()
    app = DownloadManagerApp(root)
    root.mainloop()