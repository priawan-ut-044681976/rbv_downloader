import requests
import os
import time
import random
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from enum import Enum
from mimetypes import guess_extension

# ============================================================================
# GLOBAL CONFIGURATION
# ============================================================================

class Config:
    """Global configuration"""
    BASE_URL = "https://pustaka.ut.ac.id/reader/services/view.php"
    REFERER_BASE = "https://pustaka.ut.ac.id/reader/index.php"
    TIMEOUT = 30
    MIN_DELAY = 10
    MAX_DELAY = 20
    MANIFEST_SUFFIX = ".manifest.json"
    DOC_PADDING = 2  # M01, M02, etc.
    PAGE_PADDING = 3  # 001, 002, etc.
    IMAGE_FORMAT = "jpg"  # Expected format
    
    # Cookies - Update these with your actual values
    COOKIES = {
        'PHPSESSID': 'sq4rafd8097t7tq5hhjvv8u0cq',
        '_ga_5B5HVHB1BJ': 'GS2.1.s1760865847$o1$g0$t1760867113$j60$l0$h0',
        '_ga_D6HCMSG40W': 'GS2.1.s1760865848$o1$g0$t1760865848$j60$l0$h0',
        '_ga_WNHP75XYCP': 'GS2.1.s1760865851$o1$g1$t1760867145$j60$l0$h0',
        '_gcl_au': '1.1.2142973689.1760865852',
        '_fbp': 'fb.2.1760865854237.990831187740255650',
        '_ga': 'GA1.3.937831928.1760865848',
        '_gid': 'GA1.3.591205392.1760865857',
        '_ga_Q3NS1R2SYD': 'GS2.1.s1760865856$o1$g0$t1760866102$j60$l0$h0'
    }


