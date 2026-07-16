from papermind.utils.docling_client import get_converter
from pathlib import Path
import hashlib
from concurrent.futures import ThreadPoolExecutor


EXPORT_PATH = Path("data/exports")
CACHE_DIR = Path("data/cache/parsed")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_pdf_hash(pdf_path: Path) -> str:
    return hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]


filenames = ["attention.pdf", "upskilling.pdf"]

converter = get_converter()


def parse_pdf_cached(pdf_path: Path) -> str:
    cache_key = get_pdf_hash(pdf_path)
    cache_file = CACHE_DIR / f"{cache_key}.md"

    if cache_file.exists():
        print(f"Cache hit for {pdf_path.name}")
        return cache_file.read_text()

    print(f"Parsing {pdf_path.name}...")
    result = converter.convert(pdf_path)
    md = result.document.export_to_markdown()

    cache_file.write_text(md)
    return md


def parse_single(filename: str) -> tuple[str, str]:
    PDF_PATH = Path("data/uploads") / filename
    md = parse_pdf_cached(PDF_PATH)
    with open(f"{EXPORT_PATH}/{filename[:-4]}.md", "w") as f:
        f.write(md)
    return filename, md


def parse_multiple(filenames: list[str], max_workers: int = 4) -> dict[str, str]:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(parse_single, file): file for file in filenames}
        results = {}
        for future in futures:
            filename, md = future.result()
            results[filename] = md
            with open(f"{EXPORT_PATH}/{filename[:-4]}.md", "w") as f:
                f.write(md)

    return results
