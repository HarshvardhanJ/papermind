#!/usr/bin/env python
"""
Download known papers from arXiv using direct PDF URLs.
"""

import requests
import time
from pathlib import Path

PAPERS = [
    # Transformers / Attention
    ("1706.03762", "Attention_Is_All_You_Need.pdf"),
    ("1810.04805", "BERT_Pre-training_of_Deep_Bidirectional_Transformers.pdf"),
    ("1907.11692", "RoBERTa_A_Robustly_Optimized_BERT_Pretraining_Approach.pdf"),
    ("1910.11075", "T5_Exploring_the_Limits_of_Transfer_Learning.pdf"),
    ("2005.14165", "GPT-3_Language_Models_are_Few-Shot_Learners.pdf"),
    ("2001.08361", "ELECTRA_Pre-training_Text_Encoders_as_Discriminators.pdf"),
    ("2106.09685", "Switch_Transformers_Scaling_to_Trillion_Parameter_Models.pdf"),
    ("2205.01068", "PaLM_Scaling_Language_Modeling_with_Pathways.pdf"),
    ("2302.09419", "LLaMA_Open_and_Efficient_Foundation_Language_Models.pdf"),
    ("2303.08774", "GPT-4_Technical_Report.pdf"),
    
    # Retrieval / RAG
    ("2005.11401", "REALM_Retrieval-Augmented_Language_Model_Pre-training.pdf"),
    ("2005.11401", "RAG_Retrieval-Augmented_Generation_for_Knowledge-Intensive_NLP.pdf"),
    ("2104.07567", "Dense_Passage_Retrieval_for_Open-Domain_Question_Answering.pdf"),
    ("2203.11441", "Atlas_Few-shot_Learning_with_Retrieval-Augmented_Language_Models.pdf"),
    ("2210.01283", "WebGPT_Browser-assisted_Question-Answering.pdf"),
    ("2302.09419", "Retrieval-Augmented_Generation_for_Large_Language_Models.pdf"),
    ("2305.10903", "REPLUG_Retrieval-Augmented_Language_Model_Pre-training.pdf"),
    ("2310.04418", "LongLoRA_Efficient_Fine-tuning_of_Long-Context_LLMs.pdf"),
    
    # Efficient Transformers
    ("2006.04768", "Longformer_The_Long-Document_Transformer.pdf"),
    ("2004.05150", "BigBird_Transformers_for_Longer_Sequences.pdf"),
    ("2106.08803", "Performer_Linear_Attention.pdf"),
    ("2106.08803", "Linear_Attention_Are_Transformers_Linear.pdf"),
    ("2203.02155", "FlashAttention_Fast_and_Memory-Efficient_Exact_Attention.pdf"),
    ("2307.08691", "FlashAttention-2_Faster_Attention_with_Better_Parallelism.pdf"),
    
    # Semantic Search / Embeddings
    ("1908.10084", "Sentence-BERT_Sentence_Embeddings_using_Siamese_BERT-Networks.pdf"),
    ("2004.14904", "SimCSE_Simple_Contrastive_Learning_of_Sentence_Embeddings.pdf"),
    ("2104.08821", "E5_Text_Embeddings_by_Weakly-Supervised_Contrastive_Learning.pdf"),
    ("2212.03554", "BGE_Embedding_Model.pdf"),
    ("2301.13238", "GTR_Generalizable_T5-based_Retrievers.pdf"),
    
    # Knowledge Distillation / Model Compression
    ("1402.1279", "Distilling_Knowledge_Neural_Networks.pdf"),
    ("1910.01108", "TinyBERT_Distilling_BERT_for_Natural_Language_Understanding.pdf"),
    ("2002.11251", "MobileBERT_Compact_Task-Agnostic_BERT.pdf"),
    ("2010.04635", "DistilBERT_Distilled_BERT_Smaller_Faster_Cheaper.pdf"),
    
    # Multimodal
    ("2103.00020", "CLIP_Learning_Transferable_Visual_Models.pdf"),
    ("2206.15389", "Flamingo_Visual_Language_Model_Few-Shot_Learning.pdf"),
    ("2304.14178", "LLaVA_Visual_Instruction_Tuning.pdf"),
    
    # Instruction Tuning / RLHF
    ("2203.02155", "InstructGPT_Training_Language_Models_to_Follow_Instructions.pdf"),
    ("2204.02311", "Constitutional_AI_Harmlessness_from_AI_Feedback.pdf"),
    ("2304.00712", "Alpaca_Strong_Instruction-Following_Model.pdf"),
    
    # Vector Databases / Similarity Search
    ("1702.08734", "Product_Quantization_for_Nearest_Neighbor_Search.pdf"),
    ("1905.09793", "HNSW_Efficient_Approximate_Nearest_Neighbor.pdf"),
    ("2101.07628", "DiskANN_Fast_Accurate_Billion-Scale_ANN.pdf"),
]

OUTPUT_DIR = Path("data/uploads")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://arxiv.org/pdf/"

def download_paper(arxiv_id, filename):
    """Download a paper PDF from arXiv."""
    url = f"{BASE_URL}{arxiv_id}.pdf"
    filepath = OUTPUT_DIR / filename
    
    if filepath.exists():
        print(f"  Skipping {filename} (already exists)")
        return True
    
    try:
        print(f"  Downloading {arxiv_id} -> {filename}")
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        size = filepath.stat().st_size
        print(f"  ✓ Downloaded {filename} ({size/1024:.1f} KB)")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to download {arxiv_id}: {e}")
        if filepath.exists():
            filepath.unlink()
        return False


def main():
    print(f"Downloading {len(PAPERS)} papers to {OUTPUT_DIR}")
    print("=" * 60)
    
    success = 0
    for arxiv_id, filename in PAPERS:
        if download_paper(arxiv_id, filename):
            success += 1
        time.sleep(2)  # Be nice to arXiv
    
    print("=" * 60)
    print(f"Successfully downloaded: {success}/{len(PAPERS)}")
    print(f"Total papers in {OUTPUT_DIR}: {len(list(OUTPUT_DIR.glob('*.pdf')))}")


if __name__ == "__main__":
    main()