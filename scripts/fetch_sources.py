"""Download the open-access primary sources into data/raw/, then rebuild the knowledge base.

    python scripts/fetch_sources.py            # download missing PDFs + sidecar citations
    python scripts/fetch_sources.py --rebuild  # ...and run the knowledge-base build

The PDFs themselves are NOT committed (data/raw/*.pdf is git-ignored): they are large and
publicly available. This script makes the corpus reproducible from a clean checkout.
Each PDF gets a sidecar YAML so its chunks carry a real citation and evidence tier.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RAW = ROOT / "data" / "raw"

# (filename, url, sidecar citation metadata)
SOURCES = [
    (
        "fao_2017_soc_hidden_potential.pdf",
        "https://openknowledge.fao.org/server/api/core/bitstreams/b382a255-5bd5-4656-a8cd-e30fff1a8bfe/content",
        {
            "id": "fao_2017_soc_pdf",
            "title": "Soil Organic Carbon: the hidden potential (full report)",
            "authors": "FAO",
            "publisher": "Food and Agriculture Organization of the United Nations",
            "year": 2017,
            "type": "report",
            "tier": 1,
            "url": "https://openknowledge.fao.org/items/a9260c9f-71e8-46fa-a853-0d18f0de3bda",
        },
    ),
    (
        "ipcc_srccl_spm.pdf",
        "https://www.ipcc.ch/site/assets/uploads/sites/4/2022/11/SRCCL_SPM.pdf",
        {
            "id": "ipcc_srccl_spm_pdf",
            "title": "Climate Change and Land — Summary for Policymakers (SRCCL)",
            "authors": "IPCC",
            "publisher": "Intergovernmental Panel on Climate Change",
            "year": 2019,
            "type": "assessment",
            "tier": 1,
            "url": "https://www.ipcc.ch/srccl/",
        },
    ),
    (
        "ipbes_global_assessment_spm.pdf",
        "https://files.ipbes.net/ipbes-web-prod-public-files/2020-02/ipbes_global_assessment_report_summary_for_policymakers_en.pdf",
        {
            "id": "ipbes_2019_spm_pdf",
            "title": "Global Assessment Report on Biodiversity and Ecosystem Services — Summary for Policymakers",
            "authors": "IPBES",
            "publisher": "IPBES",
            "year": 2019,
            "type": "assessment",
            "tier": 1,
            "url": "https://www.ipbes.net/global-assessment",
        },
    ),
    (
        "fao_recarbonization_global_soils.pdf",
        "https://openknowledge.fao.org/server/api/core/bitstreams/9e167594-3d97-4486-b8c9-ed875985dc98/content",
        {
            "id": "fao_recsoil_pdf",
            "title": "RECSOIL: Recarbonization of global soils — a tool to support the implementation of the Koronivia Joint Work on Agriculture",
            "authors": "FAO",
            "publisher": "Food and Agriculture Organization of the United Nations",
            "year": 2019,
            "type": "report",
            "tier": 1,
            "url": "https://openknowledge.fao.org/items/bbca7c40-2723-4f0c-8057-6c450436b830",
        },
    ),
]

HEADERS = {"User-Agent": "darukaa-earth/0.1 (hackathon project; contact via repository)"}


def sidecar_text(meta: dict) -> str:
    lines = []
    for key, value in meta.items():
        lines.append(f"{key}: {value}" if not isinstance(value, str) else f'{key}: "{value}"')
    return "\n".join(lines) + "\n"


def fetch(force: bool = False) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    ok = 0
    for name, url, meta in SOURCES:
        pdf = RAW / name
        sidecar = pdf.with_suffix(".yaml")
        sidecar.write_text(sidecar_text(meta), encoding="utf-8")
        if pdf.exists() and not force:
            print(f"  have    {name} ({pdf.stat().st_size / 1e6:.1f} MB)")
            ok += 1
            continue
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if not data.startswith(b"%PDF"):
                print(f"  SKIP    {name}: not a PDF (got {data[:16]!r})")
                sidecar.unlink(missing_ok=True)
                continue
            pdf.write_bytes(data)
            print(f"  fetched {name} ({len(data) / 1e6:.1f} MB)")
            ok += 1
        except Exception as exc:
            print(f"  FAILED  {name}: {type(exc).__name__}: {exc}")
            sidecar.unlink(missing_ok=True)
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="rebuild the knowledge base afterwards")
    parser.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"Fetching {len(SOURCES)} open-access sources into {RAW}")
    count = fetch(args.force)
    print(f"{count}/{len(SOURCES)} available")
    if args.rebuild and count:
        from darukaa.kb.build import build

        build()
