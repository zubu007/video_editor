"""Download stock footage from Pexels API."""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any

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


def _download_video(video_url: str, output_path: Path) -> None:
    """Download a video from a given URL.

    Args:
        video_url: The URL of the video to download.
        output_path: The path where the video should be saved.

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

        logger.info(f"Video downloaded successfully to {output_path}")
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
