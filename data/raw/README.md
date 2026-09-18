# Optional PDF corpus

Drop research PDFs here (e.g. FAO or IPCC reports you have downloaded) and run:

    python -m darukaa.kb.build

Each PDF is split into ~180-word overlapping chunks, tagged by domain keywords and embedded
alongside the curated evidence. Add a sidecar YAML with the same file name to give it a proper
citation, otherwise the file name is used:

```yaml
# data/raw/fao_soc_2017.yaml
id: fao_2017_soc_pdf
title: "Soil Organic Carbon: the hidden potential"
authors: FAO
publisher: Food and Agriculture Organization of the United Nations
year: 2017
type: report
tier: 1
url: https://www.fao.org/
```
