"""Entity graph from the hashed identifiers: which phone numbers, UPI IDs, accounts and handles are
advertised together, and which groups of them form seller networks.

    python -m graph.build store/redacted/posts.jsonl --labels store/annotations/gold.jsonl
    python -m graph.build store/redacted/posts.jsonl --with-channels --labels store/predictions/<run>.jsonl

Nodes are identifiers (TYPE:hash); two identifiers are linked when they appear in the same post, with
the number of such posts as the edge weight. With --with-channels, channel nodes are added and linked
to the identifiers posted there (shows sellers working across channels). Masked card numbers
(XXXX XXXX XXXX 1234) are left out: four digits are not enough to link on.

Outputs
  store/graph/entities.gexf               open in Gephi; nodes carry type, posts, channels, first/last
                                          seen, component, Louvain community, share of suspicious posts
  store/graph/{nodes,edges}.csv
  results/graph_summary.{csv,tex}         nodes and edges by type, components, modularity
  results/graph_components.{csv,tex}      size distribution of connected components
  results/graph_top_clusters.{csv,tex}    largest Louvain communities: identifiers, posts, channels,
                                          identifier types, dominant class, active dates
Only hashes and counts are written; the salt stays in .env, so the files hold no raw identifier.
"""
import argparse
import csv
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx

from common.io import iter_jsonl
from common.labels import SUSPICIOUS
from common.results import RESULTS_DIR, write_table


def node_id(ent: dict) -> str:
    return f"{ent['type']}:{ent['hash']}"


def load_labels(path) -> dict:
    """post_id -> class, from gold.jsonl (label) or a predictions file (pred)."""
    out = {}
    for r in iter_jsonl(path):
        lab = r.get("label") or r.get("pred")
        if lab:
            out[r["post_id"]] = lab
    return out


def build_graph(posts, labels: dict | None = None, with_channels: bool = False,
                max_posts_per_entity: int = 0) -> tuple[nx.Graph, dict, dict]:
    """Return the graph, {node: set(post_ids)} and {post_id: channel}."""
    labels = labels or {}
    G = nx.Graph()
    node_posts = defaultdict(set)
    node_channels = defaultdict(set)
    node_dates = defaultdict(list)
    post_nodes, post_channel = {}, {}
    for p in posts:
        nodes = sorted({node_id(e) for e in p.get("entities", []) if not (e.get("meta") or {}).get("partial")})
        if not nodes:
            continue
        post_nodes[p["post_id"]] = nodes
        post_channel[p["post_id"]] = p.get("channel", "")
        for n in nodes:
            node_posts[n].add(p["post_id"])
            node_channels[n].add(p.get("channel", ""))
            if p.get("date"):
                node_dates[n].append(p["date"])
    hubs = {n for n, ps in node_posts.items() if max_posts_per_entity and len(ps) > max_posts_per_entity}

    for n, ps in node_posts.items():
        if n in hubs:
            continue
        labs = [labels[x] for x in ps if x in labels]
        dates = sorted(node_dates[n])
        G.add_node(n, kind="entity", type=n.split(":")[0], posts=len(ps), channels=len(node_channels[n]),
                   first_seen=dates[0][:10] if dates else "", last_seen=dates[-1][:10] if dates else "",
                   labelled=len(labs), suspicious_share=(sum(x in SUSPICIOUS for x in labs) / len(labs)) if labs else -1.0,
                   top_label=Counter(labs).most_common(1)[0][0] if labs else "")
    for pid, nodes in post_nodes.items():
        nodes = [n for n in nodes if n not in hubs]
        for a, b in combinations(nodes, 2):
            w = G[a][b]["weight"] + 1 if G.has_edge(a, b) else 1
            G.add_edge(a, b, weight=w, kind="co_post")
    if with_channels:
        for n in list(G.nodes):
            for ch in node_channels[n]:
                c = f"CHANNEL:{ch}"
                if c not in G:
                    G.add_node(c, kind="channel", type="CHANNEL", posts=0, channels=1, first_seen="", last_seen="",
                               labelled=0, suspicious_share=-1.0, top_label="")
                G.add_edge(n, c, weight=1, kind="posted_in")
    return G, {n: ps for n, ps in node_posts.items() if n in G}, post_channel


