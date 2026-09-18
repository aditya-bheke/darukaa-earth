"""Variable-interaction graph: explains *how* the diagnosed problems propagate to biodiversity."""

from collections import deque

from darukaa.schemas import CausalChain, Finding

TARGETS = {"species_richness", "pollinators", "crop_yield"}


def causal_chains(relationships: list[dict], findings: list[Finding], max_len: int = 4, limit: int = 5) -> list[CausalChain]:
    adj: dict[str, list[dict]] = {}
    for r in relationships:
        adj.setdefault(r["from_var"], []).append(r)

    starts = []
    for f in findings:
        for v in f.variables:
            if v in adj and v not in starts:
                starts.append(v)

    chains: list[CausalChain] = []
    seen_paths = set()
    for start in starts:
        queue = deque([(start, [start], [], [])])
        while queue:
            node, path, mechs, evs = queue.popleft()
            if node in TARGETS and len(path) > 1:
                key = tuple(path)
                if key not in seen_paths:
                    seen_paths.add(key)
                    chains.append(CausalChain(path=path, mechanisms=mechs, evidence_ids=evs))
                continue
            if len(path) >= max_len:
                continue
            for edge in adj.get(node, []):
                if edge["to_var"] in path:
                    continue
                queue.append((edge["to_var"], path + [edge["to_var"]],
                              mechs + [f"{edge['from_var']} {edge['sign']}→ {edge['to_var']}: {edge['mechanism']}"],
                              evs + [edge["evidence_id"]]))
    # prefer longer (multi-variable) chains, then distinct starting variables
    chains.sort(key=lambda c: -len(c.path))
    picked, used_starts = [], set()
    for c in chains:
        if c.path[0] in used_starts and len(picked) < len(starts):
            continue
        # drop chains that are just the tail of a longer chain already shown
        if any(len(o.path) > len(c.path) and o.path[-len(c.path):] == c.path for o in picked):
            continue
        picked.append(c)
        used_starts.add(c.path[0])
        if len(picked) >= limit:
            break
    return picked
