from fastapi import FastAPI, BackgroundTasks, HTTPException
from typing import List, Dict

from .models import (
    LoginRequest,
    ScrapeRequest,
    ScrapeTenderDescription,
    ScrapeDownloadFiles,
    ScrapeTenderDescriptionBatch
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


# new batch processing endpoint
@app.post("/scrape_description_batch")
async def scrape_description_batch(request: ScrapeTenderDescriptionBatch, background_tasks: BackgroundTasks):
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
