import networkx as nx

from graph.build import analyse, build_graph, export


def post(pid, ch, *ents, date="2026-01-01T00:00:00+00:00"):
    return {"post_id": pid, "channel": ch, "date": date,
            "entities": [{"type": t, "hash": h, **({"meta": {"partial": True}} if t == "CARD" else {})}
                         for t, h in ents]}


POSTS = [
    post("p1", "c1", ("PHONE", "a"), ("UPI", "b")),
    post("p2", "c2", ("UPI", "b"), ("HANDLE", "c")),            # links p1's ring across channels
    post("p3", "c2", ("PHONE", "x"), ("PHONE", "y")),
    post("p4", "c3", ("PHONE", "z")),
    post("p5", "c3", ("CARD", "masked")),                       # partial card: not a node
    post("p6", "c1", ("PHONE", "a"), ("UPI", "b")),
]
LABELS = {"p1": "mule_account_sale", "p2": "mule_account_sale", "p3": "benign", "p6": "card_sale"}


def test_graph_links_shared_identifiers():
    G, node_posts, post_channel = build_graph(POSTS, LABELS)
    assert "CARD:masked" not in G
    assert G["PHONE:a"]["UPI:b"]["weight"] == 2
    assert nx.has_path(G, "PHONE:a", "HANDLE:c") and not nx.has_path(G, "PHONE:a", "PHONE:x")
    assert G.nodes["UPI:b"]["posts"] == 3 and G.nodes["UPI:b"]["channels"] == 2
    assert G.nodes["UPI:b"]["suspicious_share"] == 1.0

    summary, comps, clusters = analyse(G, node_posts, post_channel, LABELS)
    s = {r["metric"]: r["value"] for r in summary}
    assert s["connected components"] == 3 and s["largest component (nodes)"] == 3
    assert {(r["component_size"], r["components"]) for r in comps} == {(1, 1), (2, 1), (3, 1)}
    top = clusters[0]
    assert top["identifiers"] == 3 and top["posts"] == 3 and top["channels"] == 2
    assert top["top_label"] == "mule_account_sale"


def test_channels_and_hub_filter(tmp_path):
    G, *_ = build_graph(POSTS, with_channels=True)
    assert G.has_edge("UPI:b", "CHANNEL:c1") and G.has_edge("UPI:b", "CHANNEL:c2")
    G2, *_ = build_graph(POSTS, max_posts_per_entity=2)
    assert "UPI:b" not in G2 and "PHONE:a" in G2

    G, node_posts, pc = build_graph(POSTS, LABELS)
    analyse(G, node_posts, pc, LABELS)
    export(G, tmp_path)
    back = nx.read_gexf(tmp_path / "entities.gexf")
    assert set(back.nodes) == set(G.nodes)
    assert (tmp_path / "nodes.csv").read_text().count("\n") == G.number_of_nodes() + 1
