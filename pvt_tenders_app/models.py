from pydantic import BaseModel, HttpUrl
from typing import List, Dict

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
    webhook_url: str