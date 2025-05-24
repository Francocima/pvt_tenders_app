import os
import random
import tempfile
import time
import zipfile
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
from botocore.exceptions import ClientError
from webdriver_manager.chrome import ChromeDriverManager


def setup_selenium(user_agents: list, chromedriver_path="/usr/local/bin/chromedriver"):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument(f"user-agent={random.choice(user_agents)}")

    download_dir = tempfile.mkdtemp()
    chrome_options.add_experimental_option("prefs", {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    })

    chromedriver_path = '/usr/local/bin/chromedriver'
    # ChromeDriverManager().install()

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.set_window_size(1200, 720)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    return driver, download_dir

def wait_for_download(download_dir, timeout=120):
    start_time = time.time()
    while time.time() - start_time < timeout:
        files = os.listdir(download_dir)
        complete_files = [f for f in files if not f.endswith(('.crdownload', '.tmp', '.part'))]
        if complete_files:
            return os.path.join(download_dir, complete_files[0])
        time.sleep(1)
    return None

def extract_zip_file(zip_path, extract_dir):
    extracted_files = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            extracted_files = [os.path.join(extract_dir, name) for name in zip_ref.namelist()]
    except Exception as e:
        print(f"Error extracting zip file: {str(e)}")
    return extracted_files

def upload_file_to_spaces(client, bucket_name, file_path, object_key):
    try:
        with open(file_path, 'rb') as file_data:
            client.upload_fileobj(file_data, bucket_name, object_key, ExtraArgs={'ACL': 'private'})
        return True
    except ClientError as e:
        print(f"Upload error: {str(e)}")
        return False
