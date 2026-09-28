#!/usr/bin/env python
"""
chunk_experiment.py

Tests different chunk configurations and records results.
Run after ingesting papers.
"""

import json
import sys
from papermind.ingestion.pipeline import ingest_pdf
from papermind.eval.evaluate import evaluate, print_report
from papermind.storage.database import init_db

# Test configurations
CONFIGS = [
    {"max_words": 100, "overlap_words": 0, "name": "100w_no_overlap"},
    {"max_words": 100, "overlap_words": 25, "name": "100w_25_overlap"},
    {"max_words": 200, "overlap_words": 0, "name": "200w_no_overlap"},
    {"max_words": 200, "overlap_words": 50, "name": "200w_50_overlap"},
    {"max_words": 300, "overlap_words": 0, "name": "300w_no_overlap"},
    {"max_words": 300, "overlap_words": 75, "name": "300w_75_overlap"},
]

PAPERS = [
    "data/uploads/attention.pdf",
    "data/uploads/upskilling.pdf",
]

def run_experiment(config, papers):
    """Run a single configuration and return evaluation results."""
    print(f"\n{'='*60}")
    print(f"Testing: {config['name']} (max_words={config['max_words']}, overlap={config['overlap_words']})")
    print(f"{'='*60}")
    
    # Clear database
    import shutil
    shutil.rmtree("data/chroma", ignore_errors=True)
    import os
    if os.path.exists("data/papermind.db"):
        os.remove("data/papermind.db")
    
    # Invalidate BM25 cache
    from papermind.retrieval.hybrid_search import invalidate_bm25_cache
    invalidate_bm25_cache()
    
    init_db()
    
    # Ingest papers
    total_chunks = 0
    for pdf in papers:
        result = ingest_pdf(pdf, run_extraction=False,
                           max_words=config["max_words"],
                           overlap_words=config["overlap_words"])
        print(f"  {result['paper_id']}: {result['chunks']} chunks")
        total_chunks += result["chunks"]
    
    if total_chunks == 0:
        print("  WARNING: No chunks created!")
        return {
            "config": config,
            "total_chunks": 0,
            "hit_rate": 0.0,
            "mrr": 0.0,
            "details": [],
        }
    
    print(f"  Total chunks: {total_chunks}")
    
    # Run evaluation
    with open("papermind/eval/eval_set.json") as f:
        eval_items = json.load(f)
    
    report = evaluate(eval_items, k=5)
    
    return {
        "config": config,
        "total_chunks": total_chunks,
        "hit_rate": report["hit_rate"],
        "mrr": report["mrr"],
        "details": report["details"],
    }


def main():
    results = []
    
    for config in CONFIGS:
        result = run_experiment(config, PAPERS)
        results.append(result)
    
    # Print summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"{'Config':<25} {'Chunks':>8} {'Hit Rate@5':>12} {'MRR':>8}")
    print("-" * 60)
    for r in results:
        c = r["config"]
        print(f"{r['config']['name']:<25} {r['total_chunks']:>8} {r['hit_rate']:>11.2%} {r['mrr']:>8.3f}")
    
    # Save results
    with open("chunk_experiment_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to chunk_experiment_results.json")


if __name__ == "__main__":
    main()