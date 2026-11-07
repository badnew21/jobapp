# Job Helper

A small app that runs on your own computer. It does four things:

1. **Finds jobs** near a city or ZIP code. You pick the radius, the job type (full time, part time, contract, remote) and the industry (fast food, grocery, retail, customer service, healthcare support, office, warehouse, cleaning, childcare).
2. **Builds your skills bank.** Upload your resume (PDF or Word). The app compares it with the postings and shows which skills employers keep asking for. You pick the ones you really have.
3. **Makes a resume for every job.** Before each application, it writes a fresh copy of your resume. The skills that posting asks for go at the top of the Skills section and into the summary, and the summary names that job title. Files are named like `Jane Doe Resume - Walmart.pdf`.
4. **Applies automatically.** For each queued job it opens the posting, clicks Apply, fills in your details, answers the screening questions you set up, attaches that job's resume, clicks through Next / Submit, and checks for a "thank you for applying" page.

## What happens when it can't finish a job

It never guesses. If an application has a CAPTCHA, wants you to log in or create an account, asks a question you haven't answered (felony history, a custom essay question and so on), or shows an error after Submit, the job goes to **Needs review** with the reason. Press **Open these so I can finish them** on the Apply tab and it opens each one, filled in as far as it got.

Some things to know:

- **Do a test run first.** "Test run" fills every form but stops before the final Submit, so you can check it's doing the right thing. It's switched on until your first real application.
- **Daily limit (default 40) and a 20-45 second pause between jobs.** Sites flag accounts that send hundreds of applications a day.
- **Indeed and LinkedIn don't allow automated applying** and can suspend accounts that do it. Their "Easy Apply" flows usually need a login, so those jobs land in Needs review anyway. Finish them with the review mode.
- **The screening answers are yours to get right.** Answer them truthfully in tab 1. Saying "yes" to something that isn't true can get an offer pulled later.
- It only adds skills from your bank to a resume. Nothing hidden.

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
| 1. Me & my resume | Enter your contact details and screening answers, and upload your resume (PDF or .docx) |
| 2. Find jobs | Pick location, radius, type and industry, then search. Tick the jobs you want and press **Queue selected** (or "Select all new jobs") |
| 3. Tailor resume | Pick the skills you really have and save. Preview the resume it will make for any job |
| 4. Apply | Choose **Automatically** or **Review each one** and press **Start**. Check **Needs review** afterwards |
| 5. Tracker | See everything, change statuses (interview, offer, rejected) and add notes |

The first time, some sites (Indeed, Workday and so on) will ask you to sign in or make an account. The assistant's browser remembers those logins next time.

## Where job listings come from

- **Adzuna** collects postings from thousands of job boards and company sites. It covers local jobs with location and radius filters.
- **Remotive** is used for remote jobs. It needs no key, but it leans toward office and tech roles.

Big chains (McDonald's, Kroger, Walmart and others) often post on their own careers sites too. If a store you like doesn't show up, check its site directly.

## Your data

Everything stays on your computer in the `data/` folder: your details, your original resume, every per-job resume (`data/resumes/`), the job list (`jobs.db`) and the assistant's browser profile. None of it is committed to git.

## Tests

```bash
python -m pytest
```
