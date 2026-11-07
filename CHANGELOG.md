# Changelog

Notable changes to Award Wallet. Versions follow [semantic versioning](https://semver.org).

## [Unreleased]

## [0.13.0] - 2026-11-07

### Added
- Rename a program by double-clicking its name on the program's page: type, then Return to save
  or Esc to leave it as it was. Its card shows the new name.
- Chase, Amex and Capital One programs list their transfer partners, the airlines and hotels their
  points move to and at what ratio, folded away on the program's page until you open it.

### Changed
- A **Use miles** (or **Use points**) button under the balance opens the program's site, in place
  of the small paper plane, which was easy to miss.
- Every program starts with its own name, like AAdvantage, and the Link page no longer asks for
  one. A program linked under its company's name, like "American Airlines", now shows the
  program's own name too.

## [0.12.1] - 2026-11-07

### Changed
- An expiration more than three months away is a plain line on the card and the program's page,
  in the same gray as the rest, like "AAdvantage miles expire on Jan 3, 2028 unless the account
  has some activity before then". Only from 90 days before does it turn into the alert, with its
  countdown.
- The alert names what expires ("Miles expire on Feb 5, 2027 (in 90 days)") instead of "Balance
  expires", and its countdown goes down at midnight even while the window stays open.

## [0.12.0] - 2026-11-07

### Added
- American Airlines: each refresh reads when your miles expire from the account summary ("Miles
  expire on Jan 3, 2028"), found by its words rather than its place on the page, so a redesign
  doesn't lose it. The card shows the date instead of the general 24-month rule.
- Three months before a balance expires, its card and its page show an alert with what to do.
  For American: earn or spend any miles, and the date moves 24 months out.

## [0.11.4] - 2026-11-06

### Fixed
- Installing an update no longer makes macOS say Award Wallet "was prevented from modifying apps
  on your Mac". The installer used to clear the "downloaded from the internet" mark from the new
  app once it was in Applications, which macOS counts as one app changing another. It now copies
  the app without that mark instead. The notice still shows once, while updating to this version,
  because the version you're leaving does that install.

## [0.11.3] - 2026-11-06

### Changed
- Each look for the balance reads all of a program's labels in one pass over the page, instead
  of one pass per label. For American Express, with three labels, a look at a page of 40,000
  elements went from about 370 ms to 135 ms, which leaves Chrome more time between looks.

## [0.11.2] - 2026-11-06

### Changed
- **Sign in** starts right away while other programs refresh, instead of waiting for a free
  turn behind them. If the program itself was still waiting for its refresh, the sign-in takes
  that refresh's place; before, it said the program was refreshing and to try again later.

## [0.11.1] - 2026-11-06

### Fixed
- Removing a program, or changing or removing its login, while it refreshes no longer gets in the
  refresh's way. The program's Chrome profile is deleted once that refresh ends; before, Chrome
  could write it again, leaving the site's cookies behind. A sign-in to it that's open stops.
- A refresh that was running when you saved a new login no longer puts the old login back, or
  saves what the old login read. The new login is fetched right after.
- A Chrome profile left behind by a program you removed, like when the app quit before the
  removal finished, is deleted the next time the app opens.

## [0.11.0] - 2026-11-06

### Added
- A refresh that reads less than half of a program's balance, and at least 1,000 fewer, no longer
  goes into the history by itself. The program shows **Check the balance**, and its page asks
  whether to keep the new balance or the one before. A fall that big could be some other number on
  the site's page, or points you didn't spend, which is worth a look at your account.

## [0.10.3] - 2026-11-06

### Fixed
- An expiration you enter by hand on a program that refreshes by itself stays through the
  refreshes, until its date passes. Before, the next refresh dropped it, because the sites don't
  show when points expire. If the balance falls below the amount expiring, the amount shown falls
  with it; entering the balance by hand without a date clears it.

## [0.10.2] - 2026-11-06

### Fixed
- When a site changes its balance page, a refresh says it couldn't find your points or miles
  there. Before, if the page took more than 15 seconds to open, the program said it needed you to
  finish signing in, and **Sign in** then waited five minutes for nothing.
- While you sign in, the note above the page says so too when Award Wallet can't find the balance
  on it, so you know to click **Stop**.
- With no programs linked yet, the dashboard names every program you can link, American Express
  and Delta included.
- The hidden `--check-browser` command, which checks that Chrome starts, works again.

## [0.10.1] - 2026-11-06

### Changed
- The About window no longer shows the folder your data is kept in. Nothing moved: it's still
  `~/Library/Application Support/Award Wallet`, as the README says.

## [0.10.0] - 2026-11-06

### Added
- Delta SkyMiles. Link it with your SkyMiles number (or username) and password, and the app reads
  the miles you can spend from your SkyMiles overview, out of sight like the others. It never
  takes Medallion Qualifying Dollars, pending miles from booked trips, lifetime Million Miler
  miles or a card offer for the balance: if it can't tell, it shows no number rather than a wrong
  one.

## [0.9.0] - 2026-11-06

### Added
- American Express Membership Rewards. Link it with your Amex User ID and password, and the app
  reads your points from your account home, out of sight like the others. It never takes pending
  points, points that come in once you pay, points earned this year or a card offer for the
  balance: if it can't tell, it shows no number rather than a wrong one.

### Changed
- Balances are read the way they look on screen: text that only screen readers get, which sites
  tuck into invisible 1-pixel boxes, no longer counts.

## [0.8.0] - 2026-11-06

### Changed
- **Sign in** happens inside Award Wallet. The site's page shows in the app's window, where you
  click and type like in a browser to finish what the site asks, like a code by text, and
  **Stop** ends it. No Chrome window opens anymore, for anything.
- Sign in now uses the same hidden Chrome as the refreshes. Capital One trusted the Chrome window
  that Sign in used to open but treated the hidden one as a new device, so every refresh after a
  sign-in asked for a code again. Confirming once on the page inside the app teaches Capital One
  the browser that does the refreshes.
- Once you click or type on the site's page, the app types nothing more there: the page is yours.
  A sign-in waits five minutes from your last click or key before it gives up.

### Fixed
- A sign-in you don't finish after a site turned down the saved login keeps it turned down, so a
  refresh never tries that password again.

## [0.7.0] - 2026-11-06

### Changed
- Refreshing is invisible. Chrome signs in and reads your balances with no window, no tab and no
  icon in the Dock, and so does linking a program or saving a new login. Nothing pops up: when a
  site wants something only you can give, like a code by text, the program shows a **Sign in**
  button with a note saying what the site wants, and a Chrome window opens only when you click it.
- The app types logins one key at a time, like a person. Capital One turned down logins that went
  into its form all at once ("We didn't recognize that info"), which is why it kept asking you
  to sign in.
- When a site turns down the saved login, **Sign in** opens its window for you to sign in
  yourself, and the app keeps the login that worked. It never types the old one again.
- History shows each change in a balance, one entry a day at most. A refresh that finds the same
  balance adds nothing, and **Updated** says when the balance was last checked.

### Security
- Only you can open the app's folder, and everything the app writes (its database, logs,
  screenshots and each program's Chrome profile) is readable by you alone.
- The window's pages run only the app's own scripts, can't be shown inside another site, aren't
  kept on disk, and send no address to other sites. Requests from other websites are turned away.
  The window's session lasts one launch, and the launch secret leaves the window's address as
  soon as it's used.
- Updates come only from this repository's own releases on GitHub, never follow a redirect off
  HTTPS, and the .dmg must match the SHA-256 GitHub lists for it, or it's deleted and nothing is
  installed.
- Screenshots in Diagnostics black out every box on the page, so nothing typed shows in them.
  Chrome no longer remembers what's typed into forms, and doesn't save downloads.
- Releases are built only from the locked, hash-checked libraries, and the build has no way to
  push to the repository.

### Fixed
- A page that breaks shows a page with a way back instead of "Internal Server Error", and the
  details go to the Diagnostics log.

## [0.6.0] - 2026-11-06

### Added
- American Airlines AAdvantage. Link it with your AAdvantage number (or username) and password,
  and the app reads your award miles. It never takes Loyalty Points, lifetime miles or a card
  offer for the balance: if it can't tell, it shows no number rather than a wrong one.

### Changed
- Updating is one click, like other Mac apps: **Update now** downloads the new version with a
  progress bar, then the app closes, replaces itself and reopens. No .dmg to open and no second
  button. If the download fails, the page says why and offers **Try again**.
- Updates always land in your Applications folder, even when the app was opened from the .dmg
  or Downloads. Opened from anywhere else, the app offers **Move to Applications**. If
  Applications already has the same or a newer version, that one is kept and opened instead.
- Buttons show they're alive: they light up under the pointer, press in when clicked, and show a
  spinner with what they're doing (**Refreshing…**, **Starting…**) until the page changes.

### Fixed
- An update can no longer leave you without the app. Before, an app opened from the .dmg or
  from a temporary copy macOS makes of downloaded apps tried to replace itself there, failed, and
  didn't reopen. The installer now also never copies a new version over an old one it couldn't
  move aside, and writes what it did to `install.log` in Diagnostics.

## [0.5.1] - 2026-11-01

### Fixed
- Refreshes no longer leave sign-in pages for you to fill in:
  - United: the app now types the username in the "Email or MileagePlus number" box on United's
    account page, then the password. Before, it only did that on pages with "sign in" in their
    address, so United's refresh stopped there.
  - If a site clears the login form once without saying the login was wrong, the app types it
    again. It never types the password more than twice in a refresh, so a wrong password can't
    lock the account.
- Chase: its "Let's make sure it's you" page (a code by text or call) brings the window up right
  away, instead of the app looking for the points on it for 45 seconds and then failing. Sites
  ask this the first time they see the app's browser; after that, refreshes run on their own.
- While a site's window is up for you, the program shows **Waiting for you** with a note saying
  what the site wants.
- Chrome no longer offers to save the password (the app keeps it) or to restore pages after a
  refresh was cut short.
- Refresh windows sit off screen instead of minimized in the Dock, so pages load like they do in
  any open window. Moving the window no longer fails after a site switches the page to another
  process.

## [0.5.0] - 2026-10-31

### Changed
- Sign in once: each program now has its own Chrome profile that the app keeps, and refreshes use
  it in a minimized Chrome window instead of a hidden one. Sites see the same browser every time,
  so they remember this Mac and stop asking for security codes. Logins from older versions carry
  over.
- If a refresh needs a security code anyway, its Chrome window comes up for you to type it,
  instead of the refresh failing.
- Only a login the site rejected pauses automatic refreshes (**Check your login**). A program that
  asked for a code is tried again on the next refresh.

### Fixed
- Chase: reads the Ultimate Rewards points in the dashboard's Rewards box, and never the
  MileagePlus miles listed next to them. The reader also finds numbers drawn inside web
  components, and recognizes every server of a site (Chase's dashboard opens on ones like
  secure07c.chase.com).
- When a site shows its own error, like Capital One's "We can't access your account information
  right now", the app says so instead of waiting five minutes for the sign-in to time out. A
  balance page that never shows the number gives up after 45 seconds, with a screenshot.
- A balance is only taken once it stops changing, for pages that count up to it.

## [0.4.0] - 2026-10-31

### Changed
- All programs refresh at the same time, so balances arrive sooner when the app opens.
- Award Wallet is now only a Mac app for one person: the sign-up and sign-in pages, password
  hashing, the Terminal web server and its settings are gone. Fewer parts, fewer things to break.
- No open-source license: the code is public to read, but all rights are reserved.

### Added
- A log file and failed-fetch screenshots in a Diagnostics folder; **Help → Show Diagnostics in
  Finder** opens it.
- If the app can't start, it says so in a window instead of quietly not opening.

## [0.3.1] - 2026-10-31

### Added
- One-click updates: the app checks for a new version on launch, then downloads it, replaces
  itself and reopens.
- Merging into `main` publishes a release when the version is new.

### Changed
- A connected program's page shows just the balance; changing the login or typing a balance by
  hand are tucked under links.

## [0.3.0] - 2026-10-31

### Added
- Automatic balances for United, Chase and Capital One. Award Wallet signs in through Google
  Chrome with your saved login and reads the balance. The first time, a Chrome window opens so you
  can enter the site's security code; after that the browser is remembered and refreshes run
  quietly.
- Balances refresh every time the app opens, plus a Refresh now button on the dashboard.
- A program that needs you (a security code, or a changed password) says so and offers a Sign in
  button instead of retrying in the background.

## [0.2.0] - 2026-10-31

### Added
- Mac app: Award Wallet opens in its own window from Applications, with no Terminal and no
  sign-in screen. Data lives in `~/Library/Application Support/Award Wallet`.
- Wallet app icon.
- About page and Check for Updates, in the Award Wallet and Help menus.
- A link from each program to its rewards site, to plan trips and transfer points.
- Makefile, lint (ruff), CI and a release workflow that builds the .dmg.

## [0.1.0] - 2026-10-26

### Added
- Accounts, encrypted program logins and manual balances for United MileagePlus, Chase Ultimate
  Rewards and Capital One Miles.
