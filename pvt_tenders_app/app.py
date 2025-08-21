from fastapi import FastAPI, BackgroundTasks, HTTPException
from typing import List, Dict
import traceback

from .models import (
    LoginRequest,
    ScrapeRequest,
    ScrapeTenderDescription,
    ScrapeDownloadFiles,
    ScrapeTenderDescriptionBatch,
    ScrapeTenderDescriptionBatchWebhook,
    PostTesting
)
from .scraper import TenderScraper

app = FastAPI(title="Tenders Scraper", version="1.0")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/login")
async def login(request: LoginRequest):
    try:
        async with TenderScraper() as scraper:
            success = scraper._login(
                email=request.email,
                password=request.password,
                login_url=str(request.login_url)
            )
            if success:
                return {"status": "success", "message": "Login successful"}
            raise HTTPException(status_code=401, detail="Login failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")


@app.post("/scrape")
async def scrape_tenders(request: ScrapeRequest, background_tasks: BackgroundTasks):
    if not request.webhook_url:
        raise HTTPException(status_code=400, detail="Missing webhook_url")

    background_tasks.add_task(
        run_scraper_background,
        request.email,
        request.password,
        str(request.login_url),
        str(request.target_url),
        str(request.webhook_url)
    )
    return {
        "status": "processing",
        "message": "Scraping started, results will be sent to webhook.",
        "webhook_url": request.webhook_url
    }


async def run_scraper_background(email: str, password: str, login_url: str, target_url: str, webhook_url: str):
    scraper = TenderScraper()
    try:
        if not scraper._login(email, password, login_url):
            raise Exception("Login failed")
        tenders = await scraper.scrape_tenders(target_url)
        await scraper.send_to_webhook(webhook_url, tenders or [])
    except Exception as e:
        print(f"[ERROR] Background scraping: {str(e)}")
    finally:
        if hasattr(scraper, "driver"):
            scraper.driver.quit()


@app.post("/scrape_description", response_model=Dict)
async def scrape_description(request: ScrapeTenderDescription):
    scraper = TenderScraper()
    try:
        if not scraper._login(request.email, request.password, request.login_url):
            raise HTTPException(status_code=401, detail="Login failed")
        details = await scraper.scrape_tender_description(request.tender_id)
        if not details:
            raise HTTPException(status_code=404, detail="Tender not found")
        return details
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping description: {str(e)}")
    finally:
        if hasattr(scraper, "driver"):
            scraper.driver.quit()


@app.post("/scrape_description_batch", response_model=Dict)
async def scrape_description_batch(request: ScrapeTenderDescriptionBatch):
    """
    Scrape tender descriptions for all provided tender_ids
    """
    scraper = TenderScraper()
    try:
        # Login once for the entire batch
        if not scraper._login(request.email, request.password, request.login_url):
            raise HTTPException(status_code=401, detail="Login failed")
        
        # Process all tender_ids
        results = await scraper.scrape_tender_description_batch(
            tender_ids=request.tender_ids,
            delay_between_requests=request.delay_between_requests
        )
        
        # Return results even if some failed
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during batch scraping: {str(e)}")
    finally:
        if hasattr(scraper, "driver"):
            scraper.driver.quit()


# new batch processing endpoint
@app.post("/scrape_description_batch_webhook")
async def scrape_description_batch(request: ScrapeTenderDescriptionBatchWebhook, background_tasks: BackgroundTasks):
    """
    Scrape tender descriptions for all provided tender_ids
    """
    if not hasattr(request, 'webhook_url') or not request.webhook_url:
        raise HTTPException(status_code=400, detail="Missing webhook_url")
    
    background_tasks.add_task(
        run_batch_scraper_background,
        request.email,
        request.password,
        str(request.login_url),
        request.tender_ids,
        request.delay_between_requests,
        str(request.webhook_url)
    )
    
    return {
        "status": "processing",
        "message": f"Batch scraping started for {len(request.tender_ids)} tenders, results will be sent to webhook.",
        "webhook_url": request.webhook_url
    }

async def run_batch_scraper_background(email: str, password: str, login_url: str, tender_ids: List[str], delay_between_requests: float, webhook_url: str):
    scraper = TenderScraper()
    try:
        if not scraper._login(email, password, login_url):
            raise Exception("Login failed")
        
        results = await scraper.scrape_tender_description_batch(
            tender_ids=tender_ids,
            delay_between_requests=delay_between_requests
        )
        
        await scraper.send_to_webhook(webhook_url, results)
        
    except Exception as e:
        print(f"[ERROR] Background batch scraping: {str(e)}")
    finally:
        if hasattr(scraper, "driver"):
            scraper.driver.quit()

