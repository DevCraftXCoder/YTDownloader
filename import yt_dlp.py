import yt_dlp  # YouTube downloader
import os      # File system operations
import subprocess  # Running system commands
import re      # Regular expressions for URL validation
import sys     # Handling script exit
import shutil  # Checking system paths
import logging  # For logging errors
import json    # To store and load config
from tqdm import tqdm  # Progress bar
import time

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

# Function to clean up partial or failed downloads
def cleanup_partial_downloads(directory):
    """Deletes any temporary or incomplete downloads in the given directory."""
    for file in os.listdir(directory):
        if file.endswith(".part") or file.endswith(".ytdl"):
            os.remove(os.path.join(directory, file))

# Function to manually convert a file using FFmpeg
def convert_video(input_file, output_format):
    """Uses FFmpeg to convert a video to MP4, MOV, or MP3."""
    output_file = os.path.splitext(input_file)[0] + f".{output_format}"

    try:
        # Adjust FFmpeg conversion based on output format (MP3 for audio)
        if output_format == 'mp3':
            # Convert video/audio to MP3 (audio-only conversion)
            result = subprocess.run([
                "ffmpeg", "-y", "-i", input_file,
                "-vn", "-acodec", "libmp3lame", "-ab", "192k", output_file
            ], check=True, capture_output=True, text=True)
        else:
            # Standard video conversion (e.g., MP4 or MOV)
            result = subprocess.run([
                "ffmpeg", "-y", "-i", input_file,
                "-c:v", "copy", "-c:a", "aac", "-loglevel", "error", output_file
            ], check=True, capture_output=True, text=True)
        
        if result.stdout:
            logging.info(result.stdout)  # Log FFmpeg output
        return output_file
    except subprocess.CalledProcessError as e:
        logging.error(f"Error: FFmpeg conversion failed with error: {e.stderr}")
        print(f"Conversion failed: {e.stderr}")
        return None

# Function to download a video and show a progress bar
def download_video_with_progress(user_input, download_dir, output_format="mp4"):
    """Downloads a YouTube video and converts it to MP4, MOV, or MP3 with a progress bar."""
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

# Function that handles the progress bar updates
def download_progress_hook(d):
    """Progress hook for yt-dlp to show a progress bar"""
    if d['status'] == 'downloading':
        total_size = d.get('total_bytes') or d.get('total_bytes_estimate')
        if total_size:
            current = d['downloaded_bytes']
            percent = current / total_size * 100
            bar_length = 40  # Length of the progress bar
            filled_length = int(bar_length * percent // 100)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            print(f"\r[{'white'}] {bar} {percent:.2f}% ", end='', flush=True)

    elif d['status'] == 'finished':
        print(f"\nDownload finished: {d['filename']}")

# Run script
if __name__ == "__main__":
    # Check dependencies
    if not is_ffmpeg_installed():
        logging.error("FFmpeg is not installed. Please install it.")
        sys.exit(1)  # Exit the script if FFmpeg is not found

    # Load the existing configuration for the download directory
    download_directory = load_config()

    # Ask the user if they want to go to the hidden menu
    if input("Do you want to go to the hidden menu? (y/n): ").strip().lower() == "y":
        hidden_menu()

    # Ask the user for input (search term or URL)
    user_input = input("Enter search term or video URL: ").strip()

    # Ask the user to choose a file format (MP4, MOV, or MP3)
    output_format = input("Choose output format (mp4/mov/mp3): ").strip().lower()
    if output_format not in ["mp4", "mov", "mp3"]:
        logging.warning("Invalid format. Defaulting to MP4.")
        output_format = "mp4"

    # Call the function to download and convert the video
    download_video_with_progress(user_input, download_directory, output_format)
