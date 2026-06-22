from flask import Flask, render_template, request
import chromadb
from sentence_transformers import SentenceTransformer

app = Flask(__name__)

DB_PATH = "chroma_tco_db"
COLLECTION_NAME = "tco_records"

model = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path=DB_PATH)
collection = client.get_collection(COLLECTION_NAME)


def normalise_text(value):
    if value is None:
        return ""
    return str(value).lower()


def passes_required_word_filter(document, required_words, match_mode):
    """
    Applies advanced keyword filtering after vector search.

    match_mode:
    - all_words: every required word must appear somewhere in the TCO text
    - any_word: at least one required word must appear
    - exact_phrase: the full phrase must appear exactly
    """

    text = normalise_text(document)
    required = normalise_text(required_words).strip()

    if not required:
        return True

    if match_mode == "exact_phrase":
        return required in text

    words = [w.strip() for w in required.split() if w.strip()]

    if not words:
        return True

    if match_mode == "any_word":
        return any(word in text for word in words)

    # Default: all_words
    return all(word in text for word in words)


@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    query = ""
    chapter = ""
    top = 10
    required_words = ""
    match_mode = "all_words"
    candidate_pool = 100
    searched = False
    filtered_out_count = 0

    if request.method == "POST":
        searched = True

        query = request.form.get("query", "").strip()
        chapter = request.form.get("chapter", "").strip()
        required_words = request.form.get("required_words", "").strip()
        match_mode = request.form.get("match_mode", "all_words").strip()
        top = int(request.form.get("top", 10))
        candidate_pool = int(request.form.get("candidate_pool", 100))

        # Make sure candidate pool is at least as large as the number of requested final results.
        if candidate_pool < top:
            candidate_pool = top

        if query:
            query_embedding = model.encode([query]).tolist()[0]

            where_filter = None
            if chapter:
                where_filter = {"chapter": chapter}

            response = collection.query(
                query_embeddings=[query_embedding],
                n_results=candidate_pool,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )

            docs = response["documents"][0]
            metas = response["metadatas"][0]
            distances = response["distances"][0]

            for doc, meta, distance in zip(docs, metas, distances):
                if passes_required_word_filter(doc, required_words, match_mode):
                    results.append({
                        "distance": round(distance, 4),
                        "tco_number": meta.get("tco_number", ""),
                        "chapter": meta.get("chapter", ""),
                        "tariff_classification": meta.get("tariff_classification", ""),
                        "operative_date": meta.get("operative_date", ""),
                        "decision_date": meta.get("decision_date", ""),
                        "source_url": meta.get("source_url", ""),
                        "document": doc
                    })
                else:
                    filtered_out_count += 1

                if len(results) >= top:
                    break

    return render_template(
        "index.html",
        results=results,
        query=query,
        chapter=chapter,
        top=top,
        required_words=required_words,
        match_mode=match_mode,
        candidate_pool=candidate_pool,
        searched=searched,
        filtered_out_count=filtered_out_count
    )


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
