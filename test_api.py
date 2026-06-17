"""
Quick test script to verify the API server is working correctly.

Run this after starting the server to check all endpoints are accessible.
"""

import requests

BASE_URL = "http://localhost:8000"


def test_health_check():
    """Test the health check endpoint."""
    print("Testing health check endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    print("✓ Health check passed\n")


def test_root_endpoint():
    """Test the root endpoint."""
    print("Testing root endpoint...")
    response = requests.get(f"{BASE_URL}/")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"API Name: {data['name']}")
    print(f"Version: {data['version']}")
    print(f"Status: {data['status']}")
    print(f"Available endpoints: {len(data['endpoints'])}")
    assert response.status_code == 200
    print("✓ Root endpoint passed\n")


def test_docs_available():
    """Test that API documentation is available."""
    print("Testing API documentation availability...")
    response = requests.get(f"{BASE_URL}/docs")
    print(f"Status: {response.status_code}")
    assert response.status_code == 200
    print("✓ API docs available at http://localhost:8000/docs\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Video Editor API - Quick Test")
    print("=" * 60)
    print()

    try:
        test_health_check()
        test_root_endpoint()
        test_docs_available()

        print("=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        print()
        print("The API is running correctly.")
        print("Visit http://localhost:8000/docs for interactive documentation.")

    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to the API server.")
        print("Please make sure the server is running:")
        print("  python run_server.py")
    except AssertionError as e:
        print(f"❌ Test failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()
