# Merchant Crosswalk

Use [data/merchant_crosswalk.md](data/merchant_crosswalk.md) as the editable source of truth.

The analyzer now supports both formats:

- Markdown: human-editable categories and bullet rules
- CSV: legacy/compact format

Sync utility:

- `python crosswalk_sync.py --direction md-to-csv`
- `python crosswalk_sync.py --direction csv-to-md`
