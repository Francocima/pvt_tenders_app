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
    tender_id: str
    email: str
    password: str


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
    
        chromedriver_path = '/usr/local/bin/chromedriver'
        
        self.driver = webdriver.Chrome(
            service=Service(chromedriver_path),  # change to chromedriver_path to use in sevalla     ChromeDriverManager().install()
            options=chrome_options
        )
            
        # Set window size
        self.driver.set_window_size(1200, 720)
        
        # Execute JavaScript to mask WebDriver presence
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")    

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
    async def _login_ (self, email: str, password: str, login_url: str):
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
                
                # Get the page source and parse it with BS4
                page_source = self.driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                
                # Look for tender elements - rows with numeric IDs
                rows_with_ids = soup.find_all('tr', id=True)
                print(f"Found {len(rows_with_ids)} table rows with IDs")
            
                numeric_id_rows = [row for row in rows_with_ids if row.get('id', '').isdigit()]
                print(f"Found {len(numeric_id_rows)} table rows with numeric IDs")

                tender_info_containers = []
                if numeric_id_rows:
                    print("Using rows with numeric IDs")
                    tender_info_containers = numeric_id_rows
                else:
                    print("No tender rows found on this page")
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
                        # Locate the pagination container
                    pagination = self.driver.find_element(By.CLASS_NAME, "dt-custom-paging")
                    buttons = pagination.find_elements(By.TAG_NAME, "button")
                    
                    if len(buttons) >= 4:
                        next_button = buttons[2]  # Third button is "Next"
                        if "disabled" not in next_button.get_attribute("class") and not next_button.get_attribute("disabled"):
                            time.sleep(5)  # Wait for the next page to load
                            self.driver.execute_script("arguments[0].click();", next_button)
                            current_page += 1
                            time.sleep(5)  # Wait for the next page to load
                        else:
                            print(f"Next button is disabled. End of pagination at page {current_page}")
                            break
                    else:
                        print("Pagination buttons not found or malformed.")
                        break
                    
                except TimeoutException:
                    print(f"No more pages to scrape (next button not found), ended at page {current_page}")
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
                                tender_details['tender_location'] = content_text

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


    # File downloader WIP
    ### async def scrape_download_files(self, tender_id: str) -> List[Dict]:
        """
        Scrapes download files from the specified tender ID.
        
        Args:
            tender_id: The ID of the tender to scrape files from

        """
        # Use a temporary directory for downloads
        temp_download_folder = os.path.join(os.getcwd(), 'temp_downloads', tender_id)
        os.makedirs(temp_download_folder, exist_ok=True)
        
        # Set Chrome download preferences
        self.driver.command_executor._commands["send_command"] = ("POST", '/session/$sessionId/chromium/send_command')
        params = {
            'cmd': 'Page.setDownloadBehavior',
            'params': {
                'behavior': 'allow',
                'downloadPath': temp_download_folder
            }
        }
        self.driver.execute("send_command", params)
        
        tender_files_url = f"https://www.vendorpanel.com.au/Members/iFramePopModal.aspx?pageSrc=/Members/VendorDownloadOpportunityPackage.aspx|||opportunityId={tender_id}&amp;width=780px&amp;height=300px"

        downloaded_files = []
        uploaded_files = []

        try:
            print(f"Navigating to the tender files page: {tender_files_url}")
            self.driver.get(tender_files_url)

            # Wait for either the download button or content to appear
            WebDriverWait(self.driver, self.timeout).until(
                EC.any_of(
                    EC.presence_of_element_located((By.ID, "btnGo")),
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".opportunityPreviewContent")),
                    EC.url_contains("VendorDownloadOpportunityPackage")
                )
            )
            
            print("Page loaded successfully")

            # Try to find and click the download button
            try:
                download_button = WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.ID, "btnGo"))
                )
                
                # Now wait until it's actually VISIBLE
                WebDriverWait(self.driver, 10).until(
                    EC.visibility_of(download_button)
                )

                print("Button is present and visible, clicking via JavaScript...")
                self.driver.execute_script("arguments[0].click();", download_button)
                
                # Wait for download to complete
                print("Waiting for download to complete...")
                time.sleep(15)  # Give it time to download
                
                # Get list of files in the download directory
                downloaded_files = [os.path.join(temp_download_folder, f) for f in os.listdir(temp_download_folder) 
                                if os.path.isfile(os.path.join(temp_download_folder, f))]
                
                print(f"Downloaded {len(downloaded_files)} files")
                
                # Upload files to Digital Ocean Spaces
                if downloaded_files:
                    uploaded_files = self._upload_to_spaces(downloaded_files, tender_id)
                
                return uploaded_files
                
            except TimeoutException:
                print("No download button found")
                # Check if there's information about why download isn't available
                page_source = self.driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                info_text = soup.select_one('.opportunityPreviewContent')
                if info_text:
                    print(f"Download info: {info_text.text.strip()}")
                return []

        except Exception as e:
            print(f"Error during file download: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
        
        finally:
            # Clean up temporary files
            for file_path in downloaded_files:
                try:
                    os.remove(file_path)
                except:
                    pass

    ### def _upload_to_spaces(self, file_paths, tender_id):
        """
        Uploads files to Digital Ocean Spaces.
        
        Args:
            file_paths: List of local file paths to upload
            tender_id: The tender ID to use for folder naming
            
        Returns:
            List of dictionaries with file information
        """
        # Digital Ocean Spaces configuration -> in the future store the keys in a CDS scheme in snowflake
        spaces_region = 'syd1'  
        spaces_name = 'tenders'  
        spaces_endpoint = f'https://{spaces_name}.{spaces_region}.digitaloceanspaces.com' 
        spaces_access_key = 'DO80183FAJ87LC9ULBXZ'
        spaces_secret_key = 'vTImA7VBpIaeLryF+ZJ+m59IX7zlGyoqqIRCIKQ8i74'
        
        # Initialize the S3 client for Spaces
        session = boto3.session.Session()
        client = session.client('s3',
                            region_name=spaces_region,
                            endpoint_url=spaces_endpoint,
                            aws_access_key_id=spaces_access_key,
                            aws_secret_access_key=spaces_secret_key)
        
        uploaded_file_info = []
        
        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            
            # Create the key (path) in Spaces
            spaces_key = f"tenders/{tender_id}/{file_name}"
            
            try:
                # Upload file to Spaces
                client.upload_file(
                    file_path,
                    spaces_name,
                    spaces_key,
                    ExtraArgs={'ACL': 'public-read'}  # Set to 'public-read' if you want files to be publicly accessible
                )
                
                # Generate the URL for the uploaded file
                file_url = f"https://{spaces_name}.{spaces_region}.digitaloceanspaces.com/{spaces_key}"
                
                # Create file info dictionary
                file_info = {
                    'tender_id': tender_id,
                    'file_name': file_name,
                    'file_url': file_url,
                    'spaces_key': spaces_key,
                    'uploaded_at': datetime.now().isoformat()
                }
                
                uploaded_file_info.append(file_info)
                print(f"Uploaded {file_name} to Digital Ocean Spaces")
                
            except Exception as e:
                print(f"Error uploading {file_name} to Digital Ocean Spaces: {str(e)}")
        
        return uploaded_file_info


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

@app.post("/scrape_download_files", response_model=List[Dict])
async def download_tender_files(request: ScrapeDownloadFiles):
    """
    Endpoint to download files for a specific tender and upload to Digital Ocean Spaces
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
        
        print("Login successful, proceeding to download tender files")

        uploaded_files = await scraper.scrape_download_files(str(request.tender_id))

        if not uploaded_files:
            return []
        
        return uploaded_files

    except Exception as e:
        print(f"Error during file download process: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during file download: {str(e)}")
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

