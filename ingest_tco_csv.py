
import argparse

import os

import pandas as pd

import chromadb

from sentence_transformers import SentenceTransformer

def clean_value(value):

    if pd.isna(value):

        return ""

    return str(value).strip()

def make_document(row):

    return "\n".join([

        f"TCO number: {clean_value(row.get('tco_number'))}",

        f"Chapter: {clean_value(row.get('chapter'))}",

        f"Tariff classification: {clean_value(row.get('tariff_classification'))}",

        f"Description: {clean_value(row.get('description'))}",

        f"Operative date: {clean_value(row.get('operative_date'))}",

        f"Decision date: {clean_value(row.get('decision_date'))}",

        f"Source URL: {clean_value(row.get('source_url'))}",

    ])

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--csv", required=True, help="Path to TCO CSV file")

    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for testing")

    parser.add_argument("--db", default="chroma_tco_db", help="Local Chroma DB folder")

    args = parser.parse_args()

    if not os.path.exists(args.csv):

        raise FileNotFoundError(f"CSV file not found: {args.csv}")

    df = pd.read_csv(args.csv)

    if args.limit:

        df = df.head(args.limit)

    print(f"Loaded {len(df)} rows from {args.csv}")

    model = SentenceTransformer("all-MiniLM-L6-v2")

    client = chromadb.PersistentClient(path=args.db)

    collection = client.get_or_create_collection(

        name="tco_records",

        metadata={"description": "Australian ABF Tariff Concession Orders"}

    )

    documents = []

    ids = []

    metadatas = []

    for idx, row in df.iterrows():

        tco_number = clean_value(row.get("tco_number")) or str(idx)

        doc = make_document(row)

        documents.append(doc)

        ids.append(f"tco_{tco_number}_{idx}")

        metadatas.append({

            "chapter": clean_value(row.get("chapter")),

            "tariff_classification": clean_value(row.get("tariff_classification")),

            "tco_number": clean_value(row.get("tco_number")),

            "operative_date": clean_value(row.get("operative_date")),

            "decision_date": clean_value(row.get("decision_date")),

            "source_url": clean_value(row.get("source_url")),

        })

    batch_size = 250

    for start in range(0, len(documents), batch_size):

        end = start + batch_size

        batch_docs = documents[start:end]

        batch_ids = ids[start:end]

        batch_metas = metadatas[start:end]

        embeddings = model.encode(batch_docs).tolist()

        collection.upsert(

            ids=batch_ids,

            documents=batch_docs,

            embeddings=embeddings,

            metadatas=batch_metas,

        )

        print(f"Ingested {min(end, len(documents))}/{len(documents)}")

    print("")

    print(f"Done. Vector DB created in: {args.db}")

    print("Collection name: tco_records")

if __name__ == "__main__":

    main()

