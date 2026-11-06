# Changelog

Notable changes to Award Wallet. Versions follow [semantic versioning](https://semver.org).

## [Unreleased]

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
