# Job Helper

A small app that runs on your own computer. It does four things:

1. **Finds jobs** near a city or ZIP code. You pick the radius, the job type (full time, part time, contract, remote) and the industry (fast food, grocery, retail, customer service, healthcare support, office, warehouse, cleaning, childcare).
2. **Builds your skills bank.** Upload your resume (PDF or Word). The app compares it with the postings and shows which skills employers keep asking for. You pick the ones you really have.
3. **Makes a resume for every job.** Before each application, it writes a fresh copy of your resume. The skills that posting asks for go at the top of the Skills section and into the summary, and the summary names that job title. Files are named like `Jane Doe Resume - Walmart.pdf`.
4. **Applies automatically.** For each queued job it opens the posting, clicks Apply, fills in your details, answers the screening questions you set up, attaches that job's resume, clicks through Next / Submit, and checks for a "thank you for applying" page.

## Filtering out jobs she isn't qualified for

Search results automatically leave out jobs she can't get. They never show up in the results, the Tracker or the queue:

- anything that mentions a **college degree** (associate or higher), even if it's only "preferred". "No degree required" and job titles like "Sales Associate" don't count.
- jobs that **require a license** she doesn't hold (RN, CDL, CNA and so on)
- **senior and director** roles, and **professional titles** like developer, engineer, nurse or accountant, unless that work is on her resume
- jobs asking for **more years** than she has, or 3+ years in an area that isn't on her resume

Fill in **Qualifications** on tab 1 (education, years of experience, licenses she holds) so this works properly. A collapsed "Removed N jobs" list under the results shows what was left out and why.

What's left is rated ✅ **Good fit** or 🟨 **Stretch** (something preferred she doesn't have, a manager title above shift level, or a short certification like CPR).

## Scam check

Every job gets a safety rating in the search results: 🟢 Looks OK, 🟡 Check first, or 🔴 Possible scam.

- **The posting is checked for the usual warning signs:** fees for training or equipment, depositing a check and sending money back, buying gift cards, reshipping packages, interviews over Telegram or WhatsApp, asking for your SSN or bank details before an interview, pay far too high for the work, a Gmail/Yahoo contact address, no company name.
- **Press "Research these companies"** to also check each company's website: whether it loads, and how long ago the domain was registered. A careers site registered a few weeks ago is a classic scam setup.
- **"Why N jobs are flagged"** under the results lists the reasons, with links to look the company up on the Better Business Bureau, BBB Scam Tracker, Indeed and Glassdoor reviews, and a "scam" search.
- **The auto-submitter runs the check before every job.** It skips 🔴 jobs so her details don't get sent to them. You can also have it hold 🟡 jobs for you to look at. "Select all new jobs" leaves 🔴 jobs out too.

A green rating isn't a guarantee. A real employer never asks you to pay to get the job, and never needs your SSN or bank details before an interview.

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

1. Install everything:

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

Pick the sites under "Job sites to search". None of them need a sign-up, except Adzuna.

- **Indeed** (default) has the most hourly and local jobs. Listings are read with the open-source [JobSpy](https://github.com/speedyapply/JobSpy) library. When a posting links to the company's own application page, the app applies there, which skips Indeed's login.
- **ZipRecruiter, Glassdoor, Google Jobs** also work through JobSpy. They sometimes block searches; if one shows an error, leave it out.
- **Remotive** has remote jobs, mostly office and tech roles.
- **Adzuna** is optional. If you want it, get a free key at <https://developer.adzuna.com>, copy `.env.example` to `.env` and paste the App ID and App Key in.

### Employers near you

Job sites only show employers that post there. Publix only takes applications on its own site, many franchise restaurants use their own hiring pages, and small local places just put a sign in the window. Open **🗺️ Employers near you** on the search tab and press **Find employers near me**. It lists the restaurants, grocery stores and shops within your radius, using OpenStreetMap (free, no key), with links to each one's jobs on Google and Indeed and to its careers page. Tick some and press the search button to pull their job-site postings into your results.

### Remote jobs anywhere in the US

Switch **Where** at the top of the search tab to **Remote (anywhere in the US)**. The location and radius go away, and only work-from-home jobs come back, from anywhere in the country. The industries switch to customer service and office work, which is where most entry-level remote jobs are. Remote listings attract a lot of scams, so keep an eye on the safety column. Some remote jobs only hire in certain states, which the posting usually says.

### Search tips

- Pick several industries at once. Fast food, grocery and retail are selected by default.
- Leave **Job type** empty unless she really needs one. Postings that don't state a type are always kept.
- Use **Extra searches** for anything the industries miss ("dollar store, dishwasher, deli"). Each one is searched separately.
- Rural areas have fewer postings, so try a 25–50 mile radius and 30+ days.

## Your data

Everything stays on your computer in the `data/` folder: your details, your original resume, every per-job resume (`data/resumes/`), the job list (`jobs.db`) and the assistant's browser profile. None of it is committed to git.

## Tests

```bash
python -m pytest
```
