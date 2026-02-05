#!/usr/bin/env python3
"""
Web3 Job Hunter - A scraper for DeFi/Web3 job opportunities
Tailored for: Growth Lead, Community Manager, Marketing, BD, Partnerships roles
Author: witcheer
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import re
import json
import time
from urllib.parse import urljoin
import html
import os


# File to store previously seen jobs
SEEN_JOBS_FILE = "seen_jobs.json"


@dataclass
class JobOffer:
    """Represents a job offer"""
    title: str
    company: str
    url: str
    location: str
    posted_date: Optional[datetime]
    description: str
    source: str
    salary: Optional[str] = None
    tags: list = None
    is_new: bool = True  # Flag to indicate if this is a new job
    first_seen: Optional[str] = None  # Date when first seen

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class JobHunter:
    """Main job hunting class"""

    # Your profile criteria
    DESIRED_KEYWORDS = [
        'growth', 'community', 'marketing', 'communication', 'bd',
        'business development', 'partnerships', 'partner', 'relations',
        'social media', 'content', 'brand', 'ambassador', 'advocate',
        'engagement', 'ecosystem', 'strategy', 'lead', 'manager',
        'head of', 'director', 'defi', 'dune', 'analytics', 'data analyst',
        'research', 'writer', 'editor', 'pr', 'public relations'
    ]

    # Keywords to exclude (engineering roles)
    EXCLUDE_KEYWORDS = [
        'engineer', 'engineering', 'developer', 'solidity', 'rust',
        'backend', 'frontend', 'full stack', 'fullstack', 'smart contract',
        'devops', 'sre', 'infrastructure', 'architect', 'software',
        'python developer', 'java', 'golang', 'node.js', 'react developer',
        'blockchain developer', 'protocol engineer', 'security engineer',
        'qa engineer', 'test engineer', 'mobile developer', 'ios', 'android developer'
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        self.jobs: list[JobOffer] = []
        self.max_age_days = 30
        self.seen_jobs: dict = self._load_seen_jobs()

    def _load_seen_jobs(self) -> dict:
        """Load previously seen jobs from file"""
        if os.path.exists(SEEN_JOBS_FILE):
            try:
                with open(SEEN_JOBS_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_seen_jobs(self):
        """Save seen jobs to file"""
        # Update seen jobs with current jobs
        today = datetime.now().strftime("%Y-%m-%d")
        for job in self.jobs:
            job_key = job.url if job.url else f"{job.title}|{job.company}"
            if job_key not in self.seen_jobs:
                self.seen_jobs[job_key] = {
                    'first_seen': today,
                    'title': job.title,
                    'company': job.company
                }

        with open(SEEN_JOBS_FILE, 'w') as f:
            json.dump(self.seen_jobs, f, indent=2)

    def _mark_seen_jobs(self):
        """Mark jobs that were seen in previous runs"""
        for job in self.jobs:
            job_key = job.url if job.url else f"{job.title}|{job.company}"
            if job_key in self.seen_jobs:
                job.is_new = False
                job.first_seen = self.seen_jobs[job_key].get('first_seen', 'Unknown')

    def is_relevant_job(self, title: str, description: str = "") -> bool:
        """Check if job matches desired criteria"""
        text = f"{title} {description}".lower()

        # First check exclusions
        for keyword in self.EXCLUDE_KEYWORDS:
            if keyword in text:
                # Allow if it's clearly a non-engineering role with engineering in company name
                if keyword in ['engineer', 'engineering'] and any(k in text for k in ['marketing', 'growth', 'community', 'bd', 'partnerships']):
                    continue
                return False

        # Then check if it matches desired keywords
        for keyword in self.DESIRED_KEYWORDS:
            if keyword in text:
                return True

        return False

    def is_recent(self, posted_date: Optional[datetime]) -> bool:
        """Check if job was posted within the last month"""
        if posted_date is None:
            return True  # Include if we can't determine date
        cutoff = datetime.now() - timedelta(days=self.max_age_days)
        return posted_date >= cutoff

    def parse_relative_date(self, date_str: str) -> Optional[datetime]:
        """Parse relative dates like '2 days ago', '1 week ago'"""
        if not date_str:
            return None

        date_str = date_str.lower().strip()
        now = datetime.now()

        # Handle "today", "just now", "new"
        if any(x in date_str for x in ['today', 'just now', 'new', 'just posted']):
            return now

        # Handle "yesterday"
        if 'yesterday' in date_str:
            return now - timedelta(days=1)

        # Handle "X days/weeks/months ago"
        patterns = [
            (r'(\d+)\s*(?:day|d)\s*(?:ago)?', 'days'),
            (r'(\d+)\s*(?:week|w)\s*(?:ago)?', 'weeks'),
            (r'(\d+)\s*(?:month|mo)\s*(?:ago)?', 'months'),
            (r'(\d+)\s*(?:hour|hr|h)\s*(?:ago)?', 'hours'),
        ]

        for pattern, unit in patterns:
            match = re.search(pattern, date_str)
            if match:
                value = int(match.group(1))
                if unit == 'days':
                    return now - timedelta(days=value)
                elif unit == 'weeks':
                    return now - timedelta(weeks=value)
                elif unit == 'months':
                    return now - timedelta(days=value * 30)
                elif unit == 'hours':
                    return now - timedelta(hours=value)

        # Try to parse actual dates
        date_formats = [
            '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%B %d, %Y', '%b %d, %Y',
            '%d %B %Y', '%d %b %Y'
        ]
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None

    def fetch_page(self, url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
        """Fetch and parse a webpage"""
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            print(f"  ⚠️  Error fetching {url}: {e}")
            return None

    def scrape_web3_career(self):
        """Scrape web3.career"""
        print("🔍 Scraping web3.career...")

        # Focus on non-engineering categories
        categories = [
            'marketing', 'community', 'business-development',
            'growth', 'content', 'social-media', 'operations', 'non-tech'
        ]
        count = 0

        for category in categories:
            url = f"https://web3.career/{category}-jobs"
            soup = self.fetch_page(url)
            if not soup:
                continue

            # web3.career uses tr.table_row for job listings
            job_rows = soup.select('tr.table_row')

            for row in job_rows[:25]:
                try:
                    # Find all links in the row - first link with /number pattern is the job link
                    all_links = row.select('a[href]')
                    job_link = None
                    title = None
                    company = None

                    for link in all_links:
                        href = link.get('href', '')
                        # Job URLs have format: /job-title-company/12345
                        if re.search(r'/[^/]+-[^/]+/\d+$', href):
                            if not job_link:
                                job_link = href
                                title = link.get_text(strip=True)
                            elif not company:
                                company = link.get_text(strip=True)
                            break

                    if not title or not job_link:
                        continue

                    # Get company from second matching link if not found
                    if not company:
                        for link in all_links[1:3]:
                            href = link.get('href', '')
                            if re.search(r'/[^/]+-[^/]+/\d+$', href):
                                company = link.get_text(strip=True)
                                break

                    if not company:
                        company = "Unknown"

                    job_url = urljoin("https://web3.career", job_link)

                    # Get location from location links
                    location = "Remote"
                    location_links = row.select('a[href*="/web3-jobs-"]')
                    if location_links:
                        location_parts = [l.get_text(strip=True) for l in location_links[:2]]
                        location = ", ".join(location_parts) if location_parts else "Remote"

                    if self.is_relevant_job(title):
                        self.jobs.append(JobOffer(
                            title=title,
                            company=company,
                            url=job_url,
                            location=location,
                            posted_date=None,
                            description="",
                            source="web3.career",
                            tags=[category]
                        ))
                        count += 1
                except Exception:
                    continue

            time.sleep(0.5)

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_crypto_careers(self):
        """Scrape crypto-careers.com"""
        print("🔍 Scraping crypto-careers.com...")

        url = "https://crypto-careers.com/jobs"
        soup = self.fetch_page(url)
        if not soup:
            return

        job_cards = soup.select('.job-card, .job-listing, [class*="job"]')
        count = 0

        for card in job_cards[:50]:
            try:
                title_elem = card.select_one('h2, h3, .job-title, [class*="title"]')
                link_elem = card.select_one('a[href]')
                company_elem = card.select_one('.company, [class*="company"]')

                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                if not self.is_relevant_job(title):
                    continue

                job_url = urljoin("https://crypto-careers.com", link_elem.get('href', '')) if link_elem else ""
                company = company_elem.get_text(strip=True) if company_elem else "Unknown"

                self.jobs.append(JobOffer(
                    title=title,
                    company=company,
                    url=job_url,
                    location="Remote",
                    posted_date=None,
                    description="",
                    source="crypto-careers.com"
                ))
                count += 1
            except Exception:
                continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_cryptocurrencyjobs(self):
        """Scrape cryptocurrencyjobs.co"""
        print("🔍 Scraping cryptocurrencyjobs.co...")

        categories = ['marketing', 'community', 'business-development', 'operations']
        count = 0

        for category in categories:
            url = f"https://cryptocurrencyjobs.co/{category}/"
            soup = self.fetch_page(url)
            if not soup:
                continue

            job_items = soup.select('.job, .job-listing, article')

            for item in job_items[:20]:
                try:
                    title_elem = item.select_one('h2, h3, .title')
                    link_elem = item.select_one('a[href*="/job/"]')
                    company_elem = item.select_one('.company')
                    date_elem = item.select_one('time, .date')

                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not self.is_relevant_job(title):
                        continue

                    job_url = urljoin("https://cryptocurrencyjobs.co", link_elem.get('href', '')) if link_elem else ""
                    company = company_elem.get_text(strip=True) if company_elem else "Unknown"
                    date_str = date_elem.get_text(strip=True) if date_elem else ""
                    posted_date = self.parse_relative_date(date_str)

                    if self.is_recent(posted_date):
                        self.jobs.append(JobOffer(
                            title=title,
                            company=company,
                            url=job_url,
                            location="Remote",
                            posted_date=posted_date,
                            description="",
                            source="cryptocurrencyjobs.co",
                            tags=[category]
                        ))
                        count += 1
                except Exception:
                    continue

            time.sleep(0.5)

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_cryptojobslist(self):
        """Scrape cryptojobslist.com - uses API"""
        print("🔍 Scraping cryptojobslist.com...")
        count = 0

        # CryptoJobsList has a public API
        try:
            # Try the main jobs endpoint
            api_url = "https://cryptojobslist.com/api/jobs"
            headers = {
                **self.session.headers,
                'Accept': 'application/json',
                'Referer': 'https://cryptojobslist.com/'
            }
            response = self.session.get(api_url, headers=headers, timeout=15)

            if response.status_code == 200:
                data = response.json()
                jobs = data.get('jobs', data.get('data', data)) if isinstance(data, dict) else data

                if isinstance(jobs, list):
                    for job in jobs[:100]:
                        try:
                            title = job.get('title', job.get('name', ''))
                            if not self.is_relevant_job(title, job.get('description', '')):
                                continue

                            posted_str = job.get('postedAt', job.get('createdAt', job.get('date', '')))
                            posted_date = self.parse_relative_date(str(posted_str)) if posted_str else None

                            if self.is_recent(posted_date):
                                company = job.get('company', {})
                                company_name = company.get('name', 'Unknown') if isinstance(company, dict) else str(company)

                                self.jobs.append(JobOffer(
                                    title=title,
                                    company=company_name,
                                    url=job.get('url', job.get('link', f"https://cryptojobslist.com/jobs/{job.get('slug', job.get('id', ''))}")),
                                    location=job.get('location', 'Remote'),
                                    posted_date=posted_date,
                                    description=str(job.get('description', ''))[:200],
                                    source="cryptojobslist.com",
                                    salary=job.get('salary', None)
                                ))
                                count += 1
                        except Exception:
                            continue
        except Exception as e:
            print(f"  ⚠️  API failed, skipping: {e}")

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_jobstash(self):
        """Scrape jobstash.xyz"""
        print("🔍 Scraping jobstash.xyz...")

        # JobStash has an API
        api_url = "https://jobstash.xyz/api/jobs"
        count = 0

        try:
            response = self.session.get(api_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                jobs = data.get('data', data) if isinstance(data, dict) else data

                for job in jobs[:100] if isinstance(jobs, list) else []:
                    try:
                        title = job.get('title', '')
                        if not self.is_relevant_job(title, job.get('description', '')):
                            continue

                        posted_str = job.get('postedAt', job.get('created_at', ''))
                        posted_date = self.parse_relative_date(posted_str) if posted_str else None

                        if self.is_recent(posted_date):
                            self.jobs.append(JobOffer(
                                title=title,
                                company=job.get('company', {}).get('name', 'Unknown') if isinstance(job.get('company'), dict) else job.get('company', 'Unknown'),
                                url=job.get('url', f"https://jobstash.xyz/jobs/{job.get('id', '')}"),
                                location=job.get('location', 'Remote'),
                                posted_date=posted_date,
                                description=job.get('description', '')[:200],
                                source="jobstash.xyz",
                                salary=job.get('salary', None)
                            ))
                            count += 1
                    except Exception:
                        continue
        except Exception as e:
            # Fallback to HTML scraping
            soup = self.fetch_page("https://jobstash.xyz/jobs")
            if soup:
                job_cards = soup.select('[class*="job"], article')
                for card in job_cards[:30]:
                    try:
                        title_elem = card.select_one('h2, h3, [class*="title"]')
                        if not title_elem:
                            continue
                        title = title_elem.get_text(strip=True)
                        if self.is_relevant_job(title):
                            link = card.select_one('a[href]')
                            self.jobs.append(JobOffer(
                                title=title,
                                company=card.select_one('[class*="company"]').get_text(strip=True) if card.select_one('[class*="company"]') else "Unknown",
                                url=urljoin("https://jobstash.xyz", link.get('href', '')) if link else "",
                                location="Remote",
                                posted_date=None,
                                description="",
                                source="jobstash.xyz"
                            ))
                            count += 1
                    except Exception:
                        continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_remote3(self):
        """Scrape remote3.co"""
        print("🔍 Scraping remote3.co...")

        url = "https://remote3.co/web3-jobs"
        soup = self.fetch_page(url)
        count = 0

        if soup:
            job_cards = soup.select('.job-card, [class*="job"], article, .listing')

            for card in job_cards[:50]:
                try:
                    title_elem = card.select_one('h2, h3, [class*="title"]')
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not self.is_relevant_job(title):
                        continue

                    link = card.select_one('a[href]')
                    company_elem = card.select_one('[class*="company"]')
                    date_elem = card.select_one('time, [class*="date"]')

                    job_url = urljoin("https://remote3.co", link.get('href', '')) if link else ""
                    company = company_elem.get_text(strip=True) if company_elem else "Unknown"
                    date_str = date_elem.get_text(strip=True) if date_elem else ""
                    posted_date = self.parse_relative_date(date_str)

                    if self.is_recent(posted_date):
                        self.jobs.append(JobOffer(
                            title=title,
                            company=company,
                            url=job_url,
                            location="Remote",
                            posted_date=posted_date,
                            description="",
                            source="remote3.co"
                        ))
                        count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_beincrypto(self):
        """Scrape beincrypto.com/jobs"""
        print("🔍 Scraping beincrypto.com/jobs...")

        url = "https://beincrypto.com/jobs/"
        soup = self.fetch_page(url)
        count = 0

        if soup:
            job_listings = soup.select('.job-listing, [class*="job"], article')

            for listing in job_listings[:30]:
                try:
                    title_elem = listing.select_one('h2, h3, [class*="title"]')
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not self.is_relevant_job(title):
                        continue

                    link = listing.select_one('a[href]')
                    company_elem = listing.select_one('[class*="company"]')

                    self.jobs.append(JobOffer(
                        title=title,
                        company=company_elem.get_text(strip=True) if company_elem else "BeInCrypto",
                        url=urljoin("https://beincrypto.com", link.get('href', '')) if link else "",
                        location="Remote",
                        posted_date=None,
                        description="",
                        source="beincrypto.com"
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_greenhouse_board(self, company_name: str, board_url: str):
        """Scrape Greenhouse job boards (used by many companies)"""
        print(f"🔍 Scraping {company_name} jobs...")

        soup = self.fetch_page(board_url)
        count = 0

        if soup:
            # Greenhouse uses various selectors
            job_cards = soup.select('.opening, .job-post, [class*="job"], .position')

            for card in job_cards[:30]:
                try:
                    title_elem = card.select_one('a, h3, h4, [class*="title"]')
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not self.is_relevant_job(title):
                        continue

                    link = card.select_one('a[href]')
                    location_elem = card.select_one('.location, [class*="location"]')

                    self.jobs.append(JobOffer(
                        title=title,
                        company=company_name,
                        url=urljoin(board_url, link.get('href', '')) if link else board_url,
                        location=location_elem.get_text(strip=True) if location_elem else "Remote",
                        posted_date=None,
                        description="",
                        source=company_name
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_lever_board(self, company_name: str, board_url: str):
        """Scrape Lever job boards"""
        print(f"🔍 Scraping {company_name} jobs...")

        soup = self.fetch_page(board_url)
        count = 0

        if soup:
            job_cards = soup.select('.posting, [class*="posting"]')

            for card in job_cards[:30]:
                try:
                    title_elem = card.select_one('h5, [class*="title"], a')
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not self.is_relevant_job(title):
                        continue

                    link = card.select_one('a[href]')
                    location_elem = card.select_one('.location, [class*="location"]')

                    self.jobs.append(JobOffer(
                        title=title,
                        company=company_name,
                        url=link.get('href', '') if link else board_url,
                        location=location_elem.get_text(strip=True) if location_elem else "Remote",
                        posted_date=None,
                        description="",
                        source=company_name
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_ashby_board(self, company_name: str, board_url: str):
        """Scrape Ashby job boards (used by Solana, etc.)"""
        print(f"🔍 Scraping {company_name} jobs...")

        soup = self.fetch_page(board_url)
        count = 0

        if soup:
            # Ashby renders with JavaScript, but let's try
            job_cards = soup.select('[class*="job"], [class*="position"], [class*="opening"], a[href*="/jobs/"]')

            for card in job_cards[:30]:
                try:
                    if card.name == 'a':
                        title = card.get_text(strip=True)
                        link = card
                    else:
                        title_elem = card.select_one('h3, h4, a, [class*="title"]')
                        if not title_elem:
                            continue
                        title = title_elem.get_text(strip=True)
                        link = card.select_one('a[href]')

                    if not title or not self.is_relevant_job(title):
                        continue

                    self.jobs.append(JobOffer(
                        title=title,
                        company=company_name,
                        url=urljoin(board_url, link.get('href', '')) if link else board_url,
                        location="Remote",
                        posted_date=None,
                        description="",
                        source=company_name
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_dragonfly_jobs(self):
        """Scrape Dragonfly portfolio jobs"""
        print("🔍 Scraping Dragonfly portfolio jobs...")

        url = "https://jobs.dragonfly.xyz/jobs"
        soup = self.fetch_page(url)
        count = 0

        if soup:
            job_cards = soup.select('[class*="job"], article, .posting, a[href*="/job"]')

            for card in job_cards[:50]:
                try:
                    title_elem = card.select_one('h2, h3, h4, [class*="title"]') or card
                    title = title_elem.get_text(strip=True)

                    if not title or len(title) < 3 or not self.is_relevant_job(title):
                        continue

                    link = card if card.name == 'a' else card.select_one('a[href]')
                    company_elem = card.select_one('[class*="company"]')

                    self.jobs.append(JobOffer(
                        title=title,
                        company=company_elem.get_text(strip=True) if company_elem else "Dragonfly Portfolio",
                        url=urljoin("https://jobs.dragonfly.xyz", link.get('href', '')) if link else url,
                        location="Remote",
                        posted_date=None,
                        description="",
                        source="Dragonfly"
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_pantera_jobs(self):
        """Scrape Pantera Capital portfolio jobs"""
        self.scrape_greenhouse_board("Pantera Portfolio", "https://jobs.panteracapital.com/companies")

    def scrape_a16z_jobs(self):
        """Scrape a16z portfolio jobs"""
        print("🔍 Scraping a16z portfolio jobs...")

        url = "https://jobs.a16z.com"
        soup = self.fetch_page(url)
        count = 0

        if soup:
            job_cards = soup.select('[class*="job"], article, .posting, [class*="position"]')

            for card in job_cards[:50]:
                try:
                    title_elem = card.select_one('h2, h3, h4, [class*="title"], a')
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not self.is_relevant_job(title):
                        continue

                    link = card.select_one('a[href]')
                    company_elem = card.select_one('[class*="company"]')

                    self.jobs.append(JobOffer(
                        title=title,
                        company=company_elem.get_text(strip=True) if company_elem else "a16z Portfolio",
                        url=urljoin(url, link.get('href', '')) if link else url,
                        location="Remote",
                        posted_date=None,
                        description="",
                        source="a16z"
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_animoca_careers(self):
        """Scrape Animoca Brands careers"""
        self.scrape_greenhouse_board("Animoca Brands", "https://careers.animocabrands.com/jobs")

    def scrape_ethereum_jobs(self):
        """Scrape ethereumjobboard.com"""
        print("🔍 Scraping ethereumjobboard.com...")

        url = "https://ethereumjobboard.com/jobs"
        soup = self.fetch_page(url)
        count = 0

        if soup:
            # Try various selectors
            job_cards = soup.select('[class*="job"], article, .listing, a[href*="/job/"]')

            for card in job_cards[:50]:
                try:
                    if card.name == 'a':
                        title = card.get_text(strip=True)
                        link = card
                    else:
                        title_elem = card.select_one('h2, h3, h4, [class*="title"], a')
                        if not title_elem:
                            continue
                        title = title_elem.get_text(strip=True)
                        link = card.select_one('a[href]')

                    if not title or len(title) < 5 or not self.is_relevant_job(title):
                        continue

                    company_elem = card.select_one('[class*="company"]') if card.name != 'a' else None
                    date_elem = card.select_one('time, [class*="date"]') if card.name != 'a' else None

                    job_url = urljoin("https://ethereumjobboard.com", link.get('href', '')) if link else url
                    company = company_elem.get_text(strip=True) if company_elem else "Ethereum Ecosystem"
                    date_str = date_elem.get_text(strip=True) if date_elem else ""
                    posted_date = self.parse_relative_date(date_str)

                    if self.is_recent(posted_date):
                        self.jobs.append(JobOffer(
                            title=title,
                            company=company,
                            url=job_url,
                            location="Remote",
                            posted_date=posted_date,
                            description="",
                            source="ethereumjobboard.com"
                        ))
                        count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_bnbchain_jobs(self):
        """Scrape BNB Chain jobs"""
        self.scrape_ashby_board("BNB Chain", "https://jobs.bnbchain.org/jobs")

    def scrape_tron_careers(self):
        """Scrape TRON careers"""
        print("🔍 Scraping TRON careers...")

        url = "https://tron.network/career/corevalues/"
        soup = self.fetch_page(url)
        count = 0

        if soup:
            job_items = soup.select('[class*="job"], [class*="position"], [class*="career"], a[href*="career"]')

            for item in job_items[:30]:
                try:
                    title_elem = item.select_one('h2, h3, h4, [class*="title"]') or item
                    title = title_elem.get_text(strip=True)

                    if not title or len(title) < 5 or not self.is_relevant_job(title):
                        continue

                    link = item if item.name == 'a' else item.select_one('a[href]')

                    self.jobs.append(JobOffer(
                        title=title,
                        company="TRON",
                        url=urljoin("https://tron.network", link.get('href', '')) if link else url,
                        location="Remote",
                        posted_date=None,
                        description="",
                        source="TRON"
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_midnight_careers(self):
        """Scrape Midnight Network careers"""
        print("🔍 Scraping Midnight Network careers...")

        url = "https://midnight.network/careers"
        soup = self.fetch_page(url)
        count = 0

        if soup:
            job_items = soup.select('[class*="job"], [class*="position"], [class*="opening"], article, a[href*="career"], a[href*="job"]')

            for item in job_items[:30]:
                try:
                    title_elem = item.select_one('h2, h3, h4, [class*="title"]') or item
                    title = title_elem.get_text(strip=True)

                    if not title or len(title) < 5 or not self.is_relevant_job(title):
                        continue

                    link = item if item.name == 'a' else item.select_one('a[href]')

                    self.jobs.append(JobOffer(
                        title=title,
                        company="Midnight Network",
                        url=urljoin("https://midnight.network", link.get('href', '')) if link else url,
                        location="Remote",
                        posted_date=None,
                        description="",
                        source="Midnight"
                    ))
                    count += 1
                except Exception:
                    continue

        print(f"  ✅ Found {count} relevant jobs")

    def scrape_all(self):
        """Run all scrapers"""
        print("\n" + "="*60)
        print("🚀 WEB3 JOB HUNTER - Starting job search...")
        print("="*60 + "\n")
        print(f"📋 Profile: Growth, Marketing, BD, Partnerships, Community")
        print(f"📅 Filter: Jobs posted within last {self.max_age_days} days")
        print(f"🚫 Excluding: Engineering/Developer roles\n")
        print("-"*60)

        # Major job boards
        self.scrape_web3_career()
        time.sleep(1)

        self.scrape_crypto_careers()
        time.sleep(1)

        self.scrape_cryptocurrencyjobs()
        time.sleep(1)

        self.scrape_cryptojobslist()
        time.sleep(1)

        self.scrape_jobstash()
        time.sleep(1)

        self.scrape_remote3()
        time.sleep(1)

        self.scrape_beincrypto()
        time.sleep(1)

        # VC portfolio boards
        self.scrape_dragonfly_jobs()
        time.sleep(1)

        self.scrape_pantera_jobs()
        time.sleep(1)

        self.scrape_a16z_jobs()
        time.sleep(1)

        self.scrape_animoca_careers()
        time.sleep(1)

        # Protocol-specific boards
        self.scrape_ashby_board("Solana", "https://jobs.solana.com/jobs")
        time.sleep(1)

        self.scrape_ashby_board("Avalanche", "https://jobs.avax.network/jobs")
        time.sleep(1)

        self.scrape_greenhouse_board("Block", "https://block.xyz/careers/jobs")
        time.sleep(1)

        self.scrape_ethereum_jobs()
        time.sleep(1)

        self.scrape_bnbchain_jobs()
        time.sleep(1)

        self.scrape_tron_careers()
        time.sleep(1)

        self.scrape_midnight_careers()
        time.sleep(1)

        # Deduplicate jobs by URL
        seen_urls = set()
        unique_jobs = []
        for job in self.jobs:
            if job.url and job.url not in seen_urls:
                seen_urls.add(job.url)
                unique_jobs.append(job)
            elif not job.url:
                unique_jobs.append(job)

        self.jobs = unique_jobs

        # Mark previously seen jobs and save current jobs
        self._mark_seen_jobs()
        new_jobs_count = sum(1 for job in self.jobs if job.is_new)

        print("\n" + "-"*60)
        print(f"✨ Total unique jobs found: {len(self.jobs)}")
        print(f"🆕 New jobs (not seen before): {new_jobs_count}")
        print(f"👀 Previously seen jobs: {len(self.jobs) - new_jobs_count}")
        print("-"*60 + "\n")

        # Save seen jobs for next run
        self._save_seen_jobs()

    def generate_html_report(self, output_file: str = "job_report.html"):
        """Generate an HTML report of found jobs"""

        # Sort jobs: new jobs first, then by date (most recent first), then by source
        def sort_key(job):
            # New jobs come first (is_new=True -> 0, is_new=False -> 1)
            new_priority = 0 if job.is_new else 1
            if job.posted_date:
                return (new_priority, 0, -job.posted_date.timestamp(), job.source)
            return (new_priority, 1, 0, job.source)

        sorted_jobs = sorted(self.jobs, key=sort_key)

        # Count new jobs
        new_jobs_count = sum(1 for job in self.jobs if job.is_new)

        # Group by relevance/category
        categories = {
            'growth': [],
            'marketing': [],
            'community': [],
            'bd_partnerships': [],
            'other': []
        }

        for job in sorted_jobs:
            title_lower = job.title.lower()
            if 'growth' in title_lower:
                categories['growth'].append(job)
            elif any(k in title_lower for k in ['marketing', 'brand', 'content', 'social']):
                categories['marketing'].append(job)
            elif 'community' in title_lower:
                categories['community'].append(job)
            elif any(k in title_lower for k in ['bd', 'business development', 'partner', 'relations']):
                categories['bd_partnerships'].append(job)
            else:
                categories['other'].append(job)

        now = datetime.now()

        html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Web3 Job Report - {now.strftime("%Y-%m-%d")}</title>
    <style>
        :root {{
            --bg-primary: #0f0f23;
            --bg-secondary: #1a1a2e;
            --bg-card: #16213e;
            --text-primary: #e0e0e0;
            --text-secondary: #a0a0a0;
            --accent: #6366f1;
            --accent-hover: #818cf8;
            --success: #10b981;
            --warning: #f59e0b;
            --border: #2d2d44;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}

        header {{
            text-align: center;
            margin-bottom: 3rem;
            padding: 2rem;
            background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-card) 100%);
            border-radius: 16px;
            border: 1px solid var(--border);
        }}

        h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, var(--accent) 0%, #a855f7 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}

        .subtitle {{
            color: var(--text-secondary);
            font-size: 1.1rem;
        }}

        .stats {{
            display: flex;
            justify-content: center;
            gap: 2rem;
            margin-top: 1.5rem;
            flex-wrap: wrap;
        }}

        .stat {{
            background: var(--bg-primary);
            padding: 1rem 2rem;
            border-radius: 12px;
            border: 1px solid var(--border);
        }}

        .stat-value {{
            font-size: 2rem;
            font-weight: bold;
            color: var(--accent);
        }}

        .stat-label {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}

        .category {{
            margin-bottom: 2rem;
        }}

        .category-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1rem;
            padding: 1rem;
            background: var(--bg-secondary);
            border-radius: 12px;
            border-left: 4px solid var(--accent);
        }}

        .category-header h2 {{
            font-size: 1.3rem;
        }}

        .category-count {{
            background: var(--accent);
            color: white;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.9rem;
            font-weight: 600;
        }}

        .jobs-grid {{
            display: grid;
            gap: 1rem;
        }}

        .job-card {{
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid var(--border);
            transition: all 0.3s ease;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 1rem;
            align-items: start;
            position: relative;
        }}

        .job-card.seen-before {{
            opacity: 0.7;
            border-left: 3px solid var(--text-secondary);
        }}

        .job-card.is-new {{
            border-left: 3px solid var(--success);
        }}

        .job-card:hover {{
            border-color: var(--accent);
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(99, 102, 241, 0.15);
            opacity: 1;
        }}

        .new-badge {{
            background: var(--success);
            color: white;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            margin-left: 0.5rem;
            text-transform: uppercase;
        }}

        .seen-badge {{
            background: var(--text-secondary);
            color: var(--bg-primary);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            margin-left: 0.5rem;
        }}

        .job-info {{
            min-width: 0;
        }}

        .job-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
        }}

        .job-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-bottom: 0.75rem;
        }}

        .job-meta span {{
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }}

        .job-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.5rem;
        }}

        .tag {{
            background: var(--bg-primary);
            color: var(--text-secondary);
            padding: 0.25rem 0.75rem;
            border-radius: 6px;
            font-size: 0.8rem;
            border: 1px solid var(--border);
        }}

        .job-actions {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            align-items: flex-end;
        }}

        .apply-btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--accent);
            color: white;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            transition: all 0.2s ease;
            white-space: nowrap;
        }}

        .apply-btn:hover {{
            background: var(--accent-hover);
            transform: scale(1.02);
        }}

        .source-badge {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            background: var(--bg-primary);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
        }}

        .date-badge {{
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 500;
        }}

        .date-new {{
            background: rgba(16, 185, 129, 0.2);
            color: var(--success);
        }}

        .date-recent {{
            background: rgba(245, 158, 11, 0.2);
            color: var(--warning);
        }}

        .date-older {{
            background: var(--bg-primary);
            color: var(--text-secondary);
        }}

        .empty-state {{
            text-align: center;
            padding: 3rem;
            color: var(--text-secondary);
        }}

        footer {{
            text-align: center;
            margin-top: 3rem;
            padding: 2rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
            border-top: 1px solid var(--border);
        }}

        @media (max-width: 768px) {{
            .job-card {{
                grid-template-columns: 1fr;
            }}

            .job-actions {{
                flex-direction: row;
                justify-content: space-between;
                width: 100%;
            }}

            .stats {{
                gap: 1rem;
            }}

            .stat {{
                padding: 0.75rem 1rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔮 Web3 Job Report</h1>
            <p class="subtitle">Curated opportunities for witcheer | Generated {now.strftime("%B %d, %Y at %H:%M")}</p>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{len(self.jobs)}</div>
                    <div class="stat-label">Total Jobs</div>
                </div>
                <div class="stat">
                    <div class="stat-value" style="color: var(--success);">{new_jobs_count}</div>
                    <div class="stat-label">New Jobs</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(categories['growth'])}</div>
                    <div class="stat-label">Growth</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(categories['marketing'])}</div>
                    <div class="stat-label">Marketing</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(categories['community'])}</div>
                    <div class="stat-label">Community</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(categories['bd_partnerships'])}</div>
                    <div class="stat-label">BD & Partners</div>
                </div>
            </div>
        </header>

        <main>
'''

        category_names = {
            'growth': ('🚀 Growth', 'Growth Lead, Head of Growth, Growth Manager roles'),
            'marketing': ('📣 Marketing & Content', 'Marketing, Brand, Content, Social Media roles'),
            'community': ('👥 Community', 'Community Manager, Community Lead roles'),
            'bd_partnerships': ('🤝 BD & Partnerships', 'Business Development, Partnerships, Relations roles'),
            'other': ('✨ Other Relevant Roles', 'Other matching opportunities')
        }

        for cat_key, (cat_title, cat_desc) in category_names.items():
            jobs_in_cat = categories[cat_key]
            if not jobs_in_cat:
                continue

            html_content += f'''
            <section class="category">
                <div class="category-header">
                    <h2>{cat_title}</h2>
                    <span class="category-count">{len(jobs_in_cat)} jobs</span>
                </div>
                <div class="jobs-grid">
'''

            for job in jobs_in_cat:
                # Determine date badge class
                date_class = "date-older"
                date_text = "Unknown"
                if job.posted_date:
                    days_ago = (now - job.posted_date).days
                    if days_ago <= 3:
                        date_class = "date-new"
                        date_text = "New" if days_ago == 0 else f"{days_ago}d ago"
                    elif days_ago <= 14:
                        date_class = "date-recent"
                        date_text = f"{days_ago}d ago"
                    else:
                        date_text = f"{days_ago}d ago"

                # Escape HTML
                safe_title = html.escape(job.title)
                safe_company = html.escape(job.company)
                safe_location = html.escape(job.location)
                safe_source = html.escape(job.source)
                safe_url = html.escape(job.url) if job.url else "#"

                tags_html = ""
                if job.tags:
                    tags_html = '<div class="job-tags">' + ''.join(
                        f'<span class="tag">{html.escape(tag)}</span>' for tag in job.tags[:3]
                    ) + '</div>'

                salary_html = ""
                if job.salary:
                    salary_html = f'<span>💰 {html.escape(job.salary)}</span>'

                # New/Seen badge
                card_class = "job-card is-new" if job.is_new else "job-card seen-before"
                status_badge = '<span class="new-badge">NEW</span>' if job.is_new else f'<span class="seen-badge">Seen {job.first_seen}</span>'

                html_content += f'''
                    <article class="{card_class}">
                        <div class="job-info">
                            <h3 class="job-title">{safe_title}{status_badge}</h3>
                            <div class="job-meta">
                                <span>🏢 {safe_company}</span>
                                <span>📍 {safe_location}</span>
                                {salary_html}
                            </div>
                            {tags_html}
                        </div>
                        <div class="job-actions">
                            <a href="{safe_url}" target="_blank" rel="noopener" class="apply-btn">
                                Apply →
                            </a>
                            <span class="date-badge {date_class}">{date_text}</span>
                            <span class="source-badge">{safe_source}</span>
                        </div>
                    </article>
'''

            html_content += '''
                </div>
            </section>
'''

        html_content += f'''
        </main>

        <footer>
            <p>Generated by Web3 Job Hunter 🔮</p>
            <p>Profile: Growth Lead | Community Manager | Marketing | BD | Partnerships</p>
            <p>Sources: web3.career, cryptojobslist.com, cryptocurrencyjobs.co, jobstash.xyz, and more</p>
        </footer>
    </div>
</body>
</html>
'''

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"📄 Report saved to: {output_file}")
        return output_file


def main():
    """Main entry point"""
    hunter = JobHunter()
    hunter.scrape_all()

    if hunter.jobs:
        report_file = hunter.generate_html_report()
        print(f"\n🎉 Done! Open {report_file} in your browser to view your personalized job report.")
    else:
        print("\n😔 No matching jobs found. Try again later or adjust your criteria.")


if __name__ == "__main__":
    main()
