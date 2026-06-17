"""Example script demonstrating Pexels stock footage download."""

from backend.features.pexels import download_stock_footage


def main() -> None:
    """Download stock footage from Pexels API."""
    # Example 1: Download a random ocean video in HD quality
    print("Downloading ocean footage...")
    video_path = download_stock_footage("ocean waves", quality="hd")
    print(f"✓ Downloaded video to: {video_path}")

    # Example 2: Download a random nature video in SD quality
    print("\nDownloading nature footage...")
    video_path = download_stock_footage(
        "forest nature", quality="sd", output_dir="downloads/nature"
    )
    print(f"✓ Downloaded video to: {video_path}")

    # Example 3: Download a random city video
    print("\nDownloading city footage...")
    video_path = download_stock_footage("city nightlife", output_dir="downloads/city")
    print(f"✓ Downloaded video to: {video_path}")


if __name__ == "__main__":
    main()
