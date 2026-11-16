# Sitemap watch

Checks a list of sitemaps once a week and records which page URLs are new
(and which have gone). Runs on GitHub Actions; results are browsed and
downloaded from a GitHub Pages site.

## Setting it up

1. Create a new GitHub repository and upload everything in this folder,
   keeping the folder structure (including the hidden `.github` folder).
2. In the repository, go to Settings, then Pages. Set the source to
   "Deploy from a branch", choose the `main` branch and the `/docs` folder,
   and save. GitHub shows the web address of the page once it is live.
3. Go to Settings, then Actions, then General. Under "Workflow permissions"
   choose "Read and write permissions" and save.
4. Go to the Actions tab, open "Weekly sitemap check" and press
   "Run workflow". This first run saves the starting point for each sitemap.
5. After that it runs by itself every Monday morning. Run it by hand again
   whenever you want an extra check.

## Adding sitemaps

Edit `sitemaps.txt` on GitHub and add the address on a new line. The next run
saves its starting point, and new pages are reported from the run after that.
Sitemaps that point to other sitemaps (an index) are followed automatically.

## What is stored

- `snapshots/` holds one plain list of URLs per sitemap, which is last run's
  copy. It is replaced each run, so nothing builds up.
- `docs/deltas/new_urls_YYYY-MM-DD.csv` is written only in weeks where
  something changed. Columns: date, site, change (added or removed), url.
- `docs/deltas/manifest.json` feeds the web page.

## If something goes wrong

- If a sitemap cannot be read, the run is marked as failed (GitHub emails
  you) and the web page shows which one. Its saved copy is left alone, so the
  next good run still compares against the right list. The other sitemaps are
  still processed.
- If a site blocks the request, you will see a 403 error in the run log. The
  `USER_AGENT` line near the top of `monitor.py` can be changed.
