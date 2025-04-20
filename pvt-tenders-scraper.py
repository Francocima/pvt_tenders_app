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
            service=Service(ChromeDriverManager().install()),  # change to chromedriver_path to use in sevalla
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
        #Checkpoint to verify if the driver is initialized
        if not hasattr(self, 'driver'):
            print("Driver not initialized. Please login first.")
            return []

        try:
            print(f"Scraping tenders from: {target_url}")
            self.driver.get(target_url)

            # Wait for the page to load - See if the URL matches with the correct tenders_url
            
            WebDriverWait(self.driver, self.timeout).until(
                EC.any_of(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".dashboard-container")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".user-profile")),
                        EC.url_contains("Alerts:PublicTenders")   #Last flag to see if we are in the right page
                    ))
            print("Page loaded successfully")

            # get the page source and parse it with BS4
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # List to store tender information
            tenders = []

            # search for all the containers with the tenders
            tender_info_containers = soup.select('.stdAlertResultsNameCell')  #using the name of the class to get the containers
            print(f"Found {len(tender_info_containers)} tender containers")

                        
            # Loop through each container and extract the data
            for container in tender_info_containers:
                tender_data= {} # Dictionary to store tender data

                try: 
                    # tender title
                    tender_title = container.select_one('.alertResultName')
                    if tender_title:
                        tender_data['tender_title'] = tender_title.text.strip()

                    tender_id = container.select_one('a')['id']
                    if tender_id:
                        tender_data['tender_id'] = tender_id
                    
                    # Tender block information
                    info_block = container.select_one('.alertResultInfoBlock')
                    if info_block:
                        main_content = info_block.select_one('span:not(.alertResultAvatarBlock)')

                        if main_content:
                            full_text = str(main_content)

                            parts = full_text.split('<br/>')

                            if len(parts) >= 1:
                                tender_data['tender_org'] = BeautifulSoup(parts[0], 'html.parser').get_text(strip=True)

                            if len(parts) >= 2:
                                # Second part is location
                                tender_data['tender_location'] = BeautifulSoup(parts[1], 'html.parser').get_text(strip=True)
                                    
                            if len(parts) >= 3:
                                # Third part is postcode and country
                                postcode_text = BeautifulSoup(parts[2], 'html.parser').get_text(strip=True)
                                # Split by space to separate postcode from country
                                postcode_parts = postcode_text.split(' ', 1)
                                tender_data['tender_postcode'] = postcode_parts[0]

                    # Date extraction
                    date_block = container.find_next_sibling('td', class_ = 'stdAlertResultsActionCell')
                    if not date_block: 
                        parent_row = container.parent
                        if parent_row:
                           date_block = parent_row.select_one('.stdAlertResultsActionCell') 

                    if date_block:
                        date_info = date_block.select_one('.alertResultsActionInfoContainer')
                        if date_info:
                            date_text = date_info.get_text(strip=True)
                            
                            if "CLOSES:" in date_text:
                                tender_closing_date = date_text.split("CLOSES:", 1)[1].strip()
                                
                                date_time_parts = tender_closing_date.split(' ', 1)
                                if len(date_time_parts) >= 2:
                                    tender_data['tender_closing_date'] = date_time_parts[0].strip()
                                    tender_data['tender_closing_time'] = date_time_parts[1].strip() 


                    if tender_data:
                        tenders.append(tender_data)
                        print(f"Added tender: {tender_data.get('tender_title', 'Unnamed tender')}")
                
                except Exception as e:
                    print(f"Error extracting tender data: {str(e)}")
                    continue
                
            print(f"Successfully scraped {len(tenders)} tenders")
            return tenders

        except Exception as e:
            print(f"Error during scraping: {str(e)}")
        import traceback
        traceback.print_exc()
        return []



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


@app.post("/scrape", response_model=List[Dict])
async def scrape_vendor_panel_tenders(request: ScrapeRequest):
    """
    Endpoint to login to VendorPanel and scrape tender information
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
        
        print("Login successful, proceeding to scrape tenders")
        tenders = await scraper.scrape_tenders(str(request.target_url))
        
        if not tenders:
            return []
        
        return tenders
    
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



#Uvicorn API local testing creation
if __name__ == "__main__":
    # Determine port - use environment variable if available
    port = int(os.environ.get("PORT", 8080))
    
    # Run the API server
    uvicorn.run("pvt-tenders-scraper:app", host="0.0.0.0", port=port, reload=False)