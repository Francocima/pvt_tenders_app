import aiohttp
import asyncio
import json
import re
import time
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, HttpUrl
import uvicorn
import os
from datetime import datetime
import random
import selenium.webdriver as webdriver
import boto3
import tempfile
import zipfile
from botocore.exceptions import ClientError
import requests
from botocore.client import BaseClient
from pathlib import Path


#import all selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager


#Create the FastAPI app

app = FastAPI(
    title="Tenders Scraper",
    version="1.0"
)

# Define the data model for the job search request
class LoginRequest(BaseModel):
    login_url: HttpUrl
    email: str
    password: str

class ScrapeRequest(BaseModel):
    login_url: HttpUrl
    email: str
    password: str
    target_url: HttpUrl
    webhook_url: HttpUrl

class ScrapeTenderDescription(BaseModel):
    login_url: str
    tender_id: str
    email: str
    password: str

class ScrapeDownloadFiles(BaseModel):
    login_url: str
    tender_ids: List[str]
    email: str
    password: str
    url_template: str
    do_spaces_config: Dict[str, str]


#Scraper creation

class TenderScraper:
    
    def __init__(self, use_selenium: bool = True):
        self.base_url = "https://www.vendorpanel.com.au/"
        self.use_selenium = use_selenium
        self.timeout = 30

        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15'
        ]  # set the rotation of browsers
        
    def _setup_selenium(self):
        """
        Set up the Selenium web driver with Chrome
        """
        # Set up the Chrome options
        chrome_options = Options()
        
        chrome_options.add_argument('--ignore-certificate-errors')
        chrome_options.add_argument('--allow-insecure-localhost')
        chrome_options.add_argument('--ignore-ssl-errors=yes')
        chrome_options.add_argument('--disable-web-security')

        # Add headless option for server environments
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")

        # Add additional privacy options to avoid detection
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # Set user agent - Picks randomly from the list
        chrome_options.add_argument(f"user-agent={random.choice(self.user_agents)}")

        download_dir = tempfile.mkdtemp()

        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        chrome_options.add_experimental_option("prefs", prefs)

        chromedriver_path = '/usr/local/bin/chromedriver'
        
        self.driver = webdriver.Chrome(
            service=Service(chromedriver_path),  # change to chromedriver_path to use in sevalla     ChromeDriverManager().install()
            options=chrome_options
        )
            
        self.download_dir = download_dir
        
        # Set window size
        self.driver.set_window_size(1200, 720)
        
        # Execute JavaScript to mask WebDriver presence
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")    

    
    def _set_up_do_spaces_(self, do_spaces_config: Dict[str, str]) -> Optional[BaseClient]:
        try:
            session = boto3.session.Session()
            client = session.client(
                service_name='s3',
                region_name=do_spaces_config['region'],
                endpoint_url=do_spaces_config['endpoint_url'],
                aws_access_key_id=do_spaces_config['access_key'],
                aws_secret_access_key=do_spaces_config['secret_key']
        )
            client.head_bucket(Bucket=do_spaces_config['bucket_name'])
            print("Successfully connected to Digital Ocean Spaces")
            return client
        
        except Exception as e :
            print(f"Error setting up DO Spaces: {str(e)}")
            return None
        



    async def __aenter__(self):
        """Set up resources when entering context"""
        if not self.use_selenium:
            # Only set up aiohttp if not using Selenium
            self.session = aiohttp.ClientSession(headers=self.headers)
            
            # Make an initial request to get cookies
            try:
                async with self.session.get(self.base_url) as response:
                    if response.status == 200:
                        print("Successfully initialized session with cookies")
            except Exception as e:
                print(f"Error initializing session: {str(e)}")
                
        return self
    

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting context"""
        if self.use_selenium:
            self.driver.quit()
        else:
            await self.session.close()

    #using the API call with the email and password to login
    def _login_ (self, email: str, password: str, login_url: str):
        """
        Logs into the VendorPanel website using Selenium.
        """
        
        try:
            
            # Add debugging to verify _setup_selenium is called
            print("Starting login process, initializing Selenium...")
            
            # Always initialize Selenium here to ensure driver exists
            try:
                self._setup_selenium()
                print("Selenium setup completed successfully")
            except Exception as setup_error:
                print(f"Error during Selenium setup: {str(setup_error)}")
                # Re-raise to be caught by the outer try-except
                raise
            
            # Verify driver was created
            if not hasattr(self, 'driver'):
                print("Critical error: driver not initialized after _setup_selenium")
                return False
            
            # Rest of the login process
            print(f"Navigating to login page: {login_url}")
            self.driver.get(login_url)
                
            # Wait for the email field to be present
            email_field = WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.ID, "UserName"))
            )
            
            # Enter the email
            email_field.send_keys(email)
            print(f"Entered email: {email}")
            
            # Find and click the Next button
            next_button = self.driver.find_element(By.ID, "btnGo")
            next_button.click()
            print("Clicked Next button")

            password_field = WebDriverWait(self.driver, self.timeout).until(
            EC.presence_of_element_located((By.ID, "Password")))
        
            # Enter the password
            password_field.send_keys(password)
            print("Entered password")
            
            # Find and click the login button
            login_button = self.driver.find_element(By.ID, "btnGo")
            login_button.click()
            print("Clicked login button")   

            try:
                # Look for elements that would indicate successful login
                # Adjust these selectors based on the actual page structure
                WebDriverWait(self.driver, self.timeout).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".dashboard-container")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".user-profile")),
                        EC.url_contains("Members")
                    )
                )
                print("Login successful")
                return True
            except TimeoutException:
                # Check for error messages
                error_messages = self.driver.find_elements(By.CSS_SELECTOR, ".validation-summary-errors, .field-validation-error")
                if error_messages:
                    for error in error_messages:
                        print(f"Login error: {error.text}")
                else:
                    print("Login failed: Timed out waiting for dashboard page")
                return False
                
        except Exception as e:
            print(f"Login failed with error: {str(e)}")
            return False
    
    
    #Scraper function to get the tenders from the page

    async def scrape_tenders(self, target_url: str) -> List[Dict]:
        """
        Scrapes tender information from the specified URL after login.
        
        Args:
            target_url: The URL to scrape data from
                
        Returns:
            List[Dict]: A list of dictionaries containing tender information
        """
        # Checkpoint to verify if the driver is initialized
        if not hasattr(self, 'driver'):
            print("Driver not initialized. Please login first.")
            return []
        
        try:
            print(f"Scraping tenders from: {target_url}")
            self.driver.get(target_url)

            # Wait for the page to load
            WebDriverWait(self.driver, self.timeout).until(
                EC.any_of(
                    EC.presence_of_element_located((By.TAG_NAME, "body")),
                    EC.url_contains("do=Tenders:AllTenders")))
            
            print("Page loaded successfully")

            time.sleep(2)  # Allow dynamic content to load
            
            # List to store tender information
            tenders = []
            current_page = 1
            
            while True:
                print(f"Processing page {current_page}")
            
                # Wait for tender rows to load dynamically
                try:
                    print("Waiting for tender rows to load...")
                    # Wait for at least one tr element with a numeric ID to appear
                    WebDriverWait(self.driver, 20).until(
                        lambda driver: driver.find_elements(By.XPATH, "//tr[@id]")
                    )
                    print("Tender rows detected, waiting a bit more for all content...")
                    time.sleep(3)  # Additional time for all rows to load
                except TimeoutException:
                    print("Timeout waiting for tender rows to load")
                    # Try to continue anyway in case content is there but selector is wrong
                
                # Get the page source and parse it with BS4
                page_source = self.driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                
                # Debug: Let's see what we actually have in the HTML
                print("=== DEBUG: Checking HTML structure ===")
                
                # Check for tbody elements
                tbody_elements = soup.find_all('tbody')
                print(f"Found {len(tbody_elements)} tbody elements")
                
                # Check for any tr elements at all
                all_tr_elements = soup.find_all('tr')
                print(f"Found {len(all_tr_elements)} total tr elements")
                
                # Check for tr elements with any id attribute
                tr_with_any_id = soup.find_all('tr', id=True)
                print(f"Found {len(tr_with_any_id)} tr elements with id attribute")
                
                if tr_with_any_id:
                    print("Sample tr IDs:")
                    for tr in tr_with_any_id[:5]:
                        print(f"  ID: {tr.get('id')}")
                
                # Check for elements with class names that might contain tender info
                tender_elements = soup.find_all(class_=lambda x: x and 'tender' in x.lower())
                print(f"Found {len(tender_elements)} elements with 'tender' in class name")
                
                # Look for the specific structure we expect
                followed_tender_divs = soup.find_all('div', class_='followedTender')
                print(f"Found {len(followed_tender_divs)} div elements with 'followedTender' class")
                
                print("=== END DEBUG ===")
                
                # Look for tender elements - try multiple approaches
                numeric_id_rows = []
                
                # Method 1: Direct search for tr with numeric IDs
                rows_with_ids = soup.find_all('tr', id=True)
                if rows_with_ids:
                    numeric_id_rows = [row for row in rows_with_ids if row.get('id', '').isdigit()]
                    print(f"Method 1: Found {len(numeric_id_rows)} tr elements with numeric IDs")
                
                # Method 2: If no rows found, try using Selenium to find them
                if not numeric_id_rows:
                    print("Method 2: Using Selenium to find tr elements with numeric IDs")
                    try:
                        selenium_rows = self.driver.find_elements(By.XPATH, "//tr[@id]")
                        print(f"Selenium found {len(selenium_rows)} tr elements with id attribute")
                        
                        # Filter for numeric IDs
                        numeric_selenium_rows = []
                        for row in selenium_rows:
                            row_id = row.get_attribute('id')
                            if row_id and row_id.isdigit():
                                numeric_selenium_rows.append(row)
                        
                        print(f"Selenium found {len(numeric_selenium_rows)} tr elements with numeric IDs")
                        
                        # If we found rows with Selenium, get the page source again
                        if numeric_selenium_rows:
                            print("Re-parsing page source after Selenium detection...")
                            page_source = self.driver.page_source
                            soup = BeautifulSoup(page_source, 'html.parser')
                            rows_with_ids = soup.find_all('tr', id=True)
                            numeric_id_rows = [row for row in rows_with_ids if row.get('id', '').isdigit()]
                            print(f"After re-parsing: Found {len(numeric_id_rows)} tr elements with numeric IDs")
                    
                    except Exception as e:
                            print(f"Error using Selenium to find rows: {str(e)}")

                tender_info_containers = []
                if numeric_id_rows:
                    print("Using rows with numeric IDs")
                    tender_info_containers = numeric_id_rows
                else:
                    print("No tender rows found on this page")
                    # Before giving up, let's try to save the HTML for debugging
                    with open(f'debug_page_{current_page}.html', 'w', encoding='utf-8') as f:
                        f.write(page_source)
                    print(f"Saved page HTML to debug_page_{current_page}.html for inspection")
                    break
                    
                # Process tenders on current page
                page_tenders_processed = 0
                for container in tender_info_containers:
                    tender_data = {}  # Dictionary to store tender data

                    try: 
                        # Extract tender ID
                        tender_id = container.get('id')
                        if tender_id:
                            tender_data['tender_id'] = tender_id
                        
                        # Try different selectors for tender title
                        title_selectors = [
                            '.tenderName', '.alertResultTitle', 
                            'a', 'td a', 'td:first-child a', '.title', 'h3', 'h4'
                        ]
                        
                        for selector in title_selectors:
                            title_element = None
                            try:
                                if selector.startswith('.') or selector.startswith('#') or ' ' in selector:
                                    title_element = container.select_one(selector)
                                else:
                                    title_element = container.find(selector)

                                if title_element and title_element.text.strip():
                                    tender_data['tender_title'] = title_element.text.strip()
                                    break
                            except:
                                continue

                        # Tender block information
                        info_block = container.select_one('.tenderBody')
                        if info_block:
                            rows = info_block.select('.tenderDetailsRow')
                            for row in rows:
                                label_span = row.select_one('.tenderDetailsLabel')
                                value_spans = row.find_all('span')
                                
                                if label_span and len(value_spans) > 1:
                                    label = label_span.get_text(strip=True)
                                    value = value_spans[1].get_text(strip=True)

                                    if label == "Closing:":
                                        tender_data['tender_closing_date'] = value
                                    elif label == "Issued by:":
                                        tender_data['organisation'] = value
                                        
                        if tender_data and 'tender_id' in tender_data:  # Only add if we have at least an ID
                            tenders.append(tender_data)
                            page_tenders_processed += 1

                    except Exception as e:
                        print(f"Error extracting tender data: {str(e)}")
                        continue
                        
                print(f"Processed {page_tenders_processed} tenders on page {current_page}")
                
                # Attempt to navigate to the next page
                try:
                    # Find the pagination container
                    pagination = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "dt-custom-paging"))
                    )
                    buttons = pagination.find_elements(By.TAG_NAME, "button")
                    
                    # Look for the button that contains the fa-caret-right icon
                    next_button = None
                    for button in buttons:
                        icon = button.find_elements(By.CLASS_NAME, "fa-caret-right")
                        if icon:
                            next_button = button
                            break
                    
                    if next_button and "disabled" not in next_button.get_attribute("class") and not next_button.get_attribute("disabled"):
                        print("Clicking next button to navigate to the next page")
                        self.driver.execute_script("arguments[0].click();", next_button)
                        current_page += 1
                        time.sleep(5)  # Wait for the next page to load
                    else:
                        print(f"Next button is disabled or not found. End of pagination at page {current_page}")
                        break
                
                except TimeoutException:
                    print(f"No more pages to scrape (pagination container not found), ended at page {current_page}")
                    break
                except Exception as e:
                    print(f"Error navigating to next page: {str(e)}")
                    break
                                    
            print(f"Successfully scraped {len(tenders)} tenders across {current_page} pages")
            return tenders

        except Exception as e:
            print(f"Error during scraping: {str(e)}")
            import traceback
            traceback.print_exc()
            return []


    # Scraper for the tender description + downloader

    async def scrape_tender_description(self, tender_id: str) -> Dict:
        
        tender_details_url =  f"https://www.vendorpanel.com.au/Members/VendorPreviewOpportunity.aspx?opportunityId={tender_id}"

        try: 
            print(f"Navigating to the tender details page: {tender_details_url}")

            self.driver.get(tender_details_url)

            WebDriverWait(self.driver, self.timeout).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".OpportunityPreviewRow")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".opportunityPreviewContent")),
                EC.url_contains("VendorPreviewOpportunity")
            ))   #Last flag to see if we are in the right page
            
            print("Page loaded successfully")

            # get the page source and parse it with BS4
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')            
                        
            # List to store tender information
            tender_details = {'tender_details_url': tender_details_url}

            opportunity_rows = soup.find_all('tr', class_='OpportunityPreviewRow')

            for row in opportunity_rows:
                # Look for the row that contains dates
                date_sections = row.find_all('div', class_='opportunityPreviewInnerRow')
                
                for section in date_sections:
                    heading = section.find('div', class_='opportunityPreviewMinHeading')
                    content = section.find('div', class_='opportunityPreviewContent')
                    
                    if heading and content:
                        heading_text = heading.text.strip()
                        
                        # Extract just the date part without the timezone info
                        content_text = content.text.strip()
                        if "(" in content_text:
                            content_text = content_text.split("(")[0].strip()
                        
                        # Get the opening date
                        if heading_text == "Opens":
                            tender_details['tender_opening_date'] = content_text
                            print(f"Found opening date: {content_text}")
                        
                        # Get the expected decision date
                        elif heading_text == "Expected decision":
                            tender_details['tender_decision_date'] = content_text
                            print(f"Found decision date: {content_text}")

                        elif heading_text == "Location":
                            tender_details['tender_location'] = content_text
                            print(f"Found location: {content_text}")
                        
                        elif heading_text == "Business Info":
                            tender_details['tender_business_info'] = content_text
                            print(f"Found business info: {content_text}")

                        elif heading_text == "Contact Details":
                            tender_details['tender_contact_details'] = content_text
                            print(f"Found contact details: {content_text}")

                        elif heading_text == "WebSite:":
                            tender_details['organisation_website'] = content_text

                        elif heading_text == "Email:":
                            tender_details['organisation_email'] = content_text

                        elif heading_text == "Contact Name":
                            tender_details['organisation_contact_name'] = content_text
                            
                
                
                max_headings = row.find_all('div', class_='opportunityPreviewMaxHeading')

                for max_heading in max_headings:
                    heading_text = max_heading.text.strip()

                    content_section = max_heading.find_next_sibling('div', class_='opportunityPreviewInnerRow')

                    if content_section:
                        content_div = content_section.find('div', class_='opportunityPreviewContent')
                        if content_div:
                            content_text = content_div.text.strip()

                            if "What the buyer is requesting" in heading_text:
                                tender_details['tender_general_details'] = content_text
                                
                                
                            elif "Background information" in heading_text:
                                tender_details['tender_background_information'] = content_text
                                
                            elif "Regions of Service" in heading_text:
                                tender_details['tender_region_of_service'] = content_text

                            elif "Desired Outcomes" in heading_text:
                                tender_details['tender_desired_outcomes'] = content_text

                            elif "Attachments" in heading_text:
                                tender_details['tender_attachments'] = content_text

                            elif "Updates" in heading_text:
                                tender_details['tender_updates'] = content_text

                            else:
                                # Keep the exact heading as it appears on the website
                                tender_details[heading_text] = content_text
        
            required_sections = ['tender_general_details', 'tender_background_information', 'tender_desired_outcomes']
            for section in required_sections:
                if section not in tender_details:
                    tender_details[section] = "Section not available"
                        
                
            return tender_details
                    
        except Exception as e:
            print(f"Error during tender details scraping: {str(e)}")
            import traceback
            traceback.print_exc()
            return []


    async def send_to_webhook(self, webhook_url: str, tenders: List[Dict]):
        """
        Send scraped data to a webhook URL
        
        Args:
            webhook_url: The URL to send the data to
            data: The data to send
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Content-Type': 'application/json'
                }
                
                # Add a timestamp to the data
                payload = {
                    'timestamp': datetime.now().isoformat(),
                    'tenders': tenders
                }
                
                print(f"Sending data to webhook: {webhook_url}")
                async with session.post(webhook_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        print(f"Successfully sent data to webhook. Status: {response.status}")
                        return True
                    else:
                        print(f"Failed to send data to webhook. Status: {response.status}")
                        return False
                        
        except Exception as e:
            print(f"Error sending data to webhook: {str(e)}")
            return False


    async def follow_button_click(self, tender_id: str): 

        tender_details_url =  f"https://www.vendorpanel.com.au/Members/VendorPreviewOpportunity.aspx?opportunityId={tender_id}"

        try: 
            print(f"Navigating to the tender details page: {tender_details_url}")

            self.driver.get(tender_details_url)

            
            try:
                WebDriverWait(self.driver, self.timeout).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".OpportunityPreviewRow")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".opportunityPreviewContent")),
                        EC.url_contains("VendorPreviewOpportunity")
                ))   #Last flag to see if we are in the right page
                
                print("Page loaded successfully")
            except TimeoutException:
                print("Timeout waiting for the tender details page to load")
                return False
            
            # get the page source and parse it with BS4
            page_source = self.driver.page_source
                     

                        # Look for the follow button
            try:
                follow_button = WebDriverWait(self.driver, self.timeout).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".iconButton"))  
                )
                print("Follow button found and is clickable")
            except TimeoutException:
                # Check if button exists but is not clickable
                try:
                    button_exists = self.driver.find_element(By.CSS_SELECTOR, ".iconButton")
                    return {"success": False, "error": "button_not_clickable", "message": "Follow button exists but is not clickable"}
                except Exception as e:
                    return {"success": False, "error": "button_not_found", "message": "Follow button not found on page"}

            try:
                
                # Try regular click first
                follow_button.click()
                print("Follow button clicked successfully")
                
                # Wait a moment and verify the action succeeded (you might need to adjust this based on the site's behavior)
                time.sleep(1)
                
                # Optional: Check if the button state changed (e.g., text changed from "Follow" to "Following")
                # This depends on how the website implements the follow functionality
                
                return {"success": True, "message": "Follow button clicked successfully"}
                
            except Exception as e:
                print(f"Error clicking follow button: {str(e)}")
                return False
        
        except Exception as e:
            print(f"Error during tender details scraping: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


    def _download_wait_ (self, timeout=120) -> Optional[str]:

        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Look for files in download directory
            if os.path.exists(self.download_dir):
                files = os.listdir(self.download_dir)
                
                # Filter out partial downloads (usually end with .crdownload or .tmp)
                complete_files = [f for f in files if not f.endswith(('.crdownload', '.tmp', '.part'))]
                
                if complete_files:
                    # Return the first complete file found
                    return os.path.join(self.download_dir, complete_files[0])
            
            time.sleep(1)
        
        print(f"Download timeout after {timeout} seconds")
        return None
    
    def _extract_zip_file(self, zip_path: str, extract_dir: str) -> List[str]:
        """
        Extract zip file and return list of extracted file paths
        """
        extracted_files = []
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                extracted_files = [os.path.join(extract_dir, name) for name in zip_ref.namelist()]
                print(f"Extracted {len(extracted_files)} files from {zip_path}")
        except Exception as e:
            print(f"Error extracting zip file {zip_path}: {str(e)}")
        
        return extracted_files


    def _upload_file_to_spaces(self, client, bucket_name: str, file_path: str, object_key: str) -> bool:
        """
        Upload a file to Digital Ocean Spaces
        """
        try:
            with open(file_path, 'rb') as file_data:
                client.upload_fileobj(
                    file_data,
                    bucket_name,
                    object_key,
                    ExtraArgs={'ACL': 'private'}  # Set appropriate ACL
                )
            print(f"Successfully uploaded {file_path} to {bucket_name}/{object_key}")
            return True
        except ClientError as e:
            print(f"Error uploading file to Digital Ocean Spaces: {str(e)}")
            return False

    
    def scrape_download_files(self, tender_id, url_template, do_spaces_config: Dict[str,str], bucket_name: str) -> List[Dict]:
        """
        Download files for a single tender
        
        Args:
            tender_id: The tender ID to download files for
            download_url_template: URL template with {tender_id} placeholder
            
        Returns:
            List[Dict]: Information about downloaded files
        """
        if not hasattr(self, 'driver'):
            print("Driver not initialized. Please login first.")
            return []

        client = self._set_up_do_spaces_(do_spaces_config)
        if not client:
                print("Failed to connect to Digital Ocean Spaces")
                return [{'status': 'error', 'error': 'DO Spaces setup failed'}]

        downloaded_files = []

        try:
                # Construct URL
                tender_url = url_template.replace("{tender_id}", tender_id) if url_template else \
                    f"https://www.vendorpanel.com.au/Members/iFramePopIziModal.aspx?pageSrc=/Members/VendorDownloadOpportunityPackage.aspx|||opportunityId={tender_id}"

                print(f"Navigating to tender page: {tender_url}")
                self.driver.get(tender_url)
                
                # Wait for iframe and switch to it
                iframe = WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "iframe"))
                )
                self.driver.switch_to.frame(iframe)

                # Find the "Download All" button by ID or text — adjust selector as needed
                download_button = WebDriverWait(self.driver, self.timeout).until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        "//input[@id='btnGo' or @name='PopUpMaster$masterMain$btnGo' or contains(@class, 'formBtnBlue')]"
                    ))
                )

                # Clear download directory before downloading
                if os.path.exists(self.download_dir):
                    for file in os.listdir(self.download_dir):
                        file_path = os.path.join(self.download_dir, file)
                        if os.path.isfile(file_path):
                            os.remove(file_path)

                # Click the download button
                print("Clicking download button")
                self.driver.execute_script("arguments[0].click();", download_button)

                # Wait for file(s) to be downloaded
                downloaded_path = self._download_wait_(timeout=120)

                if not downloaded_path:
                    return [{'status': 'error', 'error': 'Download failed or timed out'}]

                if downloaded_path.lower().endswith('.zip'):
                    # Extract the zip
                    extract_dir = os.path.join(self.download_dir, f"extracted_{tender_id}")
                    os.makedirs(extract_dir, exist_ok=True)
                    extracted_files = self._extract_zip_file(downloaded_path, extract_dir)

                    if not extracted_files:
                        return [{'status': 'error', 'error': 'No files extracted from zip or null files'}]

                    for file_path in extracted_files:
                        
                        if os.path.isfile(file_path):
                        
                            filename = os.path.basename(file_path)
                            object_key = f"{tender_id}/{filename}"
                            upload_success = self._upload_file_to_spaces(client, bucket_name, file_path, object_key)

                            downloaded_files.append({
                                'filename': filename,
                                'local_path': file_path,
                                'file_size': os.path.getsize(file_path),
                                'status': 'uploaded' if upload_success else 'upload_failed',
                                'spaces_path': object_key if upload_success else None
                        })
                else:
                    # If not a zip, upload directly
                    if os.path.isfile(downloaded_path):
                    
                        filename = os.path.basename(downloaded_path)
                        object_key = f"{tender_id}/{filename}"
                        upload_success = self._upload_file_to_spaces(client, bucket_name, downloaded_path, object_key)

                        downloaded_files.append({
                            'filename': filename,
                            'local_path': downloaded_path,
                            'file_size': os.path.getsize(downloaded_path),
                            'status': 'uploaded' if upload_success else 'upload_failed',
                            'spaces_path': object_key if upload_success else None
                        })
                    else:
                        downloaded_files.append({
                            'status': 'error',
                            'error': f'Downloaded path is not a file: {downloaded_path}'
                        })

        except Exception as e:
                print(f"Error in scrape_download_files: {str(e)}")
                import traceback
                traceback.print_exc()
                downloaded_files.append({
                    'status': 'error',
                    'error': str(e)
                })

        return downloaded_files
            
        
    
    
    
    def download_tender_files_bulk(self, tender_ids: List[str], url_template: str, do_spaces_config: Dict[str, str], bucket_name) -> List[Dict]:
        """
        Download files for multiple tenders from a given URL and upload to Digital Ocean Spaces
        
        Args:
            tender_ids: List of tender IDs to process
            download_url: URL where the download functionality is available
            do_spaces_config: Digital Ocean Spaces configuration
            
        Returns:
            List[Dict]: Results for each tender processed
        """
        if not hasattr(self, 'driver'):
            print("Driver not initialized. Please login first.")
            return []



        # Set up Digital Ocean Spaces client
        spaces_client = self._set_up_do_spaces_(do_spaces_config)
        if not spaces_client:
            return [{"error": "Failed to initialize Digital Ocean Spaces client"}]

        results = []
        bucket_name = do_spaces_config.get('bucket_name')
        
        for tender_id in tender_ids:
            tender_result = {
                "tender_id": tender_id,
                "status": "processing",
                "files_uploaded": [],
                "errors": []
            }
            
            try:
                print(f"Processing tender ID: {tender_id}")
                
                
                
                # Wait for download to complete
                downloaded_files = self.scrape_download_files(
                    tender_id=tender_id, 
                    url_template=url_template, 
                    do_spaces_config=do_spaces_config, 
                    bucket_name=bucket_name)
                
                if not downloaded_files:
                    tender_result["status"] = "error"
                    tender_result["errors"].append("Download timeout or failed")
                    results.append(tender_result)
                    continue
                
                print(f"Downloaded file: {downloaded_files}")
                
                for file_info in downloaded_files:
                    if file_info.get('status') == 'error':
                        tender_result["errors"].append(file_info.get('error', 'Unknown error'))
                    elif file_info.get('status') == 'uploaded':
                        tender_result["files_uploaded"].append({
                            "filename": file_info.get('filename'),
                            "object_key": file_info.get('spaces_path'),
                            "file_size": file_info.get('file_size'),
                            "local_path": file_info.get('local_path')
                        })
                    elif file_info.get('status') == 'upload_failed':
                        tender_result["errors"].append(f"Failed to upload {file_info.get('filename', 'unknown file')}")
                
                # Set final status
                if tender_result["files_uploaded"]:
                    tender_result["status"] = "completed"
                else:
                    tender_result["status"] = "error"
                    if not tender_result["errors"]:
                        tender_result["errors"].append("No files were successfully uploaded")
                        
            except Exception as e:
                print(f"Error processing tender {tender_id}: {str(e)}")
                import traceback
                traceback.print_exc()
                tender_result["status"] = "error"
                tender_result["errors"].append(str(e))
            
            results.append(tender_result)
            
            # Add delay between tenders
            time.sleep(2)
        
        return results

