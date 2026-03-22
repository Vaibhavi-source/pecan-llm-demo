# pecan-llm-demo

A GSoC 2026 demo pipeline that uses large language models to extract ecological trait and yield data from scientific PDFs and format it for ingestion into [BETYdb](https://www.betydb.org/).

## What it does

1. **Ingest** — Converts a scientific PDF to structured markdown using [Docling](https://github.com/DS4SD/docling)
2. **Extract** — Uses a multi-turn conversation with Claude (Anthropic API) to extract BETYdb fields:
   - Turn 1: Site information (name, coordinates, country)
   - Turn 2: Species (scientific name, common name)
   - Turn 3: Traits and yields (variable, mean, SE, n, units, date, treatment)
3. **Validate** — Validates all extracted fields against BETYdb schema using Pydantic models. Each field is labeled:
   - `EXTRACTED` — directly stated in the paper
   - `INFERRED` — derived or calculated from context
   - `UNRESOLVED` — not found or ambiguous
4. **Export** — Produces two outputs:
   - `output/extracted.json` — full intermediate representation with evidence quotes
   - `output/bety_upload.csv` — ready for BETYdb bulk upload

## Installation

```bash
pip install -r requirements.txt
```

Copy the example env file and add your Anthropic API key:

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
python demo.py data/papers/paper.pdf --doi 10.xxxx/xxxxx
```

Example:

```bash
python demo.py data/papers/miscanthus_yield.pdf --doi 10.1093/jxb/erp184
```

## Output

The pipeline prints a summary table showing extracted vs inferred vs unresolved field counts, and previews the BETYdb CSV rows:

```
EXTRACTION SUMMARY
==================
Field status breakdown (34 total fields):
  EXTRACTED  : 21
  INFERRED   : 8
  UNRESOLVED : 5

Site:
  name        : Rothamsted Research           [EXTRACTED / HIGH]
  lat         : 51.81                         [EXTRACTED / HIGH]
  ...
```

## Project Structure

```
pecan-llm-demo/
├── demo.py          # Main pipeline script
├── src/
│   ├── ingest.py    # PDF → markdown (Docling)
│   ├── extract.py   # LLM multi-turn extraction (Anthropic)
│   ├── validate.py  # Pydantic schema validation
│   └── export.py    # JSON + BETYdb CSV export
├── data/papers/     # Place input PDFs here
└── output/          # Generated outputs
```