class DownloadStatus(Enum):
    """Download status enumeration"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    RESUMED = "resumed"
    FORMAT_MISMATCH = "format_mismatch"


# ============================================================================
# MANIFEST MANAGEMENT
# ============================================================================

class ManifestManager:
    """Manage manifest file for download tracking and resume"""
    
    def __init__(self, module_name):
        self.module_name = module_name
        self.manifest_path = Path(module_name) / f"{module_name}{Config.MANIFEST_SUFFIX}"
        self.manifest_data = None
    
    def create_manifest(self, docs_pages):
        """Create a new manifest file"""
        self.manifest_data = {
            "metadata": {
                "module_name": self.module_name,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "num_docs": len(docs_pages),
                "total_pages": sum(docs_pages.values()),
                "docs_info": {
                    f"M{i}": docs_pages[f"M{i}"]
                    for i in range(1, len(docs_pages) + 1)
                }
            },
            "files": {}
        }
        
        # Initialize file entries
        for doc_num in range(1, len(docs_pages) + 1):
            doc_original = f"M{doc_num}"
            doc_padded = f"M{doc_num:0{Config.DOC_PADDING}d}"
            num_pages = docs_pages[doc_original]
            
            for page in range(1, num_pages + 1):
                page_padded = f"{page:0{Config.PAGE_PADDING}d}"
                filename = self._get_filename(doc_padded, page_padded)
                
                self.manifest_data["files"][filename] = {
                    "submodule": str(doc_num),
                    "pagenumber": str(page),
                    "status": DownloadStatus.PENDING.value,
                    "size": 0,
                    "downloaded_size": 0,
                    "progress_percent": 0,
                    "attempts": 0,
                    "last_error": None,
                    "actual_format": None,
                    "completed_at": None
                }
        
        self._save_manifest()
        return self.manifest_data
    
    def load_manifest(self):
        """Load manifest file if exists"""
        if not self.manifest_path.exists():
            return None
        
        try:
            with open(self.manifest_path, 'r') as f:
                self.manifest_data = json.load(f)
            return self.manifest_data
        except Exception as e:
            print(f"Error loading manifest: {e}")
            return None
    
    def _save_manifest(self):
        """Save manifest to file"""
        self.manifest_data["metadata"]["updated_at"] = datetime.now().isoformat()
        Path(self.module_name).mkdir(exist_ok=True)
        
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest_data, f, indent=2)
    
    def update_file_status(self, filename, status, size=None, error=None, actual_format=None):
        """Update file download status"""
        if filename in self.manifest_data["files"]:
            self.manifest_data["files"][filename]["status"] = status.value
            self.manifest_data["files"][filename]["attempts"] += 1
            
            if size is not None:
                self.manifest_data["files"][filename]["size"] = size
                self.manifest_data["files"][filename]["downloaded_size"] = size
                self.manifest_data["files"][filename]["progress_percent"] = 100
            
            if error:
                self.manifest_data["files"][filename]["last_error"] = error
            
            if actual_format:
                self.manifest_data["files"][filename]["actual_format"] = actual_format
            
            if status == DownloadStatus.COMPLETED:
                self.manifest_data["files"][filename]["completed_at"] = datetime.now().isoformat()
            
            self._save_manifest()
    
    def get_download_progress(self):
        """Get overall download progress"""
        if not self.manifest_data:
            return 0
        
        files = self.manifest_data["files"]
        completed = sum(
            1 for f in files.values() 
            if f["status"] == DownloadStatus.COMPLETED.value
        )
        total = len(files)
        
        return (completed / total * 100) if total > 0 else 0
    
    def get_pending_files(self):
        """Get list of pending, failed, or format_mismatch files"""
        if not self.manifest_data:
            return []
        
        return [
            fname for fname, info in self.manifest_data["files"].items()
            if info["status"] in [
                DownloadStatus.PENDING.value,
                DownloadStatus.FAILED.value,
                DownloadStatus.FORMAT_MISMATCH.value
            ]
        ]
    
    def is_download_complete(self):
        """Check if all files are downloaded"""
        if not self.manifest_data:
            return False
        
        files = self.manifest_data["files"]
        return all(f["status"] == DownloadStatus.COMPLETED.value for f in files.values())
    
    def verify_files(self, output_dir):
        """Verify if all files exist and update manifest accordingly"""
        if not self.manifest_data:
            return False
        
        missing_files = []
        format_mismatches = []
        
        for filename, file_info in self.manifest_data["files"].items():
            filepath = output_dir / filename
            
            if not filepath.exists():
                missing_files.append(filename)
                self.manifest_data["files"][filename]["status"] = DownloadStatus.PENDING.value
            else:
                file_size = filepath.stat().st_size
                
                # Check file format
                actual_format = self._get_file_format(filepath)
                expected_format = Config.IMAGE_FORMAT
                
                if actual_format and actual_format.lower() != expected_format.lower():
                    format_mismatches.append((filename, expected_format, actual_format))
                    self.manifest_data["files"][filename]["status"] = DownloadStatus.FORMAT_MISMATCH.value
                    self.manifest_data["files"][filename]["actual_format"] = actual_format
                else:
                    if self.manifest_data["files"][filename]["size"] == 0:
                        self.manifest_data["files"][filename]["size"] = file_size
                        self.manifest_data["files"][filename]["downloaded_size"] = file_size
                        self.manifest_data["files"][filename]["progress_percent"] = 100
                        self.manifest_data["files"][filename]["status"] = DownloadStatus.COMPLETED.value
        
        if missing_files or format_mismatches:
            self._save_manifest()
        
        return len(missing_files) == 0 and len(format_mismatches) == 0
    
    @staticmethod
    def _get_file_format(filepath):
        """Detect actual file format by reading magic bytes"""
        try:
            with open(filepath, 'rb') as f:
                magic = f.read(12)
                
                # JPEG signatures
                if magic[:2] == b'\xff\xd8':
                    return 'jpg'
                # PNG signature
                elif magic[:8] == b'\x89PNG\r\n\x1a\n':
                    return 'png'
                # GIF signature
                elif magic[:6] in [b'GIF87a', b'GIF89a']:
                    return 'gif'
                # PDF signature
                elif magic[:4] == b'%PDF':
                    return 'pdf'
                # WEBP signature
                elif magic[:4] == b'RIFF' and magic[8:12] == b'WEBP':
                    return 'webp'
                else:
                    return None
        except:
            return None
    
    def _get_filename(self, doc_padded, page_padded):
        """Generate filename based on naming scheme"""
        return f"{self.module_name}_{doc_padded}_{page_padded}.{Config.IMAGE_FORMAT}"
    
    def get_docs_pages_from_manifest(self):
        """Extract docs_pages dict from manifest"""
        if not self.manifest_data or "metadata" not in self.manifest_data:
            return None
        
        metadata = self.manifest_data["metadata"]
        if "docs_info" not in metadata:
            return None
        
        return metadata["docs_info"]
    
    def get_file_info_for_download(self, filename):
        """Get original submodule and page number for a file"""
        if filename not in self.manifest_data["files"]:
            return None, None
        
        file_info = self.manifest_data["files"][filename]
        submodule = int(file_info.get("submodule", 0))
        pagenumber = int(file_info.get("pagenumber", 0))
        
        return submodule, pagenumber


# ============================================================================
# USER INPUT AND VALIDATION
# ============================================================================

def get_user_input():
    """Get module name, number of docs, and pages for each doc"""
    print("\n" + "=" * 70)
    print("IMAGE FETCHER - NEW DOWNLOAD CONFIGURATION")
    print("=" * 70)
    
    # Get module name
    while True:
        module_name = input("\nEnter module name (e.g., MSIM4408): ").strip()
        if module_name and module_name.replace("_", "").replace("-", "").isalnum():
            break
        print("Invalid module name! Use alphanumeric characters only.")
    
    # Get number of submodules
    while True:
        try:
            num_docs = int(input(f"Enter number of submodules for {module_name} (e.g., 5): "))
            if num_docs > 0:
                break
            print("Please enter a positive number!")
        except ValueError:
            print("Please enter a valid number!")
    
    # Get pages for each doc
    docs_pages = {}
    print(f"\nNow enter the number of pages for each document:")
    
    for i in range(1, num_docs + 1):
        while True:
            try:
                pages = int(input(f"  M{i} - Number of pages: "))
                if pages > 0:
                    docs_pages[f"M{i}"] = pages
                    break
                print("  Please enter a positive number!")
            except ValueError:
                print("  Please enter a valid number!")
    
    return module_name, docs_pages


def handle_existing_module(module_name):
    """Handle case where module already exists"""
    manifest_mgr = ManifestManager(module_name)
    manifest_data = manifest_mgr.load_manifest()
    output_dir = Path(module_name)
    
    print("\n" + "=" * 70)
    print(f"EXISTING MODULE FOUND: {module_name}")
    print("=" * 70)
    
    if manifest_data:
        metadata = manifest_data["metadata"]
        print(f"Module: {metadata['module_name']}")
        print(f"Documents: {metadata['num_docs']}")
        print(f"Total pages: {metadata['total_pages']}")
        
        progress = manifest_mgr.get_download_progress()
        print(f"Download progress: {progress:.1f}%")
        
        # Verify files
        if output_dir.exists():
            is_complete = manifest_mgr.verify_files(output_dir)
            
            if is_complete:
                print("\n✓ All files are downloaded and verified!")
                return "complete", None
            else:
                # Check for format mismatches
                format_issues = [
                    (fname, info) for fname, info in manifest_data["files"].items()
                    if info["status"] == DownloadStatus.FORMAT_MISMATCH.value
                ]
                
                if format_issues:
                    print(f"\n⚠ Found {len(format_issues)} file(s) with format mismatch:")
                    for fname, info in format_issues[:3]:
                        print(f"   - {fname}: expected {Config.IMAGE_FORMAT}, got {info.get('actual_format')}")
                    
                    choice = input("\nDo you want to see these files or re-download them? (view/redownload/ignore): ").strip().lower()
                    if choice == "view":
                        for fname, info in format_issues:
                            fpath = output_dir / fname
                            if fpath.exists():
                                try:
                                    if sys.platform == 'win32':
                                        os.startfile(fpath)
                                    elif sys.platform == 'darwin':
                                        subprocess.run(['open', str(fpath)])
                                    else:
                                        subprocess.run(['xdg-open', str(fpath)])
                                    print(f"Opening: {fname}")
                                    time.sleep(1)
                                except Exception as e:
                                    print(f"Could not open {fname}: {e}")
                        
                        choice = input("\nResume download (skip mismatched files) or continue with mismatch? (resume/continue/cancel): ").strip().lower()
                        if choice == "resume":
                            return "resume", manifest_mgr
                        elif choice == "continue":
                            return "resume", manifest_mgr
                        else:
                            return "cancel", None
                    elif choice == "redownload":
                        # Mark format mismatches as pending for re-download
                        for fname in [f[0] for f in format_issues]:
                            manifest_mgr.manifest_data["files"][fname]["status"] = DownloadStatus.PENDING.value
                        manifest_mgr._save_manifest()
                        return "resume", manifest_mgr
                
                print("\n⚠ Some files are missing or incomplete. Ready to resume.")
                return "resume", manifest_mgr
        else:
            print(f"\n⚠ Download folder '{module_name}' not found.")
            choice = input("Do you want to create and resume download? (yes/no): ").strip().lower()
            if choice == "yes":
                return "resume", manifest_mgr
            else:
                return "cancel", None
    else:
        print(f"⚠ Manifest file not found but folder exists.")
        print(f"Do you want to start a new download? (This will not resume existing files)")
        choice = input("Continue with new download? (yes/no): ").strip().lower()
        if choice == "yes":
            return "new", None
        else:
            return "cancel", None


# ============================================================================
# DOWNLOAD OPERATIONS
# ============================================================================

def is_text_file(filepath):
    """Check if file is plain text (possible HTML error response)"""
    try:
        with open(filepath, 'rb') as f:
            content = f.read(1024)  # Read first 1KB
            
            # Check for common HTML/text signatures
            if b'<!DOCTYPE' in content or b'<html' in content or b'<HTML' in content:
                return True
            if b'<?xml' in content:
                return True
            if b'<?php' in content:
                return True
            # Check if content is mostly printable ASCII (likely text)
            try:
                content.decode('utf-8')
                # If it decodes as UTF-8 and starts with text markers, likely text
                if any(marker in content[:200] for marker in [b'login', b'error', b'unauthorized', b'expired']):
                    return True
            except:
                pass
        return False
    except:
        return False


def fetch_image(module_name, submodule, page, output_dir, session, manifest_mgr, filename_padded):
    """Fetch a single image using the session with original doc/page names"""
    # Use original names for the request
    doc_original = f"M{submodule}"
    
    params = {
        'doc': doc_original,
        'format': Config.IMAGE_FORMAT,
        'subfolder': f'{module_name}/',
        'page': page
    }
    
    headers = {
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'i',
        'referer': f'{Config.REFERER_BASE}?subfolder={module_name}/&doc={doc_original}.pdf',
        'sec-ch-ua': '"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'image',
        'sec-fetch-mode': 'no-cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
    }
    
    filepath = output_dir / filename_padded
    
    try:
        response = session.get(Config.BASE_URL, params=params, headers=headers, timeout=Config.TIMEOUT)
        response.raise_for_status()
        
        # Check content-type for actual format
        content_type = response.headers.get('content-type', '').lower()
        actual_format = None
        
        if 'image/jpeg' in content_type or 'image/jpg' in content_type:
            actual_format = 'jpg'
        elif 'image/png' in content_type:
            actual_format = 'png'
        elif 'image/gif' in content_type:
            actual_format = 'gif'
        elif 'image/webp' in content_type:
            actual_format = 'webp'
        
        # Save file
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        # Check if file is actually text (HTML error, etc.) - usually means expired cookie
        if is_text_file(filepath):
            print(f"\n✗ Invalid response for {filename_padded} - received text/HTML instead of image")
            print("   This usually means your cookies have expired or session is invalid!")
            filepath.unlink()  # Delete the invalid file
            manifest_mgr.update_file_status(
                filename_padded,
                DownloadStatus.FAILED,
                error="Received text/HTML instead of image - likely expired cookies"
            )
            return "cookie_expired"
        
        # Verify actual format by reading magic bytes
        detected_format = ManifestManager._get_file_format(filepath)
        if detected_format:
            actual_format = detected_format
        
        file_size = len(response.content)
        
        # Check for format mismatch
        if actual_format and actual_format.lower() != Config.IMAGE_FORMAT.lower():
            print(f"⚠ Format mismatch: {filename_padded} - expected {Config.IMAGE_FORMAT}, got {actual_format}")
            manifest_mgr.update_file_status(
                filename_padded,
                DownloadStatus.FORMAT_MISMATCH,
                size=file_size,
                actual_format=actual_format
            )
            return "format_mismatch"
        
        manifest_mgr.update_file_status(
            filename_padded,
            DownloadStatus.COMPLETED,
            size=file_size,
            actual_format=actual_format or Config.IMAGE_FORMAT
        )
        
        print(f"✓ Downloaded: {filename_padded} ({file_size:,} bytes)")
        return "success"
    
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        manifest_mgr.update_file_status(filename_padded, DownloadStatus.FAILED, error=error_msg)
        print(f"✗ Failed to download {filename_padded}: {e}")
        return "failed"


def test_first_file(module_name, session, manifest_mgr):
    """Test download of first file to verify connectivity"""
    print("\nTesting first file download...")
    
    metadata = manifest_mgr.manifest_data["metadata"]
    first_doc = sorted(metadata["docs_info"].keys())[0]
    doc_num = int(first_doc.replace("M", ""))
    
    params = {
        'doc': first_doc,
        'format': Config.IMAGE_FORMAT,
        'subfolder': f'{module_name}/',
        'page': 1
    }
    
    headers = {
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'referer': f'{Config.REFERER_BASE}?subfolder={module_name}/&doc={first_doc}.pdf',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
    }
    
    try:
        response = session.get(Config.BASE_URL, params=params, headers=headers, timeout=Config.TIMEOUT)
        response.raise_for_status()
        print("✓ Test successful! Ready to resume download.")
        return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def run_download(module_name, docs_pages, resume_manifest=None):
    """Execute the download process"""
    output_dir = Path(module_name)
    output_dir.mkdir(exist_ok=True)
    
    # Initialize or resume manifest
    if resume_manifest:
        manifest_mgr = resume_manifest
        print("\n" + "=" * 70)
        print("RESUMING DOWNLOAD")
        print("=" * 70)
    else:
        manifest_mgr = ManifestManager(module_name)
        manifest_mgr.create_manifest(docs_pages)
        print("\n" + "=" * 70)
        print("STARTING NEW DOWNLOAD")
        print("=" * 70)
    
    # Display summary
    metadata = manifest_mgr.manifest_data["metadata"]
    print(f"Module: {module_name}")
    print(f"Documents: {metadata['num_docs']}")
    print(f"Total pages: {metadata['total_pages']}")
    print(f"Expected format: {Config.IMAGE_FORMAT.upper()}")
    
    progress = manifest_mgr.get_download_progress()
    if progress > 0:
        print(f"Current progress: {progress:.1f}%")
    
    print("=" * 70)
    
    # Confirm before starting
    confirm = input("\nProceed with download? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Cancelled.")
        return False
    
    # Create session with all cookies
    session = requests.Session()
    for cookie_name, cookie_value in Config.COOKIES.items():
        session.cookies.set(cookie_name, cookie_value)
    
    # Get list of files to download
    pending_files = manifest_mgr.get_pending_files()
    total_files = len(manifest_mgr.manifest_data["files"])
    completed_files = total_files - len(pending_files)
    
    print(f"\nDownloading {len(pending_files)} file(s) ({completed_files}/{total_files} already completed)\n")
    
    interrupted = False
    try:
        for idx, filename in enumerate(pending_files, 1):
            # Get original submodule and page number from manifest
            submodule, pagenumber = manifest_mgr.get_file_info_for_download(filename)
            
            if submodule is None or pagenumber is None:
                print(f"⚠ Skipping {filename}: Missing file info in manifest")
                continue
            
            current_total = completed_files + idx
            print(f"[{current_total}/{total_files}] Fetching {filename}...")
            
            result = fetch_image(module_name, submodule, pagenumber, output_dir, session, manifest_mgr, filename)
            
            if result == "cookie_expired":
                print("\n" + "=" * 70)
                print("⚠ COOKIE EXPIRATION DETECTED")
                print("=" * 70)
                print("The server returned text/HTML instead of an image.")
                print("This usually means your session cookies have expired.")
                print("\nTo fix this:")
                print("1. Open your browser and login to https://pustaka.ut.ac.id")
                print("2. Extract the new cookies from your request headers")
                print("3. Update the COOKIES dictionary in Config class")
                print("4. Run the script again to resume\n")
                choice = input("Do you want to stop now to update cookies? (yes/no): ").strip().lower()
                if choice == "yes":
                    interrupted = True
                    break
                # Otherwise continue (will keep failing)
            elif result == "format_mismatch":
                choice = input("  File has different format. Resume (skip this) or stop? (resume/stop): ").strip().lower()
                if choice == "stop":
                    interrupted = True
                    break
            elif result == "failed":
                choice = input("  Download failed. Resume (skip this) or stop? (resume/stop): ").strip().lower()
                if choice == "stop":
                    interrupted = True
                    break
            
            # Random delay between requests
            if idx < len(pending_files):
                delay = random.uniform(Config.MIN_DELAY, Config.MAX_DELAY)
                print(f"Waiting {delay:.1f} seconds before next request...")
                time.sleep(delay)
    
    except KeyboardInterrupt:
        print("\n\n⚠ Download interrupted by user. Progress saved. You can resume later.")
        interrupted = True
    finally:
        session.close()
        
        final_progress = manifest_mgr.get_download_progress()
        print(f"\nCurrent progress: {final_progress:.1f}%")
        
        if manifest_mgr.is_download_complete():
            print(f"✓ All files downloaded successfully!")
            return True
        else:
            if not interrupted:
                print(f"⚠ Download incomplete. Run the script again to resume.")
            return False


# ============================================================================
# PDF GENERATION
# ============================================================================

def combine_to_pdf(module_name):
    """Combine all downloaded images into a single PDF"""
    try:
        from PIL import Image
    except ImportError:
        print("\n✗ PIL (Pillow) not installed. Install with: pip install Pillow")
        return False
    
    output_dir = Path(module_name)
    
    # Get all JPG files in order (sorted by filename which includes padding)
    jpg_files = sorted(output_dir.glob(f"*.{Config.IMAGE_FORMAT}"))
    
    if not jpg_files:
        print("✗ No images found to combine.")
        return False
    
    print(f"\nCombining {len(jpg_files)} images into PDF...")
    
    try:
        images = []
        for jpg_file in jpg_files:
            try:
                img = Image.open(jpg_file)
                # Convert CMYK to RGB if necessary
                if img.mode in ('CMYK', 'P'):
                    img = img.convert('RGB')
                images.append(img)
                print(f"  Added: {jpg_file.name}")
            except Exception as e:
                print(f"  ⚠ Skipped {jpg_file.name}: {e}")
        
        if not images:
            print("✗ No valid images to combine.")
            return False
        
        pdf_filename = f"{module_name}.pdf"
        pdf_path = output_dir / pdf_filename
        
        images[0].save(
            pdf_path,
            "PDF",
            save_all=True,
            append_images=images[1:],
            optimize=False
        )
        
        print(f"\n✓ PDF created successfully: {pdf_path.absolute()}")
        return True
    
    except Exception as e:
        print(f"\n✗ Error creating PDF: {e}")
        return False


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    print("\n" + "=" * 70)
    print("AUTOMATED RBV IMAGE FETCHER WITH RESUME CAPABILITY")
    print("=" * 70)
    
    # Get module name
    module_name = input("\nEnter module name (e.g., MSIM4408): ").strip()
    if not module_name:
        print("Module name cannot be empty!")
        return
    
    # Check if module exists
    if Path(module_name).exists():
        status, manifest_mgr = handle_existing_module(module_name)
        
        if status == "complete":
            choice = input("\nDo you want to combine images into PDF? (yes/no): ").strip().lower()
            if choice == "yes":
                combine_to_pdf(module_name)
            return
        elif status == "resume":
            docs_pages = manifest_mgr.get_docs_pages_from_manifest()
            run_download(module_name, docs_pages, resume_manifest=manifest_mgr)
        elif status == "new":
            module_name, docs_pages = get_user_input()
            run_download(module_name, docs_pages)
        else:
            print("Cancelled.")
            return
    else:
        # New download
        module_name, docs_pages = get_user_input()
        run_download(module_name, docs_pages)
    
    # Ask about PDF conversion after download
    if Path(module_name).exists():
        choice = input("\nDo you want to combine images into PDF? (yes/no): ").strip().lower()
        if choice == "yes":
            combine_to_pdf(module_name)
    
    print("\n✓ Done!")


if __name__ == "__main__":
    main()
