import argparse
import chromadb
from sentence_transformers import SentenceTransformer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Search query")
    parser.add_argument("--db", default="chroma_tco_db")
    parser.add_argument("--chapter", default=None)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    model = SentenceTransformer("all-MiniLM-L6-v2")

    client = chromadb.PersistentClient(path=args.db)
    collection = client.get_collection("tco_records")

    query_embedding = model.encode([args.query]).tolist()[0]

    where_filter = None
    if args.chapter:
        where_filter = {"chapter": str(args.chapter)}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=args.top,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for i, (doc, meta, distance) in enumerate(zip(docs, metas, distances), start=1):
        print("=" * 80)
        print(f"Result {i}")
        print(f"Distance: {distance:.4f}")
        print(f"TCO: {meta.get('tco_number')}")
        print(f"Chapter: {meta.get('chapter')}")
        print(f"Tariff: {meta.get('tariff_classification')}")
        print(f"Source: {meta.get('source_url')}")
        print("")
        print(doc)


if __name__ == "__main__":
    main()