### API ENDPOINTS

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/login", response_model=dict)
async def login_to_vendor_panel(request: LoginRequest):
    """
    Endpoint to log in to VendorPanel
    """
    try:
        async with TenderScraper(use_selenium=True) as scraper:
            success = await scraper._login_(
                email=request.email,
                password=request.password,
                login_url=str(request.login_url)
            )
            
            if success:
                return {"status": "success", 
                        "message": "Successfully logged in"}
            else:
                raise HTTPException(status_code=401, detail="Login failed")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during login: {str(e)}")

@app.post("/scrape")

async def scrape_vendor_panel_tenders(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Endpoint to login to VendorPanel and scrape tender information.
    Initially returns a simple message, then sends data to webhook if provided.
    """
    # First, return a simple message immediately
    if request.webhook_url:
        # Schedule the scraping to happen in the background
        background_tasks.add_task(
            scrape_vendor_panel_tenders,
            request.email,
            request.password,
            str(request.login_url),
            str(request.target_url),
            str(request.webhook_url)
        )
        
        return {
            "status": "processing",
            "message": "The scraping process has started. Results will be sent to the provided webhook URL when complete.",
            "webhook_url": str(request.webhook_url)
        }
    else:
        # If no webhook is provided, return a message asking for one
        return {
            "status": "error",
            "message": "Please provide a webhook_url to receive the scraped data",
        }

async def scrape_vendor_panel_tenders(email: str, password: str, login_url: str, target_url: str, webhook_url: str):
    """
    Endpoint to login to VendorPanel and scrape tender information
    """
    scraper = TenderScraper(use_selenium=True)
    
    try:
        print(f"Starting login process for: {email}")
        login_success = await scraper._login_(
            email=email,
            password=password,
            login_url=str(login_url)
        )
        
        if not login_success:
            raise HTTPException(status_code=401, detail="Login failed")
        
        print("Login successful, proceeding to scrape tenders")
        tenders = await scraper.scrape_tenders(str(target_url))
        
        if not tenders:
            print("No tenders found")
            await scraper.send_to_webhook(webhook_url, tenders)
            return []
        
        await scraper.send_to_webhook(webhook_url, tenders)
    
    except Exception as e:
        print(f"Error during scraping process: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during scraping: {str(e)}")
    finally:
        # Clean up Selenium resources
        if hasattr(scraper, 'driver'):
            try:
                scraper.driver.quit()
                print("WebDriver closed successfully")
            except Exception as cleanup_error:
                print(f"Error closing WebDriver: {str(cleanup_error)}")

@app.post("/scrape_description", response_model=Dict)
async def scrape_tender_description(request: ScrapeTenderDescription):
    """
    Endpoint to scrape specific tender details: opening date, decision date, and details
    """  
    scraper = TenderScraper(use_selenium=True)

    try:
        print(f"Starting login process for: {request.email}")
        login_success = await scraper._login_(
            email=request.email,
            password=request.password,
            login_url=str(request.login_url)
        )

        if not login_success:
            raise HTTPException(status_code=401, detail="Login failed")
        
        print("Login successful, proceeding to scrape tender details")

        tender_details = await scraper.scrape_tender_description(str(request.tender_id))

        if not tender_details or len(tender_details) <= 1:  # Only has tender_id
            raise HTTPException(status_code=404, detail="No tender details found")
        
        return tender_details

    except Exception as e:
        print(f"Error during scraping process: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during scraping: {str(e)}")
    finally:
        # Clean up Selenium resources
        if hasattr(scraper, 'driver'):
            try:
                scraper.driver.quit()
                print("WebDriver closed successfully")
            except Exception as cleanup_error:
                print(f"Error closing WebDriver: {str(cleanup_error)}")



@app.post("/follow_button_click", response_model=Dict)
async def follow_button_click(request: ScrapeTenderDescription):
    """
    Endpoint to click the follow button for a specific tender
    """
    scraper = TenderScraper(use_selenium=True)

    try:
        print(f"Starting login process for: {request.email}")
        login_success = await scraper._login_(
            email=request.email,
            password=request.password,
            login_url=str(request.login_url)
        )

        if not login_success:
            raise HTTPException(status_code=401, detail="Login failed")
        
        print("Login successful, proceeding to click follow button")

        success = await scraper.follow_button_click(str(request.tender_id))

        if not success ["success"]:
            error_type = success.get("error", "unknown_error")
            if error_type == "button_not_clickable":
                raise HTTPException(status_code=400, detail="Follow button exists but is not clickable")
            elif error_type == "button_not_found":
                raise HTTPException(status_code=404, detail="Follow button not found on page")
            else:
                raise HTTPException(status_code=500, detail="Unknown error during follow button click")
        
        return {"status": "success", "message": "Follow button clicked successfully"}

    except Exception as e:
        print(f"Error during follow button click process: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during follow button click: {str(e)}")
    finally:
        # Clean up Selenium resources
        if hasattr(scraper, 'driver'):
            try:
                scraper.driver.quit()
                print("WebDriver closed successfully")
            except Exception as cleanup_error:
                print(f"Error closing WebDriver: {str(cleanup_error)}")



@app.post("/download_tender", response_model=List[Dict])
def download_tender_files_bulk_endpoint(request: ScrapeDownloadFiles):
    """
    Endpoint to download files for multiple tenders and upload to Digital Ocean Spaces
    
    Expected do_spaces_config:
    {
        "region": "syd1",
        "endpoint_url": "https://syd1.digitaloceanspaces.com", 
        "access_key": "your_access_key",
        "secret_key": "your_secret_key",
        "bucket_name": "your_bucket_name"
    }
    """
    scraper = TenderScraper(use_selenium=True)

    try:
        print(f"Starting login process for: {request.email}")
        login_success = scraper._login_(
            email=request.email,
            password=request.password,
            login_url=str(request.login_url)
        )

        if not login_success:
            raise HTTPException(status_code=401, detail="Login failed")
        
        print("Login successful, proceeding to download tender files")

        
        results = scraper.download_tender_files_bulk(
            tender_ids=request.tender_ids,
            url_template=request.url_template,
            do_spaces_config=request.do_spaces_config,
            bucket_name = request.do_spaces_config["bucket_name"]
        )

        return results

    except Exception as e:
        print(f"Error during bulk file download process: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during bulk file download: {str(e)}")
    finally:
        # Clean up Selenium resources
        if hasattr(scraper, 'driver'):
            try:
                scraper.driver.quit()
                print("WebDriver closed successfully")
            except Exception as cleanup_error:
                print(f"Error closing WebDriver: {str(cleanup_error)}")


#Uvicorn API local testing creation
if __name__ == "__main__":
    # Determine port - use environment variable if available
    port = int(os.environ.get("PORT", 8080))
    
    # Run the API server
    uvicorn.run("pvt-tenders-scraper:app", host="0.0.0.0", port=port, reload=False)

