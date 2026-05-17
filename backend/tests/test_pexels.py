"""Tests for the Pexels stock footage download feature."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.features.pexels.download import (
    PexelsAPIError,
    _download_video,
    _get_api_key,
    _search_videos,
    download_stock_footage,
)


class TestGetAPIKey:
    """Tests for _get_api_key function."""

    @patch("features.pexels.download.load_dotenv")
    @patch.dict(os.environ, {"PEXELS_API_KEY": "test_key_123"})
    def test_get_api_key_success(self, mock_load_dotenv: MagicMock) -> None:
        """Test successful retrieval of API key."""
        result = _get_api_key()
        assert result == "test_key_123"
        mock_load_dotenv.assert_called_once()

    @patch("features.pexels.download.load_dotenv")
    @patch.dict(os.environ, {}, clear=True)
    def test_get_api_key_missing(self, mock_load_dotenv: MagicMock) -> None:
        """Test error when API key is missing."""
        with pytest.raises(ValueError, match="PEXELS_API_KEY not found"):
            _get_api_key()


class TestSearchVideos:
    """Tests for _search_videos function."""

    @patch("features.pexels.download.requests.get")
    def test_search_videos_success(self, mock_get: MagicMock) -> None:
        """Test successful video search."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "videos": [{"id": 1, "url": "https://example.com/video1"}]
        }
        mock_get.return_value = mock_response

        result = _search_videos("ocean", "test_key")

        assert "videos" in result
        assert len(result["videos"]) == 1
        mock_get.assert_called_once()

    @patch("features.pexels.download.requests.get")
    def test_search_videos_api_error(self, mock_get: MagicMock) -> None:
        """Test API error handling during search."""
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("API Error")

        with pytest.raises(PexelsAPIError, match="Failed to search Pexels API"):
            _search_videos("ocean", "test_key")


class TestDownloadVideo:
    """Tests for _download_video function."""

    @patch("features.pexels.download.requests.get")
    def test_download_video_success(
        self, mock_get: MagicMock, tmp_path: Path
    ) -> None:
        """Test successful video download."""
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_get.return_value = mock_response

        output_path = tmp_path / "test_video.mp4"
        _download_video("https://example.com/video.mp4", output_path)

        assert output_path.exists()
        with open(output_path, "rb") as f:
            content = f.read()
        assert content == b"chunk1chunk2"

    @patch("features.pexels.download.requests.get")
    def test_download_video_error(self, mock_get: MagicMock, tmp_path: Path) -> None:
        """Test error handling during video download."""
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("Download Error")

        output_path = tmp_path / "test_video.mp4"
        with pytest.raises(PexelsAPIError, match="Failed to download video"):
            _download_video("https://example.com/video.mp4", output_path)


class TestDownloadStockFootage:
    """Tests for download_stock_footage function."""

    @patch("features.pexels.download._download_video")
    @patch("features.pexels.download._search_videos")
    @patch("features.pexels.download._get_api_key")
    def test_download_stock_footage_success(
        self,
        mock_get_api_key: MagicMock,
        mock_search_videos: MagicMock,
        mock_download_video: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful stock footage download."""
        mock_get_api_key.return_value = "test_key"
        mock_search_videos.return_value = {
            "videos": [
                {
                    "id": 12345,
                    "video_files": [
                        {"quality": "hd", "link": "https://example.com/video.mp4"}
                    ],
                }
            ]
        }

        result = download_stock_footage("ocean", output_dir=str(tmp_path))

        assert "pexels_ocean_12345.mp4" in result
        mock_download_video.assert_called_once()

    @patch("features.pexels.download._search_videos")
    @patch("features.pexels.download._get_api_key")
    def test_download_stock_footage_no_videos(
        self, mock_get_api_key: MagicMock, mock_search_videos: MagicMock
    ) -> None:
        """Test error when no videos are found."""
        mock_get_api_key.return_value = "test_key"
        mock_search_videos.return_value = {"videos": []}

        with pytest.raises(ValueError, match="No videos found for search term"):
            download_stock_footage("nonexistent_term")

    @patch("features.pexels.download._get_api_key")
    def test_download_stock_footage_invalid_quality(
        self, mock_get_api_key: MagicMock
    ) -> None:
        """Test error with invalid quality parameter."""
        mock_get_api_key.return_value = "test_key"

        with pytest.raises(ValueError, match="Invalid quality"):
            download_stock_footage("ocean", quality="ultra_hd")

    @patch("features.pexels.download._download_video")
    @patch("features.pexels.download._search_videos")
    @patch("features.pexels.download._get_api_key")
    def test_download_stock_footage_quality_fallback(
        self,
        mock_get_api_key: MagicMock,
        mock_search_videos: MagicMock,
        mock_download_video: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test quality fallback when preferred quality is not available."""
        mock_get_api_key.return_value = "test_key"
        mock_search_videos.return_value = {
            "videos": [
                {
                    "id": 12345,
                    "video_files": [
                        {"quality": "sd", "link": "https://example.com/video.mp4"}
                    ],
                }
            ]
        }

        result = download_stock_footage("ocean", output_dir=str(tmp_path), quality="hd")

        assert "pexels_ocean_12345.mp4" in result
        mock_download_video.assert_called_once()
