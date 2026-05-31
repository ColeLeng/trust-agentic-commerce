# Salminen Holdout — Honest Eval Set

OWNER: Blue / Eval

This folder is where you drop the **Salminen fake-review dataset** (~40k labeled
reviews, real genuine vs. computer-generated/fake). The blue **scout detector**
(`blue/signals.py`) is **never** trained or tuned on this — it's the honest
precision/recall check in `eval/run_eval.py` (report (B)).

> Salminen, J., Kandpal, C., Kamel, A.M., Jung, S., Jansen, B.J. (2022).
> *Creating and detecting fake reviews of online products.*
> Journal of Retailing and Consumer Services.

## How to drop it in

1. Download the dataset (commonly distributed as `fake_reviews_dataset.csv`):
   - Kaggle: search "fake reviews dataset" (Salminen et al.)
   - Or the authors' Open Science Framework / GitHub release.
2. Save the CSV **into this folder**, e.g.:

   ```
   data/salminen_holdout/fake_reviews_dataset.csv
   ```

3. Run the eval:

   ```bash
   python eval/run_eval.py
   ```

## Expected CSV shape

`eval/run_eval.py` is tolerant but expects roughly these columns:

| column     | meaning                                         |
|------------|-------------------------------------------------|
| `category` | product category (optional)                     |
| `rating`   | 1–5 star rating (optional)                       |
| `label`    | `CG` = computer-generated/fake, `OR` = original |
| `text_`    | the review text                                  |

If column names differ, edit the `COLUMN_MAP` at the top of `eval/run_eval.py`.

## Mock-first note

`eval/run_eval.py` runs **with no CSV present** — it falls back to a small built-in
labeled sample so the eval pipeline is demoable on a fresh clone. The real numbers
only appear once you drop the actual Salminen CSV here.

> The CSV files in this folder are git-ignored. Do **not** commit the dataset.
