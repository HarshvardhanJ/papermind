#!/usr/bin/env python
"""
Batch ingest all PDFs in data/uploads.
"""

import time
from pathlib import Path
from papermind.ingestion.pipeline import ingest_pdf
from papermind.storage.database import init_db

def main():
    init_db()
    
    pdfs = sorted(Path("data/uploads").glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs to ingest")
    print("=" * 60)
    
    results = []
    for pdf in pdfs:
        print(f"\nIngesting: {pdf.name}")
        try:
            result = ingest_pdf(str(pdf), run_extraction=True, max_words=200, overlap_words=50)
            results.append((pdf.name, result))
            print(f"  {result['status']}: {result['chunks']} chunks")
            if result['status'] == 'failed':
                print(f"  Error: {result['error']}")
        except Exception as e:
            print(f"  Exception: {e}")
            results.append((pdf.name, {"status": "exception", "error": str(e), "chunks": 0}))
        
        time.sleep(1)  # Small delay
    
    # Summary
    print("\n" + "=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)
    total_chunks = 0
    for name, result in results:
        status = result['status']
        chunks = result.get('chunks', 0)
        total_chunks += chunks
        print(f"  {name:<60} {status:<12} {chunks:>4} chunks")
    
    print(f"\nTotal papers: {len(results)}")
    print(f"Total chunks: {total_chunks}")
    
    # Save results
    import json
    with open("batch_ingest_results.json", "w") as f:
        json.dump([{"file": n, **r} for n, r in results], f, indent=2)


if __name__ == "__main__":
    main()