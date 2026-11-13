"""
Creates a clean, production-ready ZIP archive of the BharatStore project
excluding virtual environments (.venv, venv, env), __pycache__, .git, and private .env
"""

import os
import zipfile
import shutil

PROJECT_DIR = r"C:\Users\ayush\.gemini\antigravity\scratch\bharatkart"
ZIP_OUTPUT_PROJECT = os.path.join(PROJECT_DIR, "BharatStore_Project.zip")
DESKTOP_DIR = r"C:\Users\ayush\Desktop"
ZIP_OUTPUT_DESKTOP = os.path.join(DESKTOP_DIR, "BharatStore_Project.zip")

EXCLUDE_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".env",
    ".git",
    ".pytest_cache",
    ".idea",
    ".vscode"
}

EXCLUDE_FILES = {
    ".env",
    "BharatStore_Project.zip",
    "bharatkart_local.db"
}

EXCLUDE_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd"
}

def create_zip():
    print(f"Creating clean project ZIP archive from: {PROJECT_DIR}")
    files_added = 0
    total_uncompressed_bytes = 0

    with zipfile.ZipFile(ZIP_OUTPUT_PROJECT, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PROJECT_DIR):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

            for file in sorted(files):
                if file in EXCLUDE_FILES:
                    continue
                _, ext = os.path.splitext(file)
                if ext.lower() in EXCLUDE_EXTS:
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, PROJECT_DIR)

                # Prepend top-level folder 'bharatstore/' in the archive for clean extraction
                arcname = os.path.join("bharatstore", rel_path)
                zipf.write(full_path, arcname)
                files_added += 1
                total_uncompressed_bytes += os.path.getsize(full_path)
                print(f" [+] Added: {arcname}")

    zip_size_kb = os.path.getsize(ZIP_OUTPUT_PROJECT) / 1024
    print("\n" + "=" * 60)
    print(f" SUCCESS: Created {ZIP_OUTPUT_PROJECT}")
    print(f" Total files: {files_added}")
    print(f" Uncompressed size: {total_uncompressed_bytes / 1024:.1f} KB")
    print(f" Compressed ZIP size: {zip_size_kb:.1f} KB")
    print("=" * 60)

    # Also copy to Desktop if accessible
    try:
        if os.path.exists(DESKTOP_DIR):
            shutil.copy2(ZIP_OUTPUT_PROJECT, ZIP_OUTPUT_DESKTOP)
            print(f" Copied ZIP to Desktop: {ZIP_OUTPUT_DESKTOP}")
    except Exception as e:
        print(f" Notice copying to Desktop: {e}")

if __name__ == "__main__":
    create_zip()
