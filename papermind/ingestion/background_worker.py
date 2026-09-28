"""
background_worker.py

Background ingestion worker that polls the database for pending papers
and processes them asynchronously. Provides status polling via the API.
"""

import time
import logging
from threading import Thread
from papermind.storage.database import init_db, get_session
from papermind.storage.models import Paper
from papermind.ingestion.pipeline import ingest_pdf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_pending_papers(poll_interval: int = 5):
    """
    Main worker loop: finds papers with 'pending' status and processes them.
    """
    logger.info("Starting background ingestion worker...")
    
    while True:
        try:
            with get_session() as session:
                # Find pending papers
                pending = session.query(Paper).filter(
                    Paper.ingestion_status == "pending"
                ).all()
                
                for paper in pending:
                    logger.info(f"Processing paper {paper.id} ({paper.filename})")
                    
                    # Update status to parsing
                    paper.ingestion_status = "parsing"
                    session.commit()
                    
                    try:
                        # Ingest with extraction
                        result = ingest_pdf(
                            f"data/uploads/{paper.filename}",
                            run_extraction=True
                        )
                        
                        # Refresh paper from DB
                        session.refresh(paper)
                        if result["status"] == "complete":
                            paper.ingestion_status = "complete"
                        elif result["status"] == "duplicate":
                            paper.ingestion_status = "duplicate"
                        else:
                            paper.ingestion_status = "failed"
                            paper.error_message = result.get("error", "Unknown error")
                        
                        session.commit()
                        logger.info(f"Paper {paper.id} completed with status: {paper.ingestion_status}")
                        
                    except Exception as e:
                        logger.error(f"Failed to process paper {paper.id}: {e}")
                        paper.ingestion_status = "failed"
                        paper.error_message = str(e)
                        session.commit()
            
        except Exception as e:
            logger.error(f"Worker error: {e}")
        
        time.sleep(poll_interval)


def start_worker(poll_interval: int = 5) -> Thread:
    """Start the background worker in a separate thread."""
    thread = Thread(target=process_pending_papers, args=(poll_interval,), daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    init_db()
    start_worker()
    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down worker...")