@app.post("/follow_button_click", response_model=Dict)
async def follow_button_click(request: ScrapeTenderDescription):
    scraper = TenderScraper()
    try:
        if not scraper._login(request.email, request.password, request.login_url):
            raise HTTPException(status_code=401, detail="Login failed")
        result = await scraper.follow_button_click(request.tender_id)
        if not result or not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message", "Follow button error"))
        return {"status": "success", "message": result["message"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Follow button error: {str(e)}")
    finally:
        if hasattr(scraper, "driver"):
            scraper.driver.quit()


@app.post("/download_tender")
def download_tenders(request: ScrapeDownloadFiles, background_tasks: BackgroundTasks):
    if not request.webhook_url:
        raise HTTPException(status_code=400, detail="Missing webhook_url")

    background_tasks.add_task(
        run_download_background,
        request.email,
        request.password,
        str(request.login_url),
        request.tender_ids,
        str(request.url_template),
        request.do_spaces_config,
        str(request.webhook_url)
    )
    return {
        "status": "processing",
        "message": "Download started, results will be sent to webhook.",
        "webhook_url": request.webhook_url
    }


async def run_download_background(
    email: str, 
    password: str, 
    login_url: str, 
    tender_ids: List[str], 
    url_template: str, 
    do_spaces_config: Dict[str, str], 
    webhook_url: str
):
    scraper = TenderScraper()
    try:
        if not scraper._login(email, password, login_url):
            raise Exception("Login failed")
        
        results = scraper.download_tender_files_bulk(
            tender_ids=tender_ids,
            url_template=url_template,
            do_spaces_config=do_spaces_config,
            bucket_name=do_spaces_config["bucket_name"]
        )
        
        # Send results to webhook
        await scraper.send_to_webhook(webhook_url, results or [])
        
    except Exception as e:
        print(f"[ERROR] Background download: {str(e)}")
        # Optionally send error to webhook
        error_data = {"error": str(e), "status": "failed"}
        try:
            scraper.send_to_webhook(webhook_url, error_data)
        except:
            pass
    finally:
        if hasattr(scraper, "driver"):
            scraper.driver.quit()


@app.post("/post_testing")
async def process(data: PostTesting):

    try:    
        print("Data received:", data)
        return {"status": "ok"}  # <- make sure this is present

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}
    

@app.post("/check_compatibility")
async def check_compatibility():
    """Check Selenium and ChromeDriver compatibility"""
    try:
        import selenium
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        import subprocess
        import re
        
        compatibility_info = {
            "selenium_version": selenium.__version__,
            "compatibility_status": "unknown"
        }
        
        # Get Chrome browser version
        try:
            chrome_version_output = subprocess.check_output(
                ["google-chrome", "--version"], 
                stderr=subprocess.STDOUT, 
                universal_newlines=True
            )
            chrome_version = re.search(r'(\d+\.\d+\.\d+)', chrome_version_output).group(1)
            compatibility_info["chrome_browser_version"] = chrome_version
        except:
            try:
                # Alternative command for some systems
                chrome_version_output = subprocess.check_output(
                    ["chromium-browser", "--version"], 
                    stderr=subprocess.STDOUT, 
                    universal_newlines=True
                )
                chrome_version = re.search(r'(\d+\.\d+\.\d+)', chrome_version_output).group(1)
                compatibility_info["chrome_browser_version"] = chrome_version
            except:
                compatibility_info["chrome_browser_version"] = "unknown"
        
        # Get ChromeDriver version
        try:
            chromedriver_path = '/usr/local/bin/chromedriver'
            chromedriver_version_output = subprocess.check_output(
                [chromedriver_path, "--version"], 
                stderr=subprocess.STDOUT, 
                universal_newlines=True
            )
            chromedriver_version = re.search(r'(\d+\.\d+\.\d+)', chromedriver_version_output).group(1)
            compatibility_info["chromedriver_version"] = chromedriver_version
        except Exception as e:
            compatibility_info["chromedriver_version"] = "unknown"
            compatibility_info["chromedriver_error"] = str(e)
        
        # Check version compatibility
        if (compatibility_info.get("chrome_browser_version") != "unknown" and 
            compatibility_info.get("chromedriver_version") != "unknown"):
            
            chrome_major = int(compatibility_info["chrome_browser_version"].split('.')[0])
            chromedriver_major = int(compatibility_info["chromedriver_version"].split('.')[0])
            
            if chrome_major == chromedriver_major:
                compatibility_info["compatibility_status"] = "compatible"
            else:
                compatibility_info["compatibility_status"] = "version_mismatch"
                compatibility_info["recommendation"] = f"Update ChromeDriver to version {chrome_major}.x.x"
        
        # Selenium version compatibility notes
        selenium_version = compatibility_info["selenium_version"]
        if selenium_version.startswith("4."):
            compatibility_info["selenium_notes"] = "Selenium 4.x - Use Service class for driver management"
        elif selenium_version.startswith("3."):
            compatibility_info["selenium_notes"] = "Selenium 3.x - Legacy driver management"
        
        return {"status": "success", "compatibility_info": compatibility_info}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}