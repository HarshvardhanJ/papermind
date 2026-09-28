"""
evaluate.py

Measures retrieval quality with no LLM involved, so it is fast, free
and deterministic.

An eval item is a question plus a list of "expected keywords". 
Two matching modes:
  - strict: chunk must contain ALL expected keywords (case-insensitive)
  - soft: chunk must contain AT LEAST ONE expected keyword (case-insensitive)

Keyword matching is used instead of hardcoded chunk IDs because chunk IDs 
change whenever the chunking parameters change -- which is exactly the thing 
you want to tune and re-measure. A keyword-based ground truth survives re-chunking.

Metrics:
  Hit Rate@k : fraction of questions where at least one correct chunk
               appears in the top-k results.
  MRR        : mean of 1/rank of the first correct chunk (0 if none).
               1.0 means the right chunk is always ranked first.

Usage:
    python -m papermind.eval.evaluate [--mode strict|soft] [--k N] [papermind/eval/eval_set.json]
"""

import json
import sys
import argparse

from papermind.retrieval.reranker import hybrid_rerank_search


def is_hit_strict(chunk_text: str, expected_keywords: list[str]) -> bool:
    """Strict match: ALL keywords must be present."""
    text = chunk_text.lower()
    return all(kw.lower() in text for kw in expected_keywords)


def is_hit_soft(chunk_text: str, expected_keywords: list[str]) -> bool:
    """Soft match: AT LEAST ONE keyword must be present."""
    text = chunk_text.lower()
    return any(kw.lower() in text for kw in expected_keywords)


# Backward compatibility
is_hit = is_hit_strict


def evaluate(eval_items: list[dict], k: int = 5, use_hybrid: bool = True, 
             use_reranker: bool = True, mode: str = "strict") -> dict:
    """
    Evaluate retrieval quality.
    
    Args:
        eval_items: List of dicts with "question" and "expected_keywords"
        k: Number of top results to consider
        use_hybrid: Use hybrid search (BM25 + dense)
        use_reranker: Apply cross-encoder reranking
        mode: "strict" (all keywords) or "soft" (any keyword)
    """
    hit_fn = is_hit_strict if mode == "strict" else is_hit_soft
    
    hits = 0
    reciprocal_ranks = []
    details = []

    for item in eval_items:
        results = hybrid_rerank_search(item["question"], top_k=k)
        rank = None
        for i, r in enumerate(results, start=1):
            if hit_fn(r["text"], item["expected_keywords"]):
                rank = i
                break

        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

        details.append({"question": item["question"], "rank_of_first_hit": rank})

    n = len(eval_items)
    return {
        "k": k,
        "num_questions": n,
        "mode": mode,
        "hit_rate": hits / n if n else 0.0,
        "mrr": sum(reciprocal_ranks) / n if n else 0.0,
        "details": details,
    }


def print_report(report: dict) -> None:
    print(f"\nRetrieval evaluation  (k={report['k']}, {report['num_questions']} questions, mode={report['mode']})")
    print("-" * 70)
    for d in report["details"]:
        rank = d["rank_of_first_hit"]
        status = f"hit at rank {rank}" if rank else "MISS"
        print(f"  [{status:>14}]  {d['question'][:80]}")
    print("-" * 70)
    print(f"  Hit Rate@{report['k']}: {report['hit_rate']:.2%}")
    print(f"  MRR:          {report['mrr']:.3f}\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluate PaperMind retrieval")
    parser.add_argument("eval_file", nargs="?", default="papermind/eval/eval_set.json",
                        help="Path to eval_set.json")
    parser.add_argument("--mode", choices=["strict", "soft"], default="strict",
                        help="Matching mode: strict (all keywords) or soft (any keyword)")
    parser.add_argument("-k", type=int, default=5, help="Top-k results to evaluate")
    args = parser.parse_args()

    try:
        with open(args.eval_file) as f:
            items = json.load(f)
    except FileNotFoundError:
        sys.exit(f"{args.eval_file} not found. Create eval_set.json with questions and expected_keywords.")

    report = evaluate(items, k=args.k, mode=args.mode)
    print_report(report)


if __name__ == "__main__":
    main()