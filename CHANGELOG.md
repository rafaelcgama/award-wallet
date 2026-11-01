# Changelog

Notable changes to Award Wallet. Versions follow [semantic versioning](https://semver.org).

## [Unreleased]

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
