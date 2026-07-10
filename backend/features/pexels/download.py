"""Download stock footage from Pexels API."""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class PexelsAPIError(Exception):
    """Exception raised for Pexels API errors."""

    pass


def _get_api_key() -> str:
    """Load and return the Pexels API key from environment variables.

    Returns:
        The Pexels API key.

    Raises:
        ValueError: If the API key is not found in environment variables.
    """
    load_dotenv()
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        raise ValueError(
            "PEXELS_API_KEY not found in environment variables. "
            "Please add it to your .env file."
        )
    return api_key


def _search_videos(
    search_term: str, api_key: str, per_page: int = 15
) -> dict[str, Any]:
    """Search for videos on Pexels API.

    Args:
        search_term: The search query for stock footage.
        api_key: The Pexels API key.
        per_page: Number of results to fetch (default: 15).

    Returns:
        The API response containing video search results.

    Raises:
        PexelsAPIError: If the API request fails.
    """
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api_key}
    params = {"query": search_term, "per_page": per_page}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise PexelsAPIError(f"Failed to search Pexels API: {e}")


def _search_photos(
    search_term: str, api_key: str, per_page: int = 15
) -> dict[str, Any]:
    """Search for photos on Pexels API.

    Args:
        search_term: The search query for stock photos.
        api_key: The Pexels API key.
        per_page: Number of results to fetch (default: 15).

    Returns:
        The API response containing photo search results.

    Raises:
        PexelsAPIError: If the API request fails.
    """
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": api_key}
    params = {"query": search_term, "per_page": per_page}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise PexelsAPIError(f"Failed to search Pexels API: {e}")


def _download_video(video_url: str, output_path: Path) -> None:
    """Download a media file from a given URL.

    Args:
        video_url: The URL of the file to download.
        output_path: The path where the file should be saved.

    Raises:
        PexelsAPIError: If the download fails.
    """
    try:
        response = requests.get(video_url, stream=True, timeout=60)
        response.raise_for_status()

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"File downloaded successfully to {output_path}")
    except requests.exceptions.RequestException as e:
        raise PexelsAPIError(f"Failed to download video: {e}")


def download_stock_footage(
    search_term: str, output_dir: str = "downloads", quality: str = "hd"
) -> str:
    """Download a random stock footage video from Pexels based on search term.

    Args:
        search_term: The search query for stock footage (e.g., "ocean waves").
        output_dir: Directory where the video will be saved (default: "downloads").
        quality: Video quality preference - "hd", "sd", or "original" (default: "hd").

    Returns:
        The path to the downloaded video file.

    Raises:
        PexelsAPIError: If the API request or download fails.
        ValueError: If no videos are found for the search term or invalid quality.
    """
    valid_qualities = {"hd", "sd", "original"}
    if quality not in valid_qualities:
        raise ValueError(
            f"Invalid quality '{quality}'. Must be one of: {valid_qualities}"
        )

    api_key = _get_api_key()
    logger.info(f"Searching for videos with term: '{search_term}'")

    # Search for videos
    search_results = _search_videos(search_term, api_key)

    videos = search_results.get("videos", [])
    if not videos:
        raise ValueError(f"No videos found for search term: '{search_term}'")

    # Select a random video from the results
    selected_video = random.choice(videos)
    video_id = selected_video.get("id")
    video_files = selected_video.get("video_files", [])

    if not video_files:
        raise ValueError(f"No video files found for selected video (ID: {video_id})")

    # Filter by quality and select the best match
    quality_map = {"hd": "hd", "sd": "sd", "original": None}
    preferred_quality = quality_map[quality]

    # Try to find a video file matching the preferred quality
    selected_file = None
    if preferred_quality:
        for video_file in video_files:
            if video_file.get("quality") == preferred_quality:
                selected_file = video_file
                break

    # If no exact quality match, use the first available file
    if not selected_file:
        selected_file = video_files[0]
        logger.warning(
            f"Requested quality '{quality}' not available. "
            f"Using '{selected_file.get('quality')}' instead."
        )

    video_url = selected_file.get("link")
    if not video_url:
        raise ValueError("Video download link not found")

    # Create output filename
    output_path = (
        Path(output_dir) / f"pexels_{search_term.replace(' ', '_')}_{video_id}.mp4"
    )

    logger.info(
        f"Downloading video (ID: {video_id}, Quality: {selected_file.get('quality')})"
    )

    # Download the video
    _download_video(video_url, output_path)

    return str(output_path)


def download_stock_photo(
    search_term: str, output_dir: str = "downloads", size: str = "large2x"
) -> str:
    """Download a random stock photo from Pexels based on search term.

    Args:
        search_term: The search query for stock photos (e.g., "mountain lake").
        output_dir: Directory where the photo will be saved (default: "downloads").
        size: Photo size preference - "original", "large2x", "large", or
            "medium" (default: "large2x", ~1880px wide, plenty for 1080p video).

    Returns:
        The path to the downloaded photo file.

    Raises:
        PexelsAPIError: If the API request or download fails.
        ValueError: If no photos are found for the search term or invalid size.
    """
    valid_sizes = {"original", "large2x", "large", "medium"}
    if size not in valid_sizes:
        raise ValueError(f"Invalid size '{size}'. Must be one of: {valid_sizes}")

    api_key = _get_api_key()
    logger.info(f"Searching for photos with term: '{search_term}'")

    search_results = _search_photos(search_term, api_key)

    photos = search_results.get("photos", [])
    if not photos:
        raise ValueError(f"No photos found for search term: '{search_term}'")

    selected_photo = random.choice(photos)
    photo_id = selected_photo.get("id")
    src = selected_photo.get("src", {})

    photo_url = src.get(size) or src.get("original")
    if not photo_url:
        raise ValueError(f"Photo download link not found (ID: {photo_id})")

    # Keep the extension the CDN serves (Pexels photos are typically .jpeg).
    extension = Path(urlparse(photo_url).path).suffix or ".jpg"
    output_path = (
        Path(output_dir)
        / f"pexels_{search_term.replace(' ', '_')}_{photo_id}{extension}"
    )

    logger.info(f"Downloading photo (ID: {photo_id}, Size: {size})")

    _download_video(photo_url, output_path)

    return str(output_path)


def download_stock_media(
    search_term: str, media_type: str = "video", output_dir: str = "downloads"
) -> str:
    """Download stock B-roll of the requested media type from Pexels.

    Args:
        search_term: The search query for stock media.
        media_type: "video" for a stock clip, "image" for a still photo.
        output_dir: Directory where the file will be saved (default: "downloads").

    Returns:
        The path to the downloaded file.

    Raises:
        PexelsAPIError: If the API request or download fails.
        ValueError: If the media type is unknown or no results are found.
    """
    if media_type == "video":
        return download_stock_footage(search_term, output_dir=output_dir)
    if media_type == "image":
        return download_stock_photo(search_term, output_dir=output_dir)
    raise ValueError(f"Invalid media_type '{media_type}'. Must be 'video' or 'image'")
