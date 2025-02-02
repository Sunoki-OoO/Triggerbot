import os
import subprocess

def install(package):
    subprocess.check_call([os.sys.executable, "-m", "pip", "install", package])

def main():
    print("Installing required libraries...")
    libraries = [
        "opencv-python",  # cv2
        "numpy",
        "ctypes",
        "pypiwin32",  # win32api
        "bettercam",
        "threading"
    ]

    for lib in libraries:
        try:
            install(lib)
            print(f"{lib} installed successfully")
        except Exception as e:
            print(f"Failed to install {lib}: {e}")

    print("All libraries installed")

if __name__ == "__main__":
    main()
