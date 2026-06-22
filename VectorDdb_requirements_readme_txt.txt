

Starting and stopping the local web page server
-----------------------------------------------

The local web page UI is run by the Flask app:

app.py

The web page lets you query the local Chroma vector database from a browser instead of using the command line.

The local web address is:

http://127.0.0.1:5000

This address means the app is running on this computer only.


Start the web page server
-------------------------

From the project folder:

/Users/simonprowse/Documents/PythonScraper

activate the Python virtual environment:

source .venv/bin/activate

Then start the Flask app:

python app.py

If successful, Terminal will show something like:

* Serving Flask app 'app'
* Running on http://127.0.0.1:5000
Press CTRL+C to quit

Once that appears, open a browser and go to:

http://127.0.0.1:5000

Leave the Terminal window open while using the web page.


Stop the web page server
------------------------

To stop the server, click back into the Terminal window where python app.py is running.

Then press:

CTRL + C

The server will stop and the normal command prompt should return, for example:

(.venv) simonprowse@simons-MacBook-Pro PythonScraper %

Once the server is stopped, the web page at http://127.0.0.1:5000 will no longer work until the app is started again.


Restart the web page server
---------------------------

If changes are made to app.py or the HTML template, stop the server with:

CTRL + C

Then restart it:

python app.py


Flask development server warning
--------------------------------

When the app starts, Flask may show this warning:

WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.

This warning is normal.

It means Flask's built-in server is intended for local development and testing, not for running a public production website.

For this local proof-of-concept, it is acceptable because the app is running at:

http://127.0.0.1:5000

The address 127.0.0.1 means localhost, which is this computer only.

A production WSGI server would only be needed if the app was later deployed for other users, hosted on the internet, used inside a company network, or turned into a proper SaaS product.


Useful troubleshooting
----------------------

If the browser cannot open the app, check that the Terminal still shows:

Running on http://127.0.0.1:5000

If the Terminal prompt has returned, the server is not running.

Start it again with:

python app.py

If port 5000 is already in use, stop the previous server with CTRL + C or close the old Terminal process.

If the app appears to be stuck after running python app.py, it is probably not stuck. It is normally waiting for browser requests.

Open:

http://127.0.0.1:5000



cat > VectorDdb_requirements_readme_txt.txt <<'TXT'
Vector DB Requirements / README
================================

Project purpose
---------------

This local vector database is a proof-of-concept for searching Australian Tariff Concession Order (TCO) records by meaning rather than exact keyword matching.

The purpose is to test whether importer product descriptions, supplier catalogue descriptions, invoice descriptions, or internal SKU descriptions can be compared against existing TCO records to find possible tariff concession matches.

This database should be treated as a candidate-finding and research tool only. It should not be treated as a final customs, legal, or compliance decision engine.

A better production workflow would be:

1. Importer product / SKU / invoice / supplier description is entered.
2. Vector search finds similar TCO records.
3. Rules and filters check tariff chapter, tariff classification, dates, product wording, and exclusions.
4. AI summarises the evidence.
5. A customs broker or compliance person reviews the result before any claim is made.


Current project location
------------------------

Main project folder:

/Users/simonprowse/Documents/PythonScraper

Python virtual environment:

/Users/simonprowse/Documents/PythonScraper/.venv

TCO source CSV file:

/Users/simonprowse/Documents/PythonScraper/out_tco/tco_records.csv

Local Chroma vector database folder:

/Users/simonprowse/Documents/PythonScraper/chroma_tco_db

Ingest script:

/Users/simonprowse/Documents/PythonScraper/ingest_tco_csv.py

Query script:

/Users/simonprowse/Documents/PythonScraper/query_tco_db.py


Data ingested
-------------

The vector database was created from:

out_tco/tco_records.csv

The file contained 17,719 TCO records.

Important CSV columns:

chapter
tariff_classification
tco_number
description
operative_date
decision_date
source_url

Each TCO record was converted into text containing the TCO number, chapter, tariff classification, description, operative date, decision date, and source URL.

That text was then converted into a vector embedding and stored in ChromaDB.


What a vector database does
---------------------------

A normal keyword search looks for exact or near-exact words.

