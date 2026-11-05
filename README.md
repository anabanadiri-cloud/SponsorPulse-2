# SponsorPulse 2.0

A Streamlit dashboard built from the FINC 314 SponsorPulse Colab notebook, including Investment Direction Tracker, activity chart, deal report, filtering, evidence links and CSV export.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Publish using Streamlit Community Cloud

1. Create a GitHub repository and upload `app.py`, `deals.csv`, and `requirements.txt` to the repository root.
2. Sign into Streamlit Community Cloud, choose **Create app**, and select the GitHub repository and `app.py` as the entrypoint.
3. Deploy, then share the generated website URL.

## Important data limitations

`deals.csv` contains **eight offline fallback records** from the latest notebook, not a fresh web scrape. The labels are outputs of rule-based extraction and have not been independently fact-checked. Verify announcements and URLs against original sources before relying on them. The notebook also includes earlier versions with different row counts; this website uses the **last notebook cell's fallback dataset**. To update, run the validated pipeline and replace `deals.csv` with a schema-compatible export, then redeploy.
