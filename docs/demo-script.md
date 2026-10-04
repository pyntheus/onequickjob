# A ten-minute demo of OneQuickJob

For Hasan to show his business partner. Every step is real software on test data: the payments
go through a fake gateway and the texts land in an Outbox on screen, never on a phone.

## Before you start (two minutes, on your own)

1. **Reset the demo** so it looks the same every time. On the droplet:

   ```bash
   cd /srv/oqj/main && make seed && make status
   ```

   `make seed` puts back every demo person, job and payment and removes whatever earlier demos
   created. `make status` should end with "make status: OK".
2. **Find the site password.** The site sits behind one shared password (it's a private
   prototype). It's in Hasan's password manager under OneQuickJob; on the droplet,
   `grep BASIC_AUTH /srv/oqj/main/.env` shows the user name and password. Never paste it into
   chat or email.
3. **Open https://dev.onequickjob.co.uk** on a laptop (a phone works too) and enter the user
   name and password. A thin strip at the top reads "Prototype: test payments only".

Two buttons float at the bottom left on every screen:

- **Outbox**: every text and email the system would have sent, newest first, including
  sign-in codes and the links in job alerts. Click a link in a message to follow it.
- **Switch user**: become anyone in the demo in one click (Sarah the customer, Dave and the
  other providers, Tom the helper, Jo and Sam the admins).

## The tour (ten minutes)

### 1. An instant quote (1½ minutes): you as a new customer

1. On the home page, keep **Lawn mowing**, type `Orchard` in **Your address** and pick
   *12 Orchard Way, Hazlemere*. Click **See my price**.
2. Choose **Large** ("about a singles tennis court") and **Continue**.
3. Leave the answers (recently cut, take the clippings away, side gate, every 2 weeks) and
   click **See my price**.

**What it shows:** a guide price of **£31 a visit** in under a minute, with no call-back and
no account, plus the split: £26.35 to the provider, £4.65 to OneQuickJob (15%).
**Why it matters:** this is the hook. People get a fair, explained price at once, and the
commission is always on show: the customer's agreement is with the provider, and we're their
booking and payment agent.

### 2. A booking, and the provider's text alert (2 minutes)

1. Click **Request this job**. Type a name, then Sarah's number under **Mobile number**,
   `07700 900123`, and tap **Text me a code**. Open **Outbox**: the newest message is the
   6-digit code. Type it under **Your code** and tap **Confirm my number**.
2. Sarah's card is already saved (•••• 4242); for a new number, click **Use test card 4242**.
   Nothing is charged until the work is done. Tick the terms and click **Send my request**.
   You're on **Finding someone local**.
3. Open **Outbox** again: there's a **job alert to Dave**. Click its link.

**What it shows:** Dave's provider app opens on the job, signed in by the link in his text, with
the area (not the address), the answers and what he'd earn. Click **Accept at £31**: it's his,
and Sarah's text in the Outbox confirms who's coming and when.
**Why it matters:** no dispatcher. The first local, checked provider to accept books it, and
two can never book the same job.

### 3. Finishing a job (1½ minutes): as Dave

1. In Dave's app tap **Today**, then the day of Sarah's visit in the row of days.
2. On her visit tap **Demo: start it now** (the demo lets a future visit start today). A timer
   runs. Add a **Before photo** and an **After photo** if you like (any picture).
3. Tap **Finish job**. Raise **Minutes taken** past the estimate, tick **Grass was longer than
   described**, and tap **Send and get paid**.

**What it shows:** "£26.35 is on its way": the card was charged, the money split, the
provider's share is due in Friday's payout, and Sarah's receipt (with the after photo) is in the
Outbox. **Why it matters:** providers do nothing about money, and their real times and flags
feed back into the guide prices (step 6).

### 4. The tax pack and the earnings limit (1½ minutes): as Dave

1. Tap **Earnings**: this week, the last eight weeks and the next payout.
2. Tap **Tax and records**: turnover, our fees, mileage worked out from his visits, and whether
   the £1,000 trading allowance or actual costs suit him better. **Download your tax pack** is
   the file for his accountant or HMRC.
3. Back on Earnings, tap **Earnings limit**: a weekly or monthly cap he chooses.

**Why it matters:** many of the people who'll do this work are retired or on benefits.
Records done for them and a limit they control (we never store why they want one) are what make
casual work safe to take on.

### 5. Cover and helpers (1½ minutes)

1. As Dave, in **Today** pick a later day. The **Can't make one of these jobs?** card offers
   **Send Tom** (his son, his helper) or **Get cover** from another local provider.
2. Tap **Get cover**: the alerts go to other checked providers. A covered visit is charged
   at the standard 15% to the provider who does it, and the customer stays Dave's.
3. **Switch user** to **Tom**: his app shows only the visits he's been sent to (his tabs are
   Home, Today and Me), with no jobs list, no prices and no money.

**Why it matters:** regulars don't lose their visits when a provider is ill or away, and a
provider can grow with family help without handing over the business.

### 6. Pricing and calibration (1½ minutes): as an admin

1. **Switch user** to **Jo** and open **Pricing**.
2. The scatter plots every timed job: estimated minutes against actual, with the job Dave just
   finished above the shaded band. The table shows, per job type, how often the guide price was
   taken as it was and how far over the estimate jobs ran.
3. Where a job type runs consistently over, a suggestion offers a new parameter. **Draft this
   change**; it goes live only when a *different* admin (Sam) approves it.

**Why it matters:** the prices learn from real work, under control: one person can't change
prices alone, and every quote records the price version it used.

## Afterwards

Run `make seed` again to put everything back. If something looks wrong, `make status` checks
every part of the site.

Worth mentioning if asked: the **Overview** (as Jo) lists requests nobody has taken, with a
WhatsApp message for the local providers' group and **Raise guide 10%** (the customer approves
any raise first); Mary's own-customer invite (Dave's existing customer joins at a 5% fee) is in
the Outbox as a link.
