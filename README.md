# Job Helper

A small app that runs on your own computer. It does four things:

1. **Finds jobs** near a city or ZIP code. You pick the radius, the job type (full time, part time, contract, remote) and the industry (fast food, grocery, retail, customer service, healthcare support, office, warehouse, cleaning, childcare).
2. **Checks your resume against those postings.** It shows a keyword match score and lists the words employers keep using that your resume doesn't have yet.
3. **Builds a tailored resume.** You tick the missing keywords that are actually true for you, edit the summary, and it writes a clean `.docx` laid out the way applicant tracking systems (ATS) read best.
4. **Helps you apply.** It opens each job you queued in a browser window, clicks *Apply*, fills in your name, email, phone and address, and attaches your resume. You answer the screening questions and press Submit, then hit **I applied ✓** on the bar at the bottom to go to the next job. It keeps a record of every job and its status.

## Why it doesn't press Submit for you

Most applications ask things only you can answer: availability, pay expectations, work authorization, "why do you want to work here". A lot of sites also use CAPTCHAs, and Indeed, LinkedIn and others ban accounts that submit applications automatically. So the assistant does the typing and you make the final click. That usually takes a minute or two per job.

Same idea for the resume: it only adds keywords you tick. Hiding keywords in white text or listing skills you don't have might get you past the filter, but the person reading the resume or doing the interview catches it.

## Setup (one time)

You need Python 3.10 or newer ([python.org](https://www.python.org/downloads/); on Windows, tick "Add Python to PATH" during install).

1. Get a free Adzuna API key at <https://developer.adzuna.com>. Sign up, then copy the **App ID** and **App Key** from the dashboard.
2. Copy `.env.example` to `.env` and paste the two values in.
3. Install everything:

   ```bash
   pip install -r requirements.txt
   ```

   ```bash
   python -m playwright install chromium
   ```

## Running it

Double-click `start.bat` (Windows) or `start.command` (Mac), or run:

```bash
streamlit run app.py
```

It opens in your web browser. Go through the tabs in order:

| Tab | What you do |
| --- | --- |
| 1. Me & my resume | Enter your contact details and upload your resume (.docx is best) |
| 2. Find jobs | Pick location, radius, type and industry, then search. Tick the jobs you want and press **Queue selected** (or "Select all new jobs") |
| 3. Tailor resume | Tick the missing keywords that are true for you, then **Build tailored resume** |
| 4. Apply | Press **Start applying** and work through the queue in the browser window that opens |
| 5. Tracker | See everything, change statuses (interview, offer, rejected) and add notes |

The first time, some sites (Indeed, Workday and so on) will ask you to sign in or make an account. The assistant's browser remembers those logins next time.

## Where job listings come from

- **Adzuna** collects postings from thousands of job boards and company sites. It covers local jobs with location and radius filters.
- **Remotive** is used for remote jobs. It needs no key, but it leans toward office and tech roles.

Big chains (McDonald's, Kroger, Walmart and others) often post on their own careers sites too. If a store you like doesn't show up, check its site directly.

## Your data

Everything stays on your computer in the `data/` folder: your details, your resumes, the job list (`jobs.db`) and the assistant's browser profile. None of it is committed to git.

## Tests

```bash
python -m pytest
```
