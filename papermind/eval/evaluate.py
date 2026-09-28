"""
evaluate.py

Measures retrieval quality with no LLM involved, so it is fast, free
and deterministic.

An eval item is a question plus a list of "expected keywords". A
retrieved chunk counts as a correct hit if it contains ALL of the
expected keywords (case-insensitive). Keyword matching is used instead
of hardcoded chunk IDs because chunk IDs change whenever the chunking
parameters change -- which is exactly the thing you want to tune and
re-measure. A keyword-based ground truth survives re-chunking.

Metrics:
  Hit Rate@k : fraction of questions where at least one correct chunk
               appears in the top-k results.
  MRR        : mean of 1/rank of the first correct chunk (0 if none).
               1.0 means the right chunk is always ranked first.

Usage:
    python -m papermind.eval.evaluate papermind/eval/eval_set.json
"""

import json
import sys

from papermind.retrieval.reranker import hybrid_rerank_search


def is_hit(chunk_text: str, expected_keywords: list[str]) -> bool:
    text = chunk_text.lower()
    return all(kw.lower() in text for kw in expected_keywords)


def evaluate(eval_items: list[dict], k: int = 5, use_hybrid: bool = True, use_reranker: bool = True) -> dict:
    hits = 0
    reciprocal_ranks = []
    details = []

    for item in eval_items:
        results = hybrid_rerank_search(item["question"], top_k=k)
        rank = None
        for i, r in enumerate(results, start=1):
            if is_hit(r["text"], item["expected_keywords"]):
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
        "hit_rate": hits / n if n else 0.0,
        "mrr": sum(reciprocal_ranks) / n if n else 0.0,
        "details": details,
    }


def print_report(report: dict) -> None:
    print(f"\nRetrieval evaluation  (k={report['k']}, {report['num_questions']} questions)")
    print("-" * 60)
    for d in report["details"]:
        rank = d["rank_of_first_hit"]
        status = f"hit at rank {rank}" if rank else "MISS"
        print(f"  [{status:>14}]  {d['question']}")
    print("-" * 60)
    print(f"  Hit Rate@{report['k']}: {report['hit_rate']:.2%}")
    print(f"  MRR:          {report['mrr']:.3f}\n")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "papermind/eval/eval_set.json"
    try:
        with open(path) as f:
            items = json.load(f)
    except FileNotFoundError:
        sys.exit(f"{path} not found. Copy papermind/eval/eval_set.example.json to "
                 f"eval_set.json and write questions about YOUR ingested papers.")
    print_report(evaluate(items))