A vector database searches by semantic similarity, meaning it can find records that are conceptually similar even when the wording is different.

For example, it may help connect terms like:

hydraulic fitting
fluid connector
coupling adapter
hose assembly
pipe fitting

This is useful because supplier descriptions, customs records, product catalogues, invoices, and government TCO descriptions may all describe similar goods using different language.


Installed packages
------------------

The main Python packages installed for this proof-of-concept are:

1. pandas

Purpose:

pandas is used to read and process the CSV file.

In this project, pandas loads:

out_tco/tco_records.csv

and allows the ingest script to loop through each TCO row.

Installed using:

pip install pandas


2. chromadb

Purpose:

ChromaDB is the local vector database.

It stores:

- document text
- vector embeddings
- metadata such as chapter, tariff classification, TCO number, dates, and source URL

In this project, ChromaDB stores the local database in:

/Users/simonprowse/Documents/PythonScraper/chroma_tco_db

Installed using:

pip install chromadb


3. sentence-transformers

Purpose:

sentence-transformers provides the embedding model that converts text into vectors.

In this project, the model used is:

all-MiniLM-L6-v2

This model converts each TCO record description into a numerical vector that can be compared with other vectors.

Installed using:

pip install sentence-transformers


Embedding model
---------------

Model used:

all-MiniLM-L6-v2

Purpose:

This is a lightweight sentence embedding model suitable for local development and testing. It is fast enough for a laptop and good enough for a proof-of-concept semantic search system.

The model was downloaded automatically when the ingest/query scripts first ran.

A warning appeared:

"Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads."

This warning is not fatal. It means the model was downloaded from Hugging Face without logging in. For this local test, it is acceptable.


Important commands
------------------

Activate the Python virtual environment:

source .venv/bin/activate

Install required packages:

pip install pandas chromadb sentence-transformers

Ingest the first 1,000 records as a test:

python ingest_tco_csv.py --csv out_tco/tco_records.csv --limit 1000

Ingest the full TCO CSV file:

python ingest_tco_csv.py --csv out_tco/tco_records.csv

Query the vector database:

python query_tco_db.py "hydraulic hose fittings for mining equipment"

Query with a chapter filter:

python query_tco_db.py "hydraulic pump coupling adapter" --chapter 84


Files created by the vector DB process
--------------------------------------

chroma_tco_db/

This folder contains the local persistent Chroma vector database.

Do not delete this folder unless you want to rebuild the vector database from the CSV.

ingest_tco_csv.py

This script reads the TCO CSV, converts each record into searchable text, creates embeddings, and stores them in ChromaDB.

query_tco_db.py

This script takes a search phrase, converts it into an embedding, searches the vector database, and prints the closest matching TCO records.


Current result
--------------

The full ingest completed successfully.

Rows ingested:

17,719

Database folder:

chroma_tco_db

Collection name:

tco_records


Important limitations
---------------------

This vector database does not prove that a product qualifies for a TCO.

It only finds potentially similar TCO records.

A match can be semantically similar but still legally or technically wrong.

Examples of details that still need checking:

- exact product description
- tariff classification
- active or expired TCO status
- material
- size
- use case
- exclusions
- date of import
- country of origin
- customs rulings
- ABF interpretation
- broker or legal review

The vector DB should be used as a research and discovery tool, not as the final authority.


Recommended next steps
----------------------

1. Add importer product descriptions into a separate CSV.
2. Create a second vector collection for importer SKUs or supplier catalogue records.
3. Compare importer products against TCO records.
4. Add filters for tariff chapter and tariff classification.
5. Add a scoring/reporting layer.
6. Generate a candidate list for human review.
7. Keep source URLs and evidence attached to every result.

Possible future collections:

- tco_records
- importer_skus
- supplier_catalogues
- invoices
- broker_notes
- product_datasheets
- past_claims
- customs_rulings


Plain-English summary
---------------------

This local vector database is an experimental search engine for TCO records.

It helps find TCOs that may be relevant to a product description, even when the wording is not identical.

It is useful for exploring whether an importer may have missed possible duty concessions or refund opportunities.

It is not a replacement for customs compliance review.
TXT

