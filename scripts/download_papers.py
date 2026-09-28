#!/usr/bin/env python
"""
Download scientific papers from arXiv for testing PaperMind.
Searches for papers in relevant categories and downloads PDFs.
"""

import os
import time
import requests
import feedparser
from pathlib import Path
from urllib.parse import quote

# arXiv categories of interest
CATEGORIES = [
    "cs.CL",      # Computation and Language
    "cs.LG",      # Machine Learning
    "cs.AI",      # Artificial Intelligence
    "cs.IR",      # Information Retrieval
    "cs.CV",      # Computer Vision
    "stat.ML",    # Machine Learning (Statistics)
]

# Search queries for relevant papers
SEARCH_QUERIES = [
    "transformer attention mechanism",
    "large language model",
    "retrieval augmented generation",
    "semantic search embeddings",
    "knowledge distillation",
    "few shot learning",
    "instruction tuning",
    "RLHF reinforcement learning human feedback",
    "multimodal learning",
    "efficient transformer",
    "long context language model",
    "vector database similarity search",
]

OUTPUT_DIR = Path("data/uploads")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_PAPERS = 50
DOWNLOAD_DELAY = 3  # seconds between downloads (arXiv rate limit)


def search_arxiv(query, max_results=10):
    """Search arXiv for papers matching query."""
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{quote(query)}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    response = requests.get(url, params=params)
    return feedparser.parse(response.content)


def get_pdf_url(entry):
    """Extract PDF URL from arXiv entry."""
    for link in entry.links:
        if link.type == "application/pdf":
            return link.href
    return None


def download_paper(pdf_url, filename):
    """Download a paper PDF."""
    try:
        response = requests.get(pdf_url, stream=True, timeout=30)
        response.raise_for_status()
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  Failed to download {pdf_url}: {e}")
        return False


def sanitize_filename(title):
    """Create a safe filename from paper title."""
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return safe[:100] + ".pdf"


def main():
    downloaded = set()
    papers_downloaded = 0
    
    # Check existing files
    for f in OUTPUT_DIR.glob("*.pdf"):
        downloaded.add(f.stem)
    
    print(f"Already have {len(downloaded)} papers in {OUTPUT_DIR}")
    
    for query in SEARCH_QUERIES:
        if papers_downloaded >= MAX_PAPERS:
            break
            
        print(f"\nSearching for: {query}")
        feed = search_arxiv(query, max_results=15)
        
        for entry in feed.entries:
            if papers_downloaded >= MAX_PAPERS:
                break
                
            # Get paper ID from URL
            arxiv_id = entry.id.split("/")[-1]
            # Create expected filename to check if already downloaded
            title = entry.title.strip().replace("\n", " ")
            expected_filename = sanitize_filename(title)
            
            if expected_filename in downloaded:
                print(f"  Skipping {arxiv_id} (already downloaded)")
                continue
            
            pdf_url = get_pdf_url(entry)
            if not pdf_url:
                print(f"  No PDF for {arxiv_id}")
                continue
            
            filename = expected_filename
            filepath = OUTPUT_DIR / filename
            
            print(f"  Downloading: {title[:60]}... ({arxiv_id})")
            if download_paper(pdf_url, filepath):
                downloaded.add(filename)
                papers_downloaded += 1
                print(f"  ✓ Saved as {filename}")
            else:
                if filepath.exists():
                    filepath.unlink()
            
            time.sleep(DOWNLOAD_DELAY)
    
    print(f"\n{'='*60}")
    print(f"Downloaded {papers_downloaded} new papers")
    print(f"Total papers in {OUTPUT_DIR}: {len(list(OUTPUT_DIR.glob('*.pdf')))}")


if __name__ == "__main__":
    main()