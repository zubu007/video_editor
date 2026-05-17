# AGENTS.md

This document provides a set of guidelines for agentic coding agents operating in this repository. It covers everything from project setup to code style, ensuring consistency and quality in all contributions.

## 1. Project Overview

This project is a simple video editing tool designed to process podcast videos. The primary goal is to automate the removal of filler words like "ums" and "ahs" from video content. The core logic resides in `main.py`, which utilizes the `whisper` library for speech-to-text transcription.

This document is your primary source of truth for repository-specific conventions and commands. Please adhere to these guidelines strictly.

## 2. Getting Started

### 2.1. Environment Setup

This project uses Python `3.11` or higher. It is recommended to use a virtual environment to manage dependencies.

```bash
# Create a virtual environment
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate
```

### 2.2. Dependency Installation

The project's dependencies are managed by `uv`, a fast Python package installer. All dependencies are listed in `pyproject.toml`.

To install the required packages, run:

```bash
uv pip install -r requirements.txt
```
*Note: As there is no requirements.txt, you can install the dependencies from `pyproject.toml` directly*
```bash
uv pip install "whisper>=1.1.10"
```

## 3. Development Workflow

### 3.1. Running the Application

The main entry point of the application is `main.py`. To run the script, use the following command:

```bash
python main.py
```

### 3.2. Linting and Formatting

This project uses `ruff` for linting and `black` for code formatting. These tools help maintain a consistent and readable codebase.

**Linting:**

To check for linting errors, run:

```bash
ruff check .
```

To automatically fix linting errors, run:

```bash
ruff check . --fix
```

**Formatting:**

To format the entire codebase, run:

```bash
black .
```

To check if the codebase is formatted correctly, run:

```bash
black --check .
```

### 3.3. Testing

This project uses `pytest` for testing. Test files should be placed in a `tests/` directory and follow the `test_*.py` naming convention.

**Running all tests:**

```bash
pytest
```

**Running a single test file:**

```bash
pytest tests/test_example.py
```

**Running a specific test function:**

```bash
pytest tests/test_example.py::test_function_name
```

*Note: Since there is no `tests` directory yet, you should create it when adding the first test.*

## 4. Code Style Guidelines

### 4.1. General Principles

- **Clarity and Simplicity:** Write code that is easy to read and understand.
- **Consistency:** Adhere to the existing code style and conventions.
- **Modularity:** Keep functions and classes focused on a single responsibility.

### 4.2. Naming Conventions

- **Variables and Functions:** Use `snake_case` (e.g., `my_variable`, `calculate_total`).
- **Classes:** Use `PascalCase` (e.g., `VideoEditor`, `TranscriptParser`).
- **Constants:** Use `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`, `DEFAULT_TIMEOUT`).

### 4.3. Imports

- **Order:** Group imports in the following order:
  1. Standard library imports (e.g., `os`, `sys`).
  2. Third-party library imports (e.g., `whisper`).
  3. Local application imports.
- **Formatting:** Use `isort` or a similar tool to automatically format imports if needed, but `ruff` can also handle this.

### 4.4. Typing

- **Type Hinting:** Use type hints for all function signatures and variable declarations. This project uses Python's `typing` module.
- **Clarity:** Ensure type hints are precise and clear. Use `from __future__ import annotations` if needed.

### 4.5. Docstrings and Comments

- **Docstrings:** Use Google-style docstrings for all modules, classes, and functions. A one-line summary is often sufficient for simple functions.
- **Comments:** Use comments to explain *why* something is done, not *what* is done. Avoid obvious comments.

### 4.6. Error Handling

- **Exceptions:** Use specific exception types whenever possible (e.g., `ValueError` instead of a generic `Exception`).
- **Error Messages:** Write clear and informative error messages that can help with debugging.
- **Context Management:** Use `try...except...finally` blocks or context managers (`with` statements) for resource management.

### 4.7. Logging

- A structured logging setup is preferred. Use Python's `logging` module.
- Configure log levels appropriately (e.g., `INFO`, `DEBUG`, `ERROR`).

By following these guidelines, you will help maintain a high-quality and consistent codebase. Thank you for your contributions!