def analyse(G: nx.Graph, node_posts: dict, post_channel: dict, labels: dict, seed: int = 13, resolution: float = 1.0, top: int = 20):
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    for i, comp in enumerate(comps):
        for n in comp:
            G.nodes[n]["component"] = i
    communities = nx.community.louvain_communities(G, weight="weight", seed=seed, resolution=resolution) \
        if G.number_of_edges() else [{n} for n in G]
    communities = sorted(communities, key=len, reverse=True)
    for i, com in enumerate(communities):
        for n in com:
            G.nodes[n]["community"] = i
    modularity = nx.community.modularity(G, communities, weight="weight") if G.number_of_edges() else 0.0

    entity_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "entity"]
    type_counts = Counter(G.nodes[n]["type"] for n in entity_nodes)
    edge_kinds = Counter(d["kind"] for _, _, d in G.edges(data=True))
    summary = [{"metric": "entity nodes", "value": len(entity_nodes)},
               *({"metric": f"  {t}", "value": c} for t, c in sorted(type_counts.items())),
               {"metric": "channel nodes", "value": G.number_of_nodes() - len(entity_nodes)},
               {"metric": "co-post edges", "value": edge_kinds.get("co_post", 0)},
               {"metric": "entity-channel edges", "value": edge_kinds.get("posted_in", 0)},
               {"metric": "connected components", "value": len(comps)},
               {"metric": "components with 2+ nodes", "value": sum(len(c) > 1 for c in comps)},
               {"metric": "largest component (nodes)", "value": len(comps[0]) if comps else 0},
               {"metric": "Louvain communities", "value": len(communities)},
               {"metric": "Louvain communities with 2+ nodes", "value": sum(len(c) > 1 for c in communities)},
               {"metric": "modularity", "value": round(modularity, 4)}]

    sizes = Counter(len(c) for c in comps)
    comp_rows = [{"component_size": s, "components": n, "nodes": s * n} for s, n in sorted(sizes.items())]

    cluster_rows = []
    for i, com in enumerate(communities[:top]):
        ents = [n for n in com if G.nodes[n]["kind"] == "entity"]
        posts = set().union(*(node_posts.get(n, set()) for n in ents)) if ents else set()
        labs = Counter(labels[p] for p in posts if p in labels)
        firsts = [G.nodes[n]["first_seen"] for n in ents if G.nodes[n]["first_seen"]]
        lasts = [G.nodes[n]["last_seen"] for n in ents if G.nodes[n]["last_seen"]]
        n_channels = len({post_channel.get(p, "") for p in posts})
        types = Counter(G.nodes[n]["type"] for n in ents)
        cluster_rows.append({
            "community": i, "identifiers": len(ents), "posts": len(posts), "channels": n_channels,
            "types": " ".join(f"{t}:{c}" for t, c in types.most_common()),
            "top_label": labs.most_common(1)[0][0] if labs else "",
            "suspicious_share": (sum(v for k, v in labs.items() if k in SUSPICIOUS) / sum(labs.values())) if labs else None,
            "first_seen": min(firsts) if firsts else "", "last_seen": max(lasts) if lasts else ""})
    return summary, comp_rows, cluster_rows


def export(G: nx.Graph, out_dir) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(G, out / "entities.gexf")
    cols = ["id", "kind", "type", "posts", "channels", "first_seen", "last_seen", "labelled", "suspicious_share",
            "top_label", "component", "community"]
    with open(out / "nodes.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for n, d in G.nodes(data=True):
            w.writerow([n] + [d.get(c, "") for c in cols[1:]])
    with open(out / "edges.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target", "weight", "kind"])
        for a, b, d in G.edges(data=True):
            w.writerow([a, b, d["weight"], d["kind"]])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Entity graph, components and Louvain clusters")
    ap.add_argument("posts", nargs="?", default="store/redacted/posts.jsonl")
    ap.add_argument("--labels", default="", help="gold.jsonl or a predictions JSONL, to colour clusters by class")
    ap.add_argument("--with-channels", action="store_true")
    ap.add_argument("--max-posts-per-entity", type=int, default=0,
                    help="drop identifiers seen in more posts than this (e.g. an official helpline)")
    ap.add_argument("--resolution", type=float, default=1.0, help="Louvain resolution")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out", default="store/graph")
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    args = ap.parse_args(argv)

    labels = load_labels(args.labels) if args.labels else {}
    G, node_posts, post_channel = build_graph(iter_jsonl(args.posts), labels, args.with_channels,
                                              args.max_posts_per_entity)
    summary, comps, clusters = analyse(G, node_posts, post_channel, labels, args.seed, args.resolution, args.top)
    export(G, args.out)
    write_table("graph_summary", summary, caption="Entity graph", results_dir=args.results_dir)
    write_table("graph_components", comps, caption="Connected component sizes", results_dir=args.results_dir)
    write_table("graph_top_clusters", clusters, caption="Largest Louvain communities", results_dir=args.results_dir)
    for r in summary:
        print(f"{r['metric']:36s} {r['value']}")
    print(f"Gephi file: {Path(args.out) / 'entities.gexf'}")


if __name__ == "__main__":
    main()